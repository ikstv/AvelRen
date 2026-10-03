"""Descriptive precursor audit on approved local data; not an alert rule."""
import bisect,gzip,json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import median

root=Path('C:/AI/AvelRen/dist')
data=defaultdict(list)
for filename in ('queue-surge-older-20260806-0903.json.gz','queue-surge-28days.json.gz'):
    for cp,t,c,p in json.loads(gzip.decompress((root/filename).read_bytes())):
        data[cp].append((t,c,p))
events=json.loads((root/'surge-model-probe-results-advanced.json').read_text())['events']
details=[];controls={}
for cp,labels in events.items():
    rows=sorted(data[int(cp)]);times=[r[0] for r in rows]
    def point(target):
        i=bisect.bisect_left(times,target)
        choices=[j for j in (i-1,i) if 0<=j<len(times)]
        if not choices:return None
        j=min(choices,key=lambda j:abs(times[j]-target))
        return j if abs(times[j]-target)<=30 else None
    event_times=sorted(int(datetime.fromisoformat(label).timestamp()) for label in labels)
    if event_times:
        background=[]
        for end,row in enumerate(rows):
            t=row[0]
            if (t//60)%5:continue
            k=bisect.bisect_left(event_times,t)
            if any(abs(event_times[j]-t)<=75*60 for j in (k-1,k) if 0<=j<len(event_times)):continue
            begin=point(t-300)
            if begin is None or any(times[j]-times[j-1]>90 for j in range(begin+1,end+1)):continue
            background.append({'change_last5':row[1]-rows[begin][1],
                'pause_changed_last5':any(rows[j][2]!=rows[j-1][2] for j in range(begin+1,end+1))})
        controls[cp]={'windows':len(background),'median_last5_growth':median(v['change_last5'] for v in background),
            'growing_5plus':sum(v['change_last5']>=5 for v in background),
            'pause_changed_last5':sum(v['pause_changed_last5'] for v in background)}
    for label in labels:
        start=int(datetime.fromisoformat(label).timestamp());i=point(start)
        if i is None:continue
        result={'checkpoint_id':int(cp),'event_start':label,'before':{}}
        for lead in (15,30,60):
            end=point(start-lead*60);begin=point(start-(lead+5)*60)
            if end is None or begin is None or any(times[k]-times[k-1]>90 for k in range(begin+1,end+1)):
                result['before'][str(lead)]=None;continue
            result['before'][str(lead)]={'change_last5':rows[end][1]-rows[begin][1],
                'paused':rows[end][2],
                'pause_changed_last5':any(rows[k][2]!=rows[k-1][2] for k in range(begin+1,end+1))}
        end=point(start+300)
        if end is not None:
            result['first5_growth']=rows[end][1]-rows[i][1]
            result['largest_minute_growth_first5']=max(rows[k][1]-rows[k-1][1] for k in range(i+1,end+1))
        details.append(result)
summary={}
for lead in (15,30,60):
    values=[d['before'][str(lead)] for d in details if d['before'][str(lead)] is not None]
    summary[str(lead)]={'available_events':len(values),
        'median_last5_growth':median(v['change_last5'] for v in values),
        'already_growing_5plus':sum(v['change_last5']>=5 for v in values),
        'pause_change_last5':sum(v['pause_changed_last5'] for v in values)}
report={'limitation':'descriptive event-only profile; not specificity, causal evidence or a validated forecast',
        'summary':summary,'quiet_controls':controls,'control_rule':'5min-spaced origins, no labeled event within +/-75min; overlapping dependent windows; not time-of-day matched',
        'events':details}
(root/'surge-precursors-results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(summary))
print('quiet_controls',json.dumps(controls))
print('chop_case',json.dumps([d for d in details if d['checkpoint_id']==17 and d['event_start'].startswith('2026-10-01T17')]))
