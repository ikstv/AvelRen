"""Offline check of cross-checkpoint context using approved extracts only."""
import bisect,json,runpy,sys
from pathlib import Path
import numpy as np
from scipy.optimize import minimize

root=Path('C:/AI/AvelRen/dist')
sys.argv=['surge-model-probe.py','--older']
g=runpy.run_path(str(root/'surge-model-probe.py'))
rows=g['samples'](60,15)
groups=[[r for r in rows if r['origin']<g['VALIDATION']],
        [r for r in rows if g['VALIDATION']<=r['origin']<g['TEST']],
        [r for r in rows if r['origin']>=g['TEST']]]

def context(r):
    origin=r['origin'];values=[]
    for cp in g['CP']:
        t,c,p,bad,_,_=g['series'][cp]
        j=bisect.bisect_right(t,origin)-1
        if j<0 or origin-t[j]>90:return None
        deltas=[]
        for lag in (5,20):
            target=int(t[j])-lag*60
            k=bisect.bisect_left(t,target)
            candidates=[i for i in (k-1,k) if 0<=i<j]
            if not candidates:return None
            i=min(candidates,key=lambda i:abs(t[i]-target))
            if abs(t[i]-target)>30 or bad[i]!=bad[j]:return None
            deltas.append(c[j]-c[i])
        values.extend([c[j],*deltas,p[j]])
    return list(r['features'])+values

prepared=[]
for group in groups:
    good=[];features=[]
    for r in group:
        v=context(r)
        if v is not None:good.append(r);features.append(v)
    prepared.append((good,np.array(features)))
train,x=prepared[0];val,vx=prepared[1];test,tx=prepared[2]
y=np.array([r['y'] for r in train],dtype=float)
weights=np.where(y==1,len(y)/(2*y.sum()),len(y)/(2*(len(y)-y.sum())))
report={'source_hashes':g['source_hashes'],'limitation':'exploratory reused test; not final holdout or calibrated probability',
        'context':'latest available counts, 5/20min changes and pause at all 4 checkpoints; no future values or gap filling',
        'split_samples':[len(train),len(val),len(test)],'methods':{}}
for name,columns in [('optimized_own_only',15),('cross_checkpoint_context',31)]:
    xx=x[:,:columns];mu=xx.mean(axis=0);sd=xx.std(axis=0);sd[sd<1e-8]=1
    def matrix(a):return np.column_stack((np.ones(len(a)),(a[:,:columns]-mu)/sd))
    design=matrix(x)
    def loss(coef):
        logits=design@coef;prob=1/(1+np.exp(-np.clip(logits,-30,30)))
        value=float(np.mean(weights*(np.logaddexp(0,logits)-y*logits))+.03/2*np.sum(coef[1:]**2))
        grad=design.T@((prob-y)*weights)/len(y);grad[1:]+=.03*coef[1:]
        return value,grad
    fit=minimize(loss,np.zeros(columns+1),jac=True,method='L-BFGS-B',options={'maxiter':200,'ftol':1e-9})
    def scores(a):return 1/(1+np.exp(-np.clip(matrix(a)@fit.x,-30,30)))
    vs=scores(vx);ts=scores(tx)
    thresholds=sorted(set([0.0,float(vs.max()+1e-9),*np.quantile(vs,np.linspace(0,1,41)).tolist()]))
    choices=[(g['score_alerts'](val,vs,cut,15,60),cut) for cut in thresholds]
    selected,cut=max(choices,key=lambda c:(c[0]['f1'],c[0]['precision'],-c[0]['alerts']))
    result=g['score_alerts'](test,ts,cut,15,60)
    report['methods'][name]={'converged':bool(fit.success),'threshold':float(cut),'validation':selected,'test':result}
    print('CONTEXT',name,json.dumps(result),flush=True)
report['selected_by_validation']=max(report['methods'],key=lambda n:(report['methods'][n]['validation']['f1'],report['methods'][n]['validation']['precision'],-report['methods'][n]['validation']['alerts']))
(root/'surge-context-probe-results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print('CONTEXT_SELECTION',report['selected_by_validation'],flush=True)
