"""Offline research: long past history, short and rolling 24h event labels.

Purged chronological splits; train-only scaling. Test already reused.
24h score means at least one event in 1-24h, not predicted event time.
"""
import bisect,hashlib,json,runpy,sys
from pathlib import Path
import numpy as np
from scipy.optimize import minimize

root=Path('C:/AI/AvelRen/dist')
freeze_enabled='--freeze' in sys.argv
sys.argv=['surge-model-probe.py','--older']
g=runpy.run_path(str(root/'surge-model-probe.py'))
base=g['samples'](60,15)
report={'source_hashes':g['source_hashes'],'target':'precision >=99% AND recall >=99%',
        'limitations':['reused exploratory test','net growth, not gross registrations',
                       '24h classification does not provide event time or magnitude'],
        'experiments':{}}

def long_features(r):
    t,c,p,bad,severe,events=g['series'][r['cp']]
    j=bisect.bisect_left(t,r['origin']);out=[]
    for minutes in (120,240):
        goal=r['origin']-minutes*60;k=bisect.bisect_left(t,goal)
        options=[v for v in (k-1,k) if 0<=v<=j]
        if not options:return None
        i=min(options,key=lambda v:abs(t[v]-goal))
        if abs(t[i]-goal)>30 or severe[i]!=severe[j] or (j-i+1)/(minutes+1)<.95:return None
        values=c[i:j+1];changes=np.diff(values)
        out.extend([values[-1]-values[0],values.std(),values.max()-values.min(),
                    np.maximum(changes,0).sum(),np.maximum(-changes,0).sum(),
                    (changes>0).mean(),np.mean(p[i:j+1]),np.sum(np.diff(p[i:j+1])!=0)])
    return list(r['features'])+out

