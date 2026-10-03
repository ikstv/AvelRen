"""Exploratory chronological evaluation; local approved operational extract only.

No production code, no network calls, no forecasting accuracy claim.
Daily maxima are measured net queue growth, not registration events.
"""
import bisect, gzip, hashlib, json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from zoneinfo import ZoneInfo

ROOT=Path('C:/AI/AvelRen/dist')
source=ROOT/'queue-surge-28days.json.gz'
rows=json.loads(gzip.decompress(source.read_bytes()))
zone=ZoneInfo('Europe/Kyiv')
groups=defaultdict(list)
for cp,t,count,paused in rows:
    at=datetime.fromtimestamp(t,timezone.utc).astimezone(zone)
    groups[(cp,at.date().isoformat())].append((t,count,paused,at))
report={'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
        'records':len(rows),'training_rule':'only complete dates preceding forecast date; issue at 00:00 Kyiv',
        'evaluation_dates':'2026-09-18 through 2026-10-01',
        'exploratory_not_untouched_holdout':True,
        'quality_rule':'at least 95% of nominal minute observations and 90% valid intraday windows',
        'day_peaks':[],'metrics':{},'chop_oct1_predictions':{}}
for (cp,day),samples in sorted(groups.items()):
    samples.sort()
    times=[s[0] for s in samples]
    broken=[0]
    for i in range(1,len(times)):
        broken.append(broken[-1]+int(times[i]-times[i-1]>90))
    for window in (5,10,20,60):
        candidates=[]
        for j,s in enumerate(samples):
            target=s[0]-window*60
            k=bisect.bisect_left(times,target)
            choices=[i for i in (k-1,k) if 0<=i<j]
            if not choices: continue
            i=min(choices,key=lambda i:abs(times[i]-target))
            if abs(times[i]-target)>30 or broken[j]!=broken[i]: continue
            candidates.append((s[1]-samples[i][1],i,j))
        if not candidates: continue
        delta,i,j=max(candidates,key=lambda x:(x[0],-x[1]))
        start=samples[i][3]
        report['day_peaks'].append({'checkpoint_id':cp,'date':day,'window':window,
            'samples':len(samples),'valid_windows':len(candidates),
            'eligible':len(samples)>=1440*.95 and len(candidates)>=(1440-window)*.90,
            'increase':delta,'start':start.isoformat(),'end':samples[j][3].isoformat(),
            'minute':start.hour*60+start.minute,'weekday':start.weekday(),
            'paused_at_start':samples[i][2],
            'pause_transition':any(samples[k][2]!=samples[k-1][2] for k in range(i+1,j+1))})

def typical_minute(events):
    # Circular medoid prevents e.g. 23:55 and 00:05 averaging to noon.
    values=[e['minute'] for e in events]
    return min(sorted(set(values)),key=lambda x:sum(min(abs(x-y),1440-abs(x-y)) for y in values))

for cp in (17,1,6,29):
    report['metrics'][str(cp)]={}
    for window in (5,10,20,60):
        all_events=[e for e in report['day_peaks'] if e['checkpoint_id']==cp and e['window']==window]
        scores=defaultdict(list)
        for event in all_events:
            if event['date']<'2026-09-18' or not event['eligible']: continue
            prior=[e for e in all_events if e['date']<event['date'] and e['eligible']]
            if len(prior)<7: continue
            methods={'previous_eligible_day':prior[-1:], 'typical_last14_days':prior[-14:]}
            weekdays=[e for e in prior if e['weekday']==event['weekday']]
            if len(weekdays)>=2: methods['same_weekday']=weekdays
            for name,train in methods.items():
                predicted_minute=typical_minute(train)
                predicted_delta=median(e['increase'] for e in train)
                error=abs(predicted_minute-event['minute'])
                scores[name].append({'date':event['date'],'time_error_minutes':error,
                    'growth_error':abs(predicted_delta-event['increase'])})
                if cp==17 and event['date']=='2026-10-01':
                    report['chop_oct1_predictions'].setdefault(str(window),{})[name]={
                        'issued_at':'2026-10-01T00:00:00+03:00',
                        'predicted_start':f'{predicted_minute//60:02d}:{predicted_minute%60:02d}',
                        'predicted_growth':predicted_delta,'time_error_minutes':error,
                        'actual_growth':event['increase'],'actual_start':event['start']}
        report['metrics'][str(cp)][str(window)]={name:{
            'cases':len(values),
            'time_mae_minutes':round(mean(v['time_error_minutes'] for v in values),1),
            'growth_mae':round(mean(v['growth_error'] for v in values),1),
            'within_15_minutes':sum(v['time_error_minutes']<=15 for v in values),
            'within_60_minutes':sum(v['time_error_minutes']<=60 for v in values)}
            for name,values in scores.items()}
out=ROOT/'queue-surge-comparison.json'
out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in report.items() if k!='day_peaks'},ensure_ascii=True,indent=2))
print('CHOP DAILY 5M PEAKS')
for e in report['day_peaks']:
    if e['checkpoint_id']==17 and e['window']==5:
        print(e['date'],e['start'][11:16],e['increase'],e['eligible'])
