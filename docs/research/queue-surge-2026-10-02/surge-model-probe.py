"""Throwaway offline probe, not application code or a validated forecast.

Event: >=20 net vehicles within 5 minutes. Overlapping/gap<=30 minute
windows form one event. Compare calendar, momentum, and regularized logistic
scores. Train/validation/test are chronological with purged label horizons.
No requests to the source, server writes, or probability accuracy claim.
"""
import argparse, bisect, gzip, hashlib, json, math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
from zoneinfo import ZoneInfo

ROOT=Path('C:/AI/AvelRen/dist')
source=ROOT/'queue-surge-28days.json.gz'
raw=json.loads(gzip.decompress(source.read_bytes()))
parser=argparse.ArgumentParser()
parser.add_argument('--older',action='store_true')
parser.add_argument('--advanced',action='store_true')
args=parser.parse_args()
source_hashes={source.name:hashlib.sha256(source.read_bytes()).hexdigest()}
if args.older:
    older=ROOT/'queue-surge-older-20260806-0903.json.gz'
    raw=json.loads(gzip.decompress(older.read_bytes()))+raw
    source_hashes[older.name]=hashlib.sha256(older.read_bytes()).hexdigest()
assert len(raw)==len({(r[0],r[1]) for r in raw}), 'overlapping source rows'
zone=ZoneInfo('Europe/Kyiv')
def stamp(s): return int(datetime.fromisoformat(s).timestamp())
START=stamp('2026-09-04T00:00:00+03:00')
VALIDATION=stamp('2026-09-18T00:00:00+03:00')
TEST=stamp('2026-09-25T00:00:00+03:00')
END=stamp('2026-10-02T00:00:00+03:00')
data=defaultdict(list)
for cp,t,c,p in raw: data[cp].append((t,c,p))
CP=(1,6,17,29)
report={'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
        'source_hashes':source_hashes,'source_records':len(raw),
        'definition':'net increase >=20 in 5 minutes; windows within 30 minutes clustered',
        'splits_kyiv':['train Aug06-Sep17' if args.older else 'train Sep04-17','validation Sep18-24','test Sep25-Oct01'],
        'limitation':'already inspected exploratory period, not untouched final holdout; no calibrated probabilities',
        'future_quality':'>=95% expected minute samples; no gap >5min; endpoint tolerance 30 seconds',
        'results':{},'events':{}}
series={}
for cp,rows in data.items():
    rows.sort()
    t=np.array([r[0] for r in rows],dtype=np.int64)
    c=np.array([r[1] for r in rows],dtype=float)
    p=np.array([r[2] for r in rows],dtype=float)
    bad=np.concatenate(([0],np.cumsum(np.diff(t)>90)))
    severe=np.concatenate(([0],np.cumsum(np.diff(t)>300)))
    starts=[]
    for j,end in enumerate(t):
        i=bisect.bisect_left(t,end-300)
        choices=[k for k in (i-1,i) if 0<=k<j]
        if not choices: continue
        i=min(choices,key=lambda k:abs(int(t[k])-int(end-300)))
        if abs(t[i]-(end-300))<=30 and bad[j]==bad[i] and c[j]-c[i]>=20:
            start=int(t[i])
            if not starts or start>last_window+1800: starts.append(start)
            last_window=start
    series[cp]=(t,c,p,bad,severe,np.array(starts,dtype=np.int64))
    report['events'][str(cp)]=[datetime.fromtimestamp(x,timezone.utc).astimezone(zone).isoformat() for x in starts]

