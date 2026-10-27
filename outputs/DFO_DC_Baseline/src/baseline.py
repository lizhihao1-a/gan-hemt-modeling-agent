"""Prepare -> fit train only -> freeze -> one held-out evaluation -> artifacts."""
import argparse,csv,hashlib,json,sys,time,datetime,platform
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
WS=ROOT.parent.parent
sys.path.insert(0,str(WS/'work/dfo_deps'))
sys.path.insert(0,str(ROOT/'.deps'))
import numpy as np
from scipy.optimize import least_squares
from config import FIXED,BOUNDS,ACTIVE,SEED,N_STARTS,MAX_NFEV,ID_FLOOR,GM_FLOOR
from spice import Simulator

def write_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False),encoding='utf-8')
def read_json(path): return json.loads(path.read_text(encoding='utf-8'))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def stamp():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def safe_gm_mask(grid_indices):
    """Every measured gm stencil must use Id targets inside the same subset."""
    known=set(map(int,grid_indices));safe=[]
    for i in grid_indices:
        g=int(i)//201
        stencil=(int(i),int(i)+201) if g==0 else ((int(i)-201,int(i)) if g==29 else (int(i)-201,int(i)+201))
        safe.append(all(j in known for j in stencil))
    return np.array(safe,dtype=bool)
def encode_params(x):
    p=FIXED.copy()
    for k,(lo,hi,lg) in BOUNDS.items():
        u=float(x[ACTIVE.index(k)]) if k in ACTIVE else .5
        p[k]=float(10**(np.log10(lo)+u*np.log10(hi/lo)) if lg else lo+u*(hi-lo))
    return p
def load(path):
    rows=list(csv.DictReader(path.open(encoding='utf-8')))
    index=np.array([int(r['grid_index']) for r in rows])
    y=np.array([[float(r['id_A']),float(r['gm_S'])] for r in rows])
    return rows,index,y
def prepare():
    src=WS/'outputs/GaN_HEMT_Prepared/data/by_device/DFO_4x50.csv'
    rows=list(csv.DictReader(src.open(encoding='utf-8-sig')))
    out=ROOT/'data';out.mkdir(exist_ok=True)
    groups={'train':[],'test':[]}; seen=set()
    for r in rows:
        gi=round((float(r['vgs_V'])+3)*10)*201+round(float(r['vds_V'])*10)
        assert gi not in seen;seen.add(gi)
        groups[r['train_test_split']].append({k:r[k] for k in ['point_id','vds_V','vgs_V','id_A','gm_S','source_row']}|{'grid_index':gi})
    assert len(seen)==6030 and len(groups['train'])==4824 and len(groups['test'])==1206
    for split,rs in groups.items():
        with (out/f'{split}.csv').open('w',newline='',encoding='utf-8') as f:
            w=csv.DictWriter(f,fieldnames=list(rs[0]));w.writeheader();w.writerows(rs)
    manifest={'created_utc':stamp(),'source':str(src),'source_sha256':sha(src),
              'train_sha256':sha(out/'train.csv'),'test_sha256':sha(out/'test.csv'),
              'counts':{k:len(v) for k,v in groups.items()},'grid':[30,201],
              'split':'Original author train/test labels; never repartition test.'}
    write_json(out/'manifest.json',manifest);print(json.dumps(manifest),flush=True)

