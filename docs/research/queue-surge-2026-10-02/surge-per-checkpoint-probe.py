"""Research classifier per checkpoint; current approved inputs only."""
import json,runpy,sys
from pathlib import Path
import numpy as np
from scipy.optimize import minimize

root=Path('C:/AI/AvelRen/dist');sys.argv=['surge-model-probe.py','--older']
g=runpy.run_path(str(root/'surge-model-probe.py'));rows=g['samples'](60,15)
train=[r for r in rows if r['origin']<g['VALIDATION']]
val=[r for r in rows if g['VALIDATION']<=r['origin']<g['TEST']]
test=[r for r in rows if r['origin']>=g['TEST']]
models={};vs=np.full(len(val),-1.);ts=np.full(len(test),-1.)
for cp in g['CP']:
    tr=[r for r in train if r['cp']==cp];x=np.array([r['features'][:11] for r in tr]);y=np.array([r['y'] for r in tr],dtype=float)
    if not y.sum() or y.sum()==len(y):
        models[str(cp)]={'status':'insufficient training classes','positive_samples':int(y.sum())};continue
    mu=x.mean(axis=0);sd=x.std(axis=0);sd[sd<1e-8]=1
    x=np.column_stack((np.ones(len(x)),(x-mu)/sd))
    weights=np.where(y==1,len(y)/(2*y.sum()),len(y)/(2*(len(y)-y.sum())))
    def loss(coef):
        z=x@coef;p=1/(1+np.exp(-np.clip(z,-30,30)))
        value=float(np.mean(weights*(np.logaddexp(0,z)-y*z))+.03/2*np.sum(coef[1:]**2))
        grad=x.T@((p-y)*weights)/len(y);grad[1:]+=.03*coef[1:]
        return value,grad
    fit=minimize(loss,np.zeros(x.shape[1]),jac=True,method='L-BFGS-B',options={'maxiter':200,'ftol':1e-9})
    models[str(cp)]={'status':'fitted','converged':bool(fit.success),'positive_samples':int(y.sum())}
    for rs,output in ((val,vs),(test,ts)):
        ix=[i for i,r in enumerate(rs) if r['cp']==cp]
        xx=np.array([rs[i]['features'][:11] for i in ix]);xx=np.column_stack((np.ones(len(xx)),(xx-mu)/sd))
        output[ix]=1/(1+np.exp(-np.clip(xx@fit.x,-30,30)))
thresholds=sorted(set([0.,float(vs.max()+1e-9),*np.quantile(vs[vs>=0],np.linspace(0,1,41)).tolist()]))
choices=[(g['score_alerts'](val,vs,cut,15,60),cut) for cut in thresholds]
selected,cut=max(choices,key=lambda c:(c[0]['f1'],c[0]['precision'],-c[0]['alerts']))
result=g['score_alerts'](test,ts,cut,15,60)
report={'limitation':'exploratory reused test; missing model is unavailable, not evidence of no risk',
        'models':models,'threshold':float(cut),'validation':selected,'test':result}
(root/'surge-per-checkpoint-probe-results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print('PER_CHECKPOINT',json.dumps(report),flush=True)