def samples(horizon_min,lead_min):
    output=[]
    for cp,(t,c,p,bad,severe,events) in series.items():
        for j,origin in enumerate(t):
            local=datetime.fromtimestamp(int(origin),timezone.utc).astimezone(zone)
            if horizon_min==1440:
                if local.hour!=0 or local.minute!=0: continue
            elif local.minute%5: continue
            boundary=VALIDATION if origin<VALIDATION else TEST if origin<TEST else END
            future_end=int(origin)+horizon_min*60
            # Extra 5min are needed to verify the event window at horizon end.
            label_end=future_end+300
            if label_end>=boundary: continue
            lag=[]
            for minute in (5,10,20,60):
                goal=int(origin)-minute*60
                i=bisect.bisect_left(t,goal)
                options=[k for k in (i-1,i) if 0<=k<=j]
                if not options: break
                k=min(options,key=lambda k:abs(int(t[k])-goal))
                if abs(t[k]-goal)>30 or bad[k]!=bad[j]: break
                lag.append(float(c[j]-c[k]))
            if len(lag)!=4: continue
            k=bisect.bisect_left(t,label_end)
            if k>=len(t) or abs(t[k]-label_end)>30: continue
            expected=(label_end-int(origin))/60+1
            if (k-j+1)/expected<.95 or severe[k]!=severe[j]: continue
            phase=local.hour*60+local.minute
            features=[c[j],*lag,lag[0]-lag[1]/2,p[j],
                      math.sin(2*math.pi*phase/1440),math.cos(2*math.pi*phase/1440),
                      math.sin(2*math.pi*local.weekday()/7),math.cos(2*math.pi*local.weekday()/7),
                      *(int(cp==x) for x in CP)]
            eligible=events[(events>=int(origin)+lead_min*60)&(events<=future_end)]
            output.append({'cp':cp,'origin':int(origin),'features':features,'y':int(len(eligible)>0),
                           'events':eligible.tolist(),'weekday':local.weekday(),'hourbin':local.hour//3})
    return output

def score_alerts(rows,scores,threshold,lead,horizon):
    alerts=[]; last={}
    for row,score in sorted(zip(rows,scores),key=lambda x:x[0]['origin']):
        if score<threshold: continue
        cp,origin=row['cp'],row['origin']
        if origin-last.get(cp,-10**20)<3600: continue
        alerts.append(row); last[cp]=origin
    eligible={(r['cp'],e) for r in rows for e in r['events']}
    matched=set(); successes=[]; matched_details=[]
    for r in alerts:
        possibilities=sorted(e for cp,e in eligible if cp==r['cp'] and
                    r['origin']+lead*60<=e<=r['origin']+horizon*60 and (cp,e) not in matched)
        if possibilities:
            e=possibilities[0]; matched.add((r['cp'],e)); successes.append((e-r['origin'])/60)
            matched_details.append({'checkpoint_id':r['cp'],
                'issued_at':datetime.fromtimestamp(r['origin'],timezone.utc).astimezone(zone).isoformat(),
                'event_start':datetime.fromtimestamp(e,timezone.utc).astimezone(zone).isoformat(),
                'lead_minutes':(e-r['origin'])/60})
    precision=len(matched)/len(alerts) if alerts else 0
    recall=len(matched)/len(eligible) if eligible else 0
    return {'alerts':len(alerts),'correct_alerts':len(matched),'false_alerts':len(alerts)-len(matched),
            'eligible_events':len(eligible),'detected_events':len(matched),
            'precision':round(precision,4),'recall':round(recall,4),
            'f1':2*precision*recall/(precision+recall) if precision+recall else 0,
            'mean_lead_minutes':round(float(np.mean(successes)),1) if successes else None,
            'detected_chop_oct1_afternoon':any(cp==17 and datetime.fromtimestamp(e,timezone.utc).astimezone(zone).date().isoformat()=='2026-10-01'
                and 17<=datetime.fromtimestamp(e,timezone.utc).astimezone(zone).hour<18 for cp,e in matched),
            'matched_events':matched_details}

for horizon,lead in ((60,15),(1440,60)):
    rows=samples(horizon,lead)
    train=[r for r in rows if r['origin']<VALIDATION]
    val=[r for r in rows if VALIDATION<=r['origin']<TEST]
    test=[r for r in rows if r['origin']>=TEST]
    print('DATA',horizon,[(len(x),sum(r['y'] for r in x)) for x in (train,val,test)],flush=True)
    if not train or not val or not test or not sum(r['y'] for r in train):
        report['results'][str(horizon)]={'status':'insufficient_labels'};continue
    x=np.array([r['features'] for r in train]); y=np.array([r['y'] for r in train],dtype=float)
    mu=x.mean(axis=0); sd=x.std(axis=0);sd[sd<1e-8]=1
    def matrix(rs): return np.column_stack((np.ones(len(rs)),(np.array([r['features'] for r in rs])-mu)/sd))
    design=matrix(train); w=np.zeros(design.shape[1]);
    weights=np.where(y==1,len(y)/(2*y.sum()),len(y)/(2*(len(y)-y.sum())))
    for step in range(500):
        probability=1/(1+np.exp(-np.clip(design@w,-30,30)))
        gradient=design.T@((probability-y)*weights)/len(y)
        gradient[1:]+=.03*w[1:]
        w-=.08*gradient
    bins=defaultdict(list)
    for r in train:bins[(r['cp'],r['weekday'],r['hourbin'])].append(r['y'])
    base=float(y.mean())
    def calendar(rs):
        return np.array([(sum(bins[(r['cp'],r['weekday'],r['hourbin'])])+5*base)/(len(bins[(r['cp'],r['weekday'],r['hourbin'])])+5) for r in rs])
    def momentum(rs):return np.array([max(0,r['features'][1]/20,r['features'][2]/40) for r in rs])
    metrics={'split_samples':[len(train),len(val),len(test)],'positive_samples':[int(y.sum()),sum(r['y'] for r in val),sum(r['y'] for r in test)],'methods':{}}
    methods=[('calendar',calendar),('momentum',momentum),('logistic',lambda rs:1/(1+np.exp(-np.clip(matrix(rs)@w,-30,30))))]
    if args.advanced and horizon==60:
        from scipy.optimize import minimize
        def expanded(rs):
            z=(np.array([r['features'] for r in rs])-mu)/sd
            z=np.clip(z,-8,8)
            # CP-specific behavior plus curvature; transforms are fixed before test.
            return np.column_stack((np.ones(len(rs)),z,z[:,:7]**2,
                *(z[:,:7]*z[:,k:k+1] for k in range(11,15))))
        qx=expanded(train)
        def objective(coef):
            logits=qx@coef
            loss=float(np.mean(weights*(np.logaddexp(0,logits)-y*logits))+.03/2*np.sum(coef[1:]**2))
            prob=1/(1+np.exp(-np.clip(logits,-30,30)))
            grad=qx.T@((prob-y)*weights)/len(y)
            grad[1:]+=.03*coef[1:]
            return loss,grad
        fit=minimize(objective,np.zeros(qx.shape[1]),jac=True,method='L-BFGS-B',options={'maxiter':200,'ftol':1e-9})
        metrics['nonlinear_fit']={'converged':bool(fit.success),'iterations':int(fit.nit),'features':int(qx.shape[1])}
        methods.append(('nonlinear_logistic',lambda rs:1/(1+np.exp(-np.clip(expanded(rs)@fit.x,-30,30)))))

        # Histogram Newton boosting with decision stumps: research baseline only.
        cuts=[np.unique(np.quantile(x[:,k],np.linspace(.05,.95,19))) for k in range(x.shape[1])]
        indices=[np.searchsorted(cuts[k],x[:,k],side='left') for k in range(x.shape[1])]
        logits=np.zeros(len(y)); stumps=[]
        for iteration in range(80):
            prob=1/(1+np.exp(-np.clip(logits,-30,30)))
            gradient=weights*(y-prob); hessian=weights*prob*(1-prob)
            best=None
            for k,histogram_bins in enumerate(indices):
                size=len(cuts[k])+1
                gs=np.bincount(histogram_bins,weights=gradient,minlength=size).cumsum()[:-1]
                hs=np.bincount(histogram_bins,weights=hessian,minlength=size).cumsum()[:-1]
                ns=np.bincount(histogram_bins,minlength=size).cumsum()[:-1]
                rg=gradient.sum()-gs;rh=hessian.sum()-hs
                gain=gs**2/(hs+20)+rg**2/(rh+20)
                gain[(ns<120)|(len(y)-ns<120)]=-np.inf
                split=int(np.argmax(gain))
                if not np.isfinite(gain[split]):continue
                candidate=(float(gain[split]),k,split,float(gs[split]/(hs[split]+20)),float(rg[split]/(rh[split]+20)))
                if best is None or candidate[0]>best[0]:best=candidate
            if best is None:break
            _,k,split,left,right=best
            cutoff=float(cuts[k][split]);left*=.1;right*=.1
            stumps.append((k,cutoff,left,right))
            logits+=np.where(x[:,k]<=cutoff,left,right)
        def boosted(rs):
            values=np.array([r['features'] for r in rs]);scores=np.zeros(len(rs))
            for k,cutoff,left,right in stumps:scores+=np.where(values[:,k]<=cutoff,left,right)
            return 1/(1+np.exp(-np.clip(scores,-30,30)))
        methods.append(('boosted_stumps',boosted))
        metrics['boosting_fit']={'trees':len(stumps),'leaf_minimum':120,'learning_rate':.1}
    for name,fn in methods:
        vs=fn(val);ts=fn(test)
        thresholds=sorted(set([0.0,float(vs.max()+1e-9),*np.quantile(vs,np.linspace(0,1,41)).tolist()]))
        choices=[(score_alerts(val,vs,threshold,lead,horizon),threshold) for threshold in thresholds]
        selected,threshold=max(choices,key=lambda x:(x[0]['f1'],x[0]['precision'],-x[0]['alerts']))
        test_result=score_alerts(test,ts,threshold,lead,horizon)
        metrics['methods'][name]={'threshold':round(threshold,5),'validation':selected,'test':test_result}
        print('RESULT',horizon,name,json.dumps(test_result),flush=True)
        conservative=[(result,cutoff) for result,cutoff in choices
                      if result['precision']>=.99 and result['correct_alerts']>0]
        if conservative:
            cv,ct=max(conservative,key=lambda x:(x[0]['recall'],-x[0]['alerts']))
            cr=score_alerts(test,ts,ct,lead,horizon)
            metrics['methods'][name]['validation_99_policy']={
                'threshold':round(ct,5),'validation':cv,'test':cr,
                'limitation':'selected on few validation events; not a 99% guarantee'}
            print('CONSERVATIVE',horizon,name,json.dumps(cr),flush=True)
        else:
            metrics['methods'][name]['validation_99_policy']={'status':'no threshold with nonzero validated alerts and >=99% precision'}
            print('CONSERVATIVE',horizon,name,'unavailable',flush=True)
    metrics['selected_by_validation']=max(metrics['methods'],key=lambda name:(metrics['methods'][name]['validation']['f1'],metrics['methods'][name]['validation']['precision'],-metrics['methods'][name]['validation']['alerts']))
    report['results'][str(horizon)]=metrics
result_path=ROOT/('surge-model-probe-results-advanced.json' if args.advanced else 'surge-model-probe-results-extended.json' if args.older else 'surge-model-probe-results.json')
result_path.write_text(json.dumps(report,indent=2),encoding='utf-8')
print('SAVED',result_path,flush=True)
