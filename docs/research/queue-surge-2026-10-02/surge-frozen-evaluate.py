"""Research-only frozen inference and later evaluation; no fitting/network.

Forecast issuance uses past only. Unknown future is pending/unassessable,
never silently a negative. Wide-window classifier is not precise timing.
"""
import argparse,bisect,gzip,hashlib,json,math
from collections import defaultdict
from datetime import datetime,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import numpy as np

root=Path('C:/AI/AvelRen/dist');zone=ZoneInfo('Europe/Kyiv')
ap=argparse.ArgumentParser()
ap.add_argument('--new-data',type=Path)
ap.add_argument('--start',default='2026-10-02T00:00:00+03:00')
ap.add_argument('--end',default='2026-10-09T00:00:00+03:00')
ap.add_argument('--output',type=Path,default=root/'surge-frozen-evaluation.json')
args=ap.parse_args()
model_path=root/'surge-frozen-24h-20261002.json'
model=json.loads(model_path.read_text());model_hash=hashlib.sha256(model_path.read_bytes()).hexdigest()
assert model_hash=='331320e05c62ec027744dab387ba40c859a9c1070821afc3910f4358bb3b90bb','frozen model changed'
start=int(datetime.fromisoformat(args.start).timestamp());end=int(datetime.fromisoformat(args.end).timestamp())
assert start<end
mu=np.array(model['feature_mean']);sd=np.array(model['feature_std']);coef=np.array(model['coefficients'])
assert len(mu)==len(sd)==15 and len(coef)==16 and np.all(sd>0)
data=defaultdict(list);keys=set();sources={}
paths=[root/name for name in model['source_hashes']]
if args.new_data:paths.append(args.new_data)
for path in paths:
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    if path.name in model['source_hashes']:assert digest==model['source_hashes'][path.name]
    sources[path.name]=digest
    for cp,t,c,p in json.loads(gzip.decompress(path.read_bytes())):
        assert cp in (1,6,17,29) and c>=0 and isinstance(p,bool)
        assert (cp,t) not in keys,'duplicate input key'
        keys.add((cp,t));data[cp].append((t,c,p))

predictions=[];eligible=set();events_all=set();quality_rejections=0;pending_origins=0
for cp,rows in data.items():
    rows.sort();times=np.array([r[0] for r in rows]);counts=np.array([r[1] for r in rows]);paused=np.array([r[2] for r in rows])
    def closest(goal):
        k=bisect.bisect_left(times,goal);options=[v for v in (k-1,k) if 0<=v<len(times)]
        return min(options,key=lambda v:abs(times[v]-goal))
    def good(i,j,minutes,max_gap,coverage=True):
        return j>=i and abs(times[j]-times[i]-minutes*60)<=60 and (not coverage or (j-i+1)/(minutes+1)>=.95) and np.all(np.diff(times[i:j+1])<=max_gap)
    events=[];last_window=-10**20
    for j,t in enumerate(times):
        i=closest(t-300)
        if i<j and abs(times[i]-(t-300))<=30 and good(i,j,5,90,False) and counts[j]-counts[i]>=20:
            s=int(times[i])
            if s>last_window+1800:events.append(s)
            last_window=s
    events_all.update((cp,e) for e in events if start<=e<end)
    for j,t in enumerate(times):
        if not start<=t<end:continue
        local=datetime.fromtimestamp(int(t),timezone.utc).astimezone(zone)
        if local.minute!=0:continue
        lags=[]
        for minutes in (5,10,20,60):
            i=closest(t-minutes*60)
            if i>j or abs(times[i]-(t-minutes*60))>30 or not good(i,j,minutes,90,False):break
            lags.append(float(counts[j]-counts[i]))
        if len(lags)!=4:quality_rejections+=1;continue
        long_ok=True
        for minutes in (120,240):
            i=closest(t-minutes*60)
            if abs(times[i]-(t-minutes*60))>30 or not good(i,j,minutes,300):long_ok=False;break
        if not long_ok:quality_rejections+=1;continue
        phase=local.hour*60+local.minute
        f=np.array([counts[j],*lags,lags[0]-lags[1]/2,float(paused[j]),
                    math.sin(2*math.pi*phase/1440),math.cos(2*math.pi*phase/1440),
                    math.sin(2*math.pi*local.weekday()/7),math.cos(2*math.pi*local.weekday()/7),
                    *(int(cp==v) for v in (1,6,17,29))])
        z=coef[0]+((f-mu)/sd)@coef[1:];score=float(1/(1+np.exp(-np.clip(z,-30,30))))
        label_end=int(t)+1440*60+300
        if label_end>times[-1]:status='pending_future';pending_origins+=1
        else:
            k=closest(label_end)
            status='assessable' if abs(times[k]-label_end)<=30 and good(j,k,1445,300) else 'future_data_gap'
        reachable=[e for e in events if t+3600<=e<=t+86400] if status=='assessable' else []
        eligible.update((cp,e) for e in reachable)
        predictions.append({'cp':cp,'origin':int(t),'score':score,'future_status':status,'events':reachable})

alerts=[];last={}
for p in sorted(predictions,key=lambda v:(v['origin'],v['cp'])):
    if p['score']>=model['threshold'] and p['origin']-last.get(p['cp'],-10**20)>=3600:
        alerts.append(dict(p));last[p['cp']]=p['origin']
matched=set();correct=0;false=0
for p in alerts:
    if p['future_status']!='assessable':p['outcome']='not_yet_assessable';continue
    possibilities=[e for e in p['events'] if (p['cp'],e) not in matched]
    if possibilities:
        e=min(possibilities);matched.add((p['cp'],e));correct+=1;p['outcome']='matched';p['matched_event']=e
    else:false+=1;p['outcome']='unmatched'
out={'model_sha256':model_hash,'source_hashes':sources,'origins_interval':[args.start,args.end],
     'status':'research_only; no 99% acceptance; event time/magnitude not predicted',
     'origin_scores':predictions,
     'predictions':len(predictions),'pending_origins':pending_origins,'past_quality_rejections':quality_rejections,
     'alerts':alerts,'correct_alerts':correct,'false_alerts':false,
     'unassessable_alerts':len(alerts)-correct-false,'eligible_events':len(eligible),'detected_events':len(matched),
     'observed_labeled_events_in_origin_interval':len(events_all),
     'observed_events_without_assessable_origin':[{'cp':cp,'time':e} for cp,e in sorted(events_all-eligible)],
     'precision_on_assessable_alerts':correct/(correct+false) if correct+false else None,
     'recall_on_eligible_events':len(matched)/len(eligible) if eligible else None,
     'note':'Unknown future and data gaps are not counted as negatives; cannot claim overall recall from eligible-only denominator.'}
args.output.write_text(json.dumps(out,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in out.items() if k not in ('alerts','origin_scores')},indent=2))
