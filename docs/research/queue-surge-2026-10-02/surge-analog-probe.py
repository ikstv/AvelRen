"""Local research only: historical analogs, train-only reference library.

No calibrated probability; overlapping reference rows are not independent
events. Reused exploratory test cannot establish final 99% acceptance.
"""
import json, runpy, sys
from pathlib import Path
import numpy as np
from scipy.spatial import cKDTree

root=Path('C:/AI/AvelRen/dist')
sys.argv=['surge-model-probe.py','--older']
g=runpy.run_path(str(root/'surge-model-probe.py'))
rows=g['samples'](60,15)
train=[r for r in rows if r['origin']<g['VALIDATION']]
val=[r for r in rows if g['VALIDATION']<=r['origin']<g['TEST']]
test=[r for r in rows if r['origin']>=g['TEST']]
report={'source_hashes':g['source_hashes'],
        'target':'precision >=0.99 AND event recall >=0.99',
        'horizon':'15-60 minutes, not full rolling 24h forecast',
        'limitation':'reused exploratory test; correlated minute reference rows; scores uncalibrated',
        'methods':{}}
for neighbors in (20,100,500):
    scores=[np.zeros(len(val)),np.zeros(len(test))]
    for cp in g['CP']:
        reference=[r for r in train if r['cp']==cp]
        x=np.array([r['features'][:11] for r in reference])
        labels=np.array([r['y'] for r in reference])
        mu=x.mean(axis=0);sd=x.std(axis=0);sd[sd<1e-8]=1
        tree=cKDTree((x-mu)/sd)
        for target,output in zip((val,test),scores):
            ids=[i for i,r in enumerate(target) if r['cp']==cp]
            q=np.array([target[i]['features'][:11] for i in ids])
            distances,indices=tree.query((q-mu)/sd,k=min(neighbors,len(reference)),workers=1)
            weights=1/(.1+distances)
            output[ids]=(weights*labels[indices]).sum(axis=1)/weights.sum(axis=1)
    vs,ts=scores
    # Fixed threshold grid: 101 quantiles chosen on validation only.
    cuts=sorted(set([0.,float(vs.max()+1e-9),*np.quantile(vs,np.linspace(0,1,101)).tolist()]))
    choices=[(g['score_alerts'](val,vs,c,15,60),c) for c in cuts]
    chosen,cut=max(choices,key=lambda z:(z[0]['f1'],z[0]['precision'],-z[0]['alerts']))
    result=g['score_alerts'](test,ts,cut,15,60)
    both=[(m,c) for m,c in choices if m['precision']>=.99 and m['recall']>=.99]
    name=f'own_analogs_{neighbors}'
    report['methods'][name]={'threshold':cut,'validation':chosen,'test':result,
                            'joint_99_validation_threshold_available':bool(both)}
    print('ANALOG',name,json.dumps(result),flush=True)
report['selected_by_validation']=max(report['methods'],key=lambda n:(report['methods'][n]['validation']['f1'],report['methods'][n]['validation']['precision'],-report['methods'][n]['validation']['alerts']))
(root/'surge-analog-probe-results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print('SELECTED',report['selected_by_validation'],flush=True)