for horizon,lead in ((60,15),(1440,60)):
    origins=[]
    for original in base:
        r=dict(original)
        if horizon==1440:
            local=g['datetime'].fromtimestamp(r['origin'],g['timezone'].utc).astimezone(g['zone'])
            if local.minute!=0:continue
            t,c,p,bad,severe,events=g['series'][r['cp']]
            j=bisect.bisect_left(t,r['origin']);end=r['origin']+horizon*60+300
            boundary=g['VALIDATION'] if r['origin']<g['VALIDATION'] else g['TEST'] if r['origin']<g['TEST'] else g['END']
            if end>=boundary:continue
            k=bisect.bisect_left(t,end)
            if k>=len(t) or abs(t[k]-end)>30 or severe[k]!=severe[j] or (k-j+1)/((end-r['origin'])/60+1)<.95:continue
            r['events']=events[(events>=r['origin']+lead*60)&(events<=r['origin']+horizon*60)].tolist()
            r['y']=int(bool(r['events']))
        origins.append(r)
    enriched=[(r,long_features(r)) for r in origins]
    common=[r|{'long_features':f} for r,f in enriched if f is not None]
    splits=[[r for r in common if r['origin']<g['VALIDATION']],
            [r for r in common if g['VALIDATION']<=r['origin']<g['TEST']],
            [r for r in common if r['origin']>=g['TEST']]]
    train,val,test=splits
    raw_test_events={(cp,int(e)) for cp,series in g['series'].items() for e in series[-1] if g['TEST']<=e<g['END']}
    eligible_test_events={(r['cp'],e) for r in test for e in r['events']}
    experiment={'origin_rows_before_long_history':len(origins),'common_rows':len(common),
                'split_rows':[len(s) for s in splits],
                'positive_rows':[sum(r['y'] for r in s) for s in splits],
                'test_events_before_long_history':len({(r['cp'],e) for r in origins if r['origin']>=g['TEST'] for e in r['events']}),
                'test_events_after_long_history':len({(r['cp'],e) for r in test for e in r['events']}),
                'all_labeled_events_in_test':len(raw_test_events),
                'events_excluded_from_test_recall':[{'checkpoint_id':cp,'event_start':g['datetime'].fromtimestamp(e,g['timezone'].utc).astimezone(g['zone']).isoformat()} for cp,e in sorted(raw_test_events-eligible_test_events)],
                'methods':{}}
    assert all(not r['events'] or min(r['events'])>=r['origin']+lead*60 for r in common)
    if not all(splits) or not 0<sum(r['y'] for r in train)<len(train):
        experiment['status']='insufficient_labels';report['experiments'][str(horizon)]=experiment;continue
    y=np.array([r['y'] for r in train],dtype=float)
    weights=np.where(y==1,len(y)/(2*y.sum()),len(y)/(2*(len(y)-y.sum())))
    for name,key in (('baseline_common_origins','features'),('past_2_4_hours','long_features')):
        arrays=[np.array([r[key] for r in s]) for s in splits]
        mu=arrays[0].mean(axis=0);sd=arrays[0].std(axis=0);sd[sd<1e-8]=1
        design=[np.column_stack((np.ones(len(a)),(a-mu)/sd)) for a in arrays]
        x=design[0]
        def objective(coef):
            z=x@coef;p=1/(1+np.exp(-np.clip(z,-30,30)))
            loss=np.mean(weights*(np.logaddexp(0,z)-y*z))+.03/2*np.sum(coef[1:]**2)
            grad=x.T@((p-y)*weights)/len(y);grad[1:]+=.03*coef[1:]
            return float(loss),grad
        fit=minimize(objective,np.zeros(x.shape[1]),jac=True,method='L-BFGS-B',options={'maxiter':250,'ftol':1e-9})
        assert fit.success,fit.message
        vs,ts=[1/(1+np.exp(-np.clip(a@fit.x,-30,30))) for a in design[1:]]
        cuts=sorted(set([0.,float(vs.max()+1e-9),*np.quantile(vs,np.linspace(0,1,101)).tolist()]))
        choices=[(g['score_alerts'](val,vs,c,lead,horizon),c) for c in cuts]
        selected,cut=max(choices,key=lambda z:(z[0]['f1'],z[0]['precision'],-z[0]['alerts']))
        result=g['score_alerts'](test,ts,cut,lead,horizon)
        experiment['methods'][name]={'threshold':cut,'converged':bool(fit.success),'validation':selected,'test':result,
                                    'joint_99_validation':any(m['precision']>=.99 and m['recall']>=.99 for m,c in choices)}
        if freeze_enabled and horizon==1440 and name=='baseline_common_origins':
            frozen={'kind':'research_only_frozen_baseline_24h','source_hashes':g['source_hashes'],
                    'probe_source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    'trained_before':'2026-09-18T00:00:00+03:00',
                    'threshold_selected_before':'2026-09-25T00:00:00+03:00',
                    'holdout_origins_start':'2026-10-02T00:00:00+03:00',
                    'holdout_origins_end_exclusive':'2026-10-09T00:00:00+03:00',
                    'required_future_data_until':'2026-10-10T00:05:00+03:00',
                    'feature_mean':mu.tolist(),'feature_std':sd.tolist(),
                    'coefficients':fit.x.tolist(),'threshold':float(cut),
                    'feature_order':'count,d5,d10,d20,d60,d5-d10/2,paused,sin_day,cos_day,sin_week,cos_week,cp1,cp6,cp17,cp29',
                    'origin_frequency_minutes':60,'lead_minutes':60,'horizon_minutes':1440,
                    'past_quality':'baseline last60min no gap>90s; additionally last120/240min coverage>=95%, no gap>300s, endpoint tolerance30s',
                    'future_quality':'24h+5min coverage>=95%, no gap>300s, endpoint tolerance30s',
                    'event_definition':'net +20 within5min, no internal gap>90s, endpoint tolerance30s; windows within30min clustered',
                    'matching':'new alert cooldown60min per checkpoint; chronological one alert to one unmatched event',
                    'acceptance':'precision>=0.99 AND recall>=0.99; excluded events reported separately; sufficient independent evidence required',
                    'scope_limitation':'predicts any event in1-24h, not precise event time or magnitude; not deployed'}
            freeze_path=root/'surge-frozen-24h-20261002.json'
            if freeze_path.exists():raise RuntimeError('Frozen artifact already exists: do not overwrite')
            freeze_path.write_text(json.dumps(frozen,indent=2),encoding='utf-8')
            print('FROZEN_SHA256',hashlib.sha256(freeze_path.read_bytes()).hexdigest(),flush=True)
        print('LONG',horizon,name,json.dumps(result),flush=True)
    experiment['selected_by_validation']=max(experiment['methods'],key=lambda n:(experiment['methods'][n]['validation']['f1'],experiment['methods'][n]['validation']['precision'],-experiment['methods'][n]['validation']['alerts']))
    report['experiments'][str(horizon)]=experiment
(root/'surge-long-history-probe-results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print('LONG_SAVED',flush=True)
