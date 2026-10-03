"""Offline own-checkpoint-only feature probe, no external registration schedule."""
import bisect,gzip,hashlib,json,runpy,sys
from datetime import datetime,timezone
from pathlib import Path
import numpy as np
from scipy.optimize import minimize

wait_enabled='--wait' in sys.argv
root=Path('C:/AI/AvelRen/dist')
sys.argv=['surge-model-probe.py','--older']
g=runpy.run_path(str(root/'surge-model-probe.py'))
rows=g['samples'](60,15)
wait_values={}
if wait_enabled:
    wait_path=root/'queue-surge-wait-20260806-1001.json.gz'
    wait_rows=json.loads(gzip.decompress(wait_path.read_bytes()))
    wait_values={(cp,t):value for cp,t,value in wait_rows}
    assert len(wait_values)==len(wait_rows)==316136
    assert set(wait_values)=={(cp,int(t)) for cp,series in g['series'].items() for t in series[0]}
splits=[[r for r in rows if r['origin']<g['VALIDATION']],
        [r for r in rows if g['VALIDATION']<=r['origin']<g['TEST']],
        [r for r in rows if r['origin']>=g['TEST']]]
state_starts={}
for cp,(times,counts,paused,*_) in g['series'].items():
    starts=np.zeros(len(times),dtype=np.int64)
    for j in range(1,len(times)):
        starts[j]=j if paused[j]!=paused[j-1] or times[j]-times[j-1]>90 else starts[j-1]
    state_starts[cp]=starts

def features(r,enriched):
    f=list(r['features'])
    if not enriched:return f
    if enriched=='wait':
        cp,origin=r['cp'],r['origin'];times=g['series'][cp][0]
        current=wait_values[(cp,origin)]
        known=current>0
        additions=[current/3600 if known else np.nan,float(known)]
        for minutes in (5,20,60):
            target=origin-minutes*60;k=bisect.bisect_left(times,target)
            candidates=[i for i in (k-1,k) if 0<=i<len(times) and times[i]<=origin]
            i=min(candidates,key=lambda i:abs(times[i]-target))
            earlier=wait_values[(cp,int(times[i]))]
            valid=known and earlier>0 and abs(times[i]-target)<=30
            additions.extend([(current-earlier)/3600 if valid else np.nan,float(valid)])
        additions.extend([current/max(1,f[0])/3600 if known and f[0]>0 else np.nan,
                          float(known and f[0]>0)])
        return f+additions
    local=datetime.fromtimestamp(r['origin'],timezone.utc).astimezone(g['zone'])
    day=[int(local.weekday()==k) for k in range(7)]
    timebins=[int(local.hour//6==k) for k in range(4)]
    times,counts,paused,*_=g['series'][r['cp']]
    j=bisect.bisect_right(times,r['origin'])-1
    age=min(180,(r['origin']-int(times[state_starts[r['cp']][j]]))/60)
    cp_flags=f[11:15]
    return f+day+timebins+[age,age*f[6],age*(1-f[6]),f[1]/max(1,f[0]),f[2]/max(1,f[0])]+[d*c for c in cp_flags for d in day]

report={'source_hashes':g['source_hashes'],'scope':'own checkpoint only; registration continuously available according to owner',
        'limitation':'exploratory reused test; no calibrated probability or 99% claim','methods':{}}
train,val,test=splits;y=np.array([r['y'] for r in train],dtype=float)
weights=np.where(y==1,len(y)/(2*y.sum()),len(y)/(2*(len(y)-y.sum())))
methods=[('optimized_own_only',False),('own_wait_estimate','wait') if wait_enabled else ('own_weekday_state',True)]
if wait_enabled:
    report['wait_source_sha256']=hashlib.sha256(wait_path.read_bytes()).hexdigest()
    report['missing_wait_rule']='historical zero is unknown; missing numerical features imputed by training medians, explicit validity flags retained'
for name,enriched in methods:
    arrays=[np.array([features(r,enriched) for r in rs],dtype=float) for rs in splits]
    if enriched=='wait':
        imputation=np.nanmedian(arrays[0],axis=0)
        imputation=np.where(np.isfinite(imputation),imputation,0)
        arrays=[np.where(np.isfinite(a),a,imputation) for a in arrays]
    mu=arrays[0].mean(axis=0);sd=arrays[0].std(axis=0);sd[sd<1e-8]=1
    design=[np.column_stack((np.ones(len(a)),(a-mu)/sd)) for a in arrays]
    x=design[0]
    def objective(coef):
        z=x@coef;p=1/(1+np.exp(-np.clip(z,-30,30)))
        loss=float(np.mean(weights*(np.logaddexp(0,z)-y*z))+.03/2*np.sum(coef[1:]**2))
        grad=x.T@((p-y)*weights)/len(y);grad[1:]+=.03*coef[1:]
        return loss,grad
    fit=minimize(objective,np.zeros(x.shape[1]),jac=True,method='L-BFGS-B',options={'maxiter':250,'ftol':1e-9})
    vs,ts=[1/(1+np.exp(-np.clip(a@fit.x,-30,30))) for a in design[1:]]
    cuts=sorted(set([0.0,float(vs.max()+1e-9),*np.quantile(vs,np.linspace(0,1,41)).tolist()]))
    choices=[(g['score_alerts'](val,vs,cut,15,60),cut) for cut in cuts]
    selected,cut=max(choices,key=lambda c:(c[0]['f1'],c[0]['precision'],-c[0]['alerts']))
    result=g['score_alerts'](test,ts,cut,15,60)
    report['methods'][name]={'converged':bool(fit.success),'features':x.shape[1]-1,'threshold':float(cut),'validation':selected,'test':result}
    print('OWN',name,json.dumps(result),flush=True)
report['selected_by_validation']=max(report['methods'],key=lambda n:(report['methods'][n]['validation']['f1'],report['methods'][n]['validation']['precision'],-report['methods'][n]['validation']['alerts']))
result_path=root/('surge-wait-probe-results.json' if wait_enabled else 'surge-own-probe-results.json')
result_path.write_text(json.dumps(report,indent=2),encoding='utf-8')
print('OWN_SELECTION',report['selected_by_validation'],flush=True)