def fit():
    _,ix,y=load(ROOT/'data/train.csv')
    train_hash=sha(ROOT/'data/train.csv')
    rng=np.random.default_rng(SEED); perm=rng.permutation(len(ix));nv=round(.2*len(ix))
    val=perm[:nv]; fitix=perm[nv:]
    safe_fit=safe_gm_mask(ix[fitix])
    scales=np.array([max(float(np.ptp(y[fitix,0])),ID_FLOOR),
        max(float(np.ptp(y[fitix[safe_fit],1])),GM_FLOOR)])
    out=ROOT/'results';out.mkdir(exist_ok=True)
    protocol={'created_utc':stamp(),'protocol_version':2,'seed':SEED,'starts':N_STARTS,'max_nfev_each':MAX_NFEV,
       'active_parameters':ACTIVE,'published_bounds':BOUNDS,'fixed':FIXED,
       'inactive':'Remaining 12 search parameters fixed at arithmetic/geometric midpoint; no Ig or independent temperature data.',
       'internal_fit_count':len(fitix),'internal_validation_count':len(val),
       'fit_point_ids':ix[fitix].tolist(),'validation_point_ids':ix[val].tolist(),
       'train_sha256':train_hash,'test_targets_used':False,
       'loss':'Id/gm asinh residual at 1e-4 A / 1e-3 S plus 2*linear residual/train-fit range. soft_l1 f_scale=0.3. gm residual zeroed unless every difference-stencil Id is inside the same fit/validation subset.',
       'selection':'Lowest internal validation robust cost among the final three starts; refit using all 4824 training points.',
       'gm':'numpy.gradient Id along Vgs, 0.1 V; one-sided at endpoints. Source gm exactly equals full-grid Id gradient; cross-subset stencil targets are excluded.',
       'safe_gm_internal_fit':int(safe_gm_mask(ix[fitix]).sum()),
       'safe_gm_internal_validation':int(safe_gm_mask(ix[val]).sum()),
       'safe_gm_full_train':int(safe_gm_mask(ix).sum()),
       'linear_normalization_scales':scales.tolist(),
       'audit_history':'Protocol 1 was evaluated, then a structural full-grid gm leakage audit identified cross-split derivative stencils. Protocol 2 keeps all bounds, seed, starts, loss scales and optimizer budget unchanged, masks unsafe gm, and is rerun. Test metrics were already seen in protocol 1; no pristine untouched-test claim.',
       'stopping':'scipy least_squares trf max_nfev=100, ftol=xtol=gtol=1e-6; diff_step=1e-3 in normalized coordinates.'}
    write_json(out/'fit_protocol.json',protocol)
    sim=Simulator(ROOT,encode_params(np.full(len(ACTIVE),.5)))
    (out/'initial_netlist.cir').write_text(sim.netlist,encoding='utf-8')
    (out/'simulator_startup.log').write_text('\n'.join(sim.messages),encoding='utf-8')
    calls=0;failed=0;start=time.perf_counter();history=[]
    def predict(x):
        nonlocal calls,failed
        calls+=1
        try:
            a,b,t=sim.simulate(encode_params(x));return np.column_stack([a.ravel(),b.ravel()]),t
        except Exception as e:
            failed+=1
            with (out/'simulation_failures.log').open('a',encoding='utf-8') as f:f.write(f'{calls}: {e}\n')
            return None,None
    def residual(pred,indices):
        data=y[indices]; p=pred[ix[indices]]; floors=np.array([ID_FLOOR,GM_FLOOR])
        transformed=np.arcsinh(p/floors)-np.arcsinh(data/floors);linear=2*(p-data)/scales
        safe=safe_gm_mask(ix[indices]);transformed[~safe,1]=0;linear[~safe,1]=0
        return np.concatenate([transformed.ravel(),linear.ravel()])
    def cost(r):return float(np.mean(2*.3**2*(np.sqrt(1+(r/.3)**2)-1)))
    def objective(x,indices,stage):
        p,_=predict(x)
        if p is None:return np.full(len(indices)*4,100.)
        r=residual(p,indices)
        if calls%25==0:
            rec={'call':calls,'stage':stage,'seconds':round(time.perf_counter()-start,3),'cost':cost(r)}
            history.append(rec)
            with (out/'optimization_trace.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(rec)+'\n')
            if calls%250==0:print(json.dumps(rec),flush=True)
        return r
    x0=np.full(len(ACTIVE),.5)
    initial,t0=predict(x0);np.savez_compressed(out/'initial_predictions.npz',prediction=initial,delta_temperature_K=t0)
    trials=[]
    for j in range(N_STARTS):
        x=x0 if j==0 else np.clip(x0+rng.normal(0,.18,len(ACTIVE)),.05,.95)
        opt=least_squares(objective,x,args=(fitix,f'start_{j}'),bounds=(np.zeros(len(x)),np.ones(len(x))),
            loss='soft_l1',f_scale=.3,diff_step=1e-3,max_nfev=MAX_NFEV,ftol=1e-6,xtol=1e-6,gtol=1e-6)
        pred,_=predict(opt.x);vc=cost(residual(pred,val))
        rec={'start':j,'internal_fit_cost':cost(residual(pred,fitix)),'validation_cost':vc,
             'nfev':opt.nfev,'status':int(opt.status),'message':str(opt.message),'x':opt.x.tolist()}
        trials.append(rec);write_json(out/'training_candidates.json',trials)
        print('START_COMPLETE '+json.dumps(rec),flush=True)
    best=min(trials,key=lambda t:t['validation_cost'])
    opt=least_squares(objective,best['x'],args=(np.arange(len(ix)),'refit_train'),
        bounds=(np.zeros(len(ACTIVE)),np.ones(len(ACTIVE))),loss='soft_l1',f_scale=.3,
        diff_step=1e-3,max_nfev=MAX_NFEV,ftol=1e-6,xtol=1e-6,gtol=1e-6)
    pred,temp=predict(opt.x);params=encode_params(opt.x)
    write_json(ROOT/'models/fitted_parameters.json',params)
    text='.model nfet asmhemt (\n'+'\n'.join(f'+ {k}={v:.14g}' for k,v in params.items())+'\n+ )\n'
    (ROOT/'models/fitted_model.lib').write_text(text,encoding='utf-8')
    np.savez_compressed(out/'frozen_predictions.npz',prediction=pred,delta_temperature_K=temp)
    freeze={'frozen_utc':stamp(),'protocol_version':2,'parameters_sha256':sha(ROOT/'models/fitted_parameters.json'),
        'prediction_sha256':sha(out/'frozen_predictions.npz'),'protocol_sha256':sha(out/'fit_protocol.json'),
        'train_sha256':train_hash,'test_targets_used':False,'selected_start':best['start'],
        'simulation_calls':calls,'failed_simulations':failed,'elapsed_seconds':time.perf_counter()-start,
        'refit_nfev':opt.nfev,'refit_status':int(opt.status),'refit_message':str(opt.message),
        'training_cost_before':cost(residual(initial,np.arange(len(ix)))),
        'training_cost_after':cost(residual(pred,np.arange(len(ix)))),
        'normalized_x':opt.x.tolist(),'parameter_count_active':len(ACTIVE)}
    write_json(out/'freeze.json',freeze);print('FROZEN '+json.dumps(freeze),flush=True)

def metrics(y,p):
    result={}
    for j,name in enumerate(['id_A','gm_S']):
        e=p[:,j]-y[:,j];span=float(np.ptp(y[:,j]));floor=[ID_FLOOR,GM_FLOOR][j]
        m=np.abs(y[:,j])>=floor
        result[name]={'rmse':float(np.sqrt(np.mean(e*e))),'mae':float(np.mean(np.abs(e))),
            'nrmse_by_observed_range':float(np.sqrt(np.mean(e*e))/span),
            'asinh_rmse':float(np.sqrt(np.mean((np.arcsinh(p[:,j]/floor)-np.arcsinh(y[:,j]/floor))**2))),
            'median_absolute_relative_error_above_floor':float(np.median(np.abs(e[m]/y[m,j]))),
            'relative_error_floor':floor,'points_above_floor':int(m.sum()),'observed_range':span}
    return result

def evaluate():
    out=ROOT/'results';freeze=read_json(out/'freeze.json')
    assert sha(ROOT/'models/fitted_parameters.json')==freeze['parameters_sha256']
    assert sha(out/'frozen_predictions.npz')==freeze['prediction_sha256']
    if (out/'test_evaluation.json').exists():raise RuntimeError('Held-out evaluation already exists. Do not use test feedback for retuning.')
    after=np.load(out/'frozen_predictions.npz');before=np.load(out/'initial_predictions.npz')['prediction']
    pred=after['prediction'];temp=after['delta_temperature_K'];summary={}
    for split in ['train','test']:
        rows,ix,y=load(ROOT/f'data/{split}.csv')
        safe=safe_gm_mask(ix)
        summary[split]={'n':len(y),'before':metrics(y,before[ix]),'after':metrics(y,pred[ix]),
            'same_subset_gm_stencil_count':int(safe.sum()),
            'gm_safe_before':metrics(y[safe],before[ix[safe]])['gm_S'],
            'gm_safe_after':metrics(y[safe],pred[ix[safe]])['gm_S']}
        with (out/f'{split}_predictions.csv').open('w',newline='',encoding='utf-8') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0])+['id_before_A','id_after_A','gm_before_S','gm_after_S']);w.writeheader()
            for r,i in zip(rows,ix):w.writerow(r|{'id_before_A':before[i,0],'id_after_A':pred[i,0],'gm_before_S':before[i,1],'gm_after_S':pred[i,1]})
    x=np.array(freeze['normalized_x']);p=read_json(ROOT/'models/fitted_parameters.json')
    hits=[k for k,u in zip(ACTIVE,x) if u<.01 or u>.99]
    qa={'scope':'Local DC sanity checks, not official competition QA.',
        'finite_predictions':bool(np.isfinite(pred).all()),'finite_temperature':bool(np.isfinite(temp).all()),
        'id_min_A':float(pred[:,0].min()),'id_max_A':float(pred[:,0].max()),
        'gm_min_S':float(pred[:,1].min()),'delta_temperature_min_K':float(temp.min()),'delta_temperature_max_K':float(temp.max()),
        'near_bound_parameters':hits,'bounds_pass':bool(((x>=0)&(x<=1)).all()),
        'nonnegative_id_with_1uA_tolerance':bool((pred[:,0]>=-1e-6).all()),
        'nonnegative_gm_with_1mS_tolerance':bool((pred[:,1]>=-1e-3).all()),
        'temperature_below_600K_at_context_298K':bool((temp+298.15<600).all())}
    write_json(out/'local_qa.json',qa)
    write_json(out/'test_evaluation.json',{'evaluated_utc':stamp(),'freeze_sha256':sha(out/'freeze.json'),
       'test_sha256':sha(ROOT/'data/test.csv'),'single_evaluation_this_protocol':True,
       'previous_protocol_test_seen':True,'protocol_version':2,'metrics':summary})
    print(json.dumps({'metrics':summary,'qa':qa},indent=2),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','fit','evaluate'])
    args=parser.parse_args();globals()[args.action]()
