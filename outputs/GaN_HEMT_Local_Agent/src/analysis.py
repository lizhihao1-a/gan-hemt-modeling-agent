"""Training-only diagnostics and fixed-budget grouped validation."""
import csv,time,hashlib,json
from pathlib import Path
import numpy as np
from scipy.optimize import least_squares
from scipy.linalg import svd
from config import ACTIVE
from common import *
from backend import LocalBackend,NativeAttemptLimit

def backend(root,log,protocol):
    return LocalBackend(root,log,protocol['simulation_timeout_seconds'],protocol['simulation_retries'])

def diagnose(root,out,log,protocol):
    _,ix,y=load_data(root/'data/train.csv');target=Targets(ix,y)
    x=normalized(read_json(root/'reference/fitted_parameters.json'))
    derivatives=[];rows=[];profiles=[]
    with backend(root,log,protocol) as sim:
        p,temp=sim.simulate(x);r=target.residual(p);base=target.cost(p)
        for j,k in enumerate(ACTIVE):
            estimates=[]
            for h in [protocol['diagnostic_step'],protocol['diagnostic_step']/3]:
                lo=x.copy();hi=x.copy();lo[j]=max(0,x[j]-h);hi[j]=min(1,x[j]+h)
                a,_=sim.simulate(lo);b,_=sim.simulate(hi)
                estimates.append((target.residual(b)-target.residual(a))/(hi[j]-lo[j]))
            d=estimates[0];derivatives.append(d)
            norm=float(np.sqrt(np.mean(d*d)))
            stability=float(np.linalg.norm(d-estimates[1])/max(np.linalg.norm(estimates[1]),1e-12))
            bound='lower' if x[j]<.01 else ('upper' if x[j]>.99 else '')
            rows.append({'parameter':k,'normalized_position':float(x[j]),'near_bound':bound,
                         'rms_sensitivity':norm,'relative_step_disagreement':stability})
            if bound:
                for distance in [.02,.05,.1]:
                    q=x.copy();q[j]=min(1,x[j]+distance) if bound=='lower' else max(0,x[j]-distance)
                    v,_=sim.simulate(q)
                    profiles.append({'parameter':k,'inward_fraction_of_range':distance,
                        'training_cost':target.cost(v),'cost_change_fraction':(target.cost(v)-base)/base})
        calls=sim.calls
    J=np.column_stack(derivatives);_,s,Vh=svd(J,full_matrices=False)
    norms=np.linalg.norm(J,axis=0);cos=(J.T@J)/np.maximum(np.outer(norms,norms),1e-30)
    pairs=sorted([{'a':ACTIVE[i],'b':ACTIVE[j],'absolute_derivative_cosine':float(abs(cos[i,j]))}
        for i in range(23) for j in range(i+1,23) if abs(cos[i,j])>.98],key=lambda r:-r['absolute_derivative_cosine'])
    modes=[]
    for v in Vh[-3:]:
        order=np.argsort(abs(v))[::-1][:5]
        modes.append({ACTIVE[j]:float(v[j]) for j in order})
    rank=int((s>s[0]*protocol['diagnostic_rank_relative_threshold']).sum())
    regions=[]
    for name,mask in [('Vds<=2V',ix%201<=20),('2<Vds<=10V',(ix%201>20)&(ix%201<=100)),('Vds>10V',ix%201>100)]:
        regions.append({'region':name,'points':int(mask.sum()),'metrics':metric(y[mask],p[ix[mask]],target.scales)})
    out.mkdir(parents=True,exist_ok=True)
    np.savez_compressed(out/'jacobian.npz',jacobian=J,cosines=cos,singular_values=s,grid_index=ix)
    with (out/'parameter_sensitivity.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    result={'scope':'Training-only local numerical diagnostics at the frozen baseline; no confidence intervals or uniqueness claim.',
      'source_parameter_sha256':sha(root/'reference/fitted_parameters.json'),'target_rows':len(ix),
      'safe_gm_targets':int(target.safe.sum()),'training_cost':base,'simulation_calls':calls,
      'parameters':rows,'inward_perturbations':profiles,'high_coupling_pairs':pairs,'weak_modes':modes,
      'singular_values':s.tolist(),'relative_rank_threshold':protocol['diagnostic_rank_relative_threshold'],
      'numerical_rank':rank,'condition_number':float(s[0]/s[-1]) if s[-1]>0 else None,
      'training_regions':regions,'bounds_changed':False,'test_targets_used':False}
    atomic_json(out/'diagnostics.json',result)
    event(log,'diagnostics_complete',rank=rank,bound_parameters=[r['parameter'] for r in rows if r['near_bound']],real_simulations=calls)
    return result

class BudgetExceeded(RuntimeError):pass

def fit_job(root,jobdir,log,protocol,fit_target,x0,active,max_nfev,label):
    """Checkpoint granularity is one completed optimization job, not one SciPy iteration."""
    jobdir.mkdir(parents=True,exist_ok=True)
    signature=hashlib.sha256(fit_target.ix.tobytes()+fit_target.y.tobytes()+fit_target.scales.tobytes()+
        np.asarray(x0).tobytes()+json.dumps({'active':active,'max_nfev':max_nfev,'protocol':protocol},sort_keys=True).encode()).hexdigest()
    if (jobdir/'job.json').exists():
        result=read_json(jobdir/'job.json')
        if result['signature']!=signature:raise RuntimeError('Completed job signature changed')
        assert_manifest(result['artifacts'],jobdir)
        event(log,'job_reused',job=label)
        return result,np.load(jobdir/'prediction.npz')['prediction']
    selected=np.array([ACTIVE.index(k) for k in active]);start=time.perf_counter();evaluations=0
    best_cost=float('inf');best_x=np.asarray(x0).copy();best_prediction=None;best_temperature=None;status='';messages=[]
    trace=jobdir/'trace.jsonl';trace.write_text('',encoding='utf-8')
    with backend(root,log,protocol) as sim:
        sim.attempt_limit=protocol['job_simulation_limit']
        def expand(z):
            x=np.asarray(x0).copy();x[selected]=z;return x
        def objective(z):
            nonlocal evaluations,best_cost,best_x,best_prediction,best_temperature
            if sim.calls>=protocol['job_simulation_limit']-1 or time.perf_counter()-start>protocol['job_deadline_seconds']:
                raise BudgetExceeded('Per-job simulation/time budget exhausted')
            x=expand(z);p,t=sim.simulate(x);evaluations+=1;r=fit_target.residual(p);c=robust_cost(r)
            if c<best_cost:best_cost=c;best_x=x.copy();best_prediction=p.copy();best_temperature=t.copy()
            if evaluations%25==0:event(trace,'objective',evaluation=evaluations,cost=c,seconds=time.perf_counter()-start)
            if evaluations%250==0:print(json.dumps({'job':label,'simulation':evaluations,'training_cost':c}),flush=True)
            return r
        event(log,'job_started',job=label,active=active,target_rows=len(fit_target.ix),safe_gm=int(fit_target.safe.sum()),max_nfev=max_nfev)
        try:
            opt=least_squares(objective,np.asarray(x0)[selected],bounds=(np.zeros(len(selected)),np.ones(len(selected))),
                loss='soft_l1',f_scale=.3,diff_step=protocol['finite_difference_step'],max_nfev=max_nfev,
                ftol=1e-6,xtol=1e-6,gtol=1e-6)
            final_x=expand(opt.x);status='converged' if opt.status>0 else 'evaluation_budget';messages.append(str(opt.message));nfev=int(opt.nfev)
        except (BudgetExceeded,NativeAttemptLimit) as e:
            if not np.isfinite(best_cost):raise
            final_x=best_x;status='budget_exhausted';messages.append(str(e));nfev=None
        if status=='budget_exhausted':
            final_x=best_x;final=best_prediction;temp=best_temperature
        else:
            try:final,temp=sim.simulate(final_x)
            except NativeAttemptLimit:
                final_x=best_x;final=best_prediction;temp=best_temperature;status='budget_exhausted'
                messages.append('Retained best completed prediction; no call beyond the native attempt limit')
        result={'label':label,'signature':signature,'x':final_x.tolist(),'status':status,'messages':messages,
            'nfev':nfev,'real_simulation_attempts':sim.calls,'failed_attempts':sim.failures,
            'training_cost':fit_target.cost(final),'elapsed_seconds':time.perf_counter()-start,
            'active':active,'fit_rows':len(fit_target.ix),'safe_gm_targets':int(fit_target.safe.sum())}
    np.savez_compressed(jobdir/'prediction.npz',prediction=final,temperature=temp)
    result['artifacts']={'prediction.npz':sha(jobdir/'prediction.npz'),'trace.jsonl':sha(trace)}
    atomic_json(jobdir/'job.json',result);event(log,'job_complete',**{k:v for k,v in result.items() if k not in ['x','artifacts']})
    return result,final

def grouped_validation(root,out,log,protocol):
    rows,ix,y=load_data(root/'data/train.csv');groups=ix//201;folds=[];oof=np.empty_like(y)
    for fold,held_groups in enumerate(protocol['curve_folds']):
        val=np.isin(groups,held_groups);fit=~val
        train=Targets(ix[fit],y[fit]);validation=Targets(ix[val],y[val],train.scales)
        assert not set(groups[fit])&set(groups[val])
        job,pred=fit_job(root,out/f'fold_{fold}',log,protocol,train,np.full(23,.5),ACTIVE,protocol['cv_max_nfev'],f'curve_fold_{fold}')
        oof[val]=pred[ix[val]]
        folds.append({'fold':fold,'held_out_curve_indices':held_groups,'fit_curve_indices':sorted(map(int,set(groups[fit]))),
            'fit_points':int(fit.sum()),'validation_points':int(val.sum()),'safe_fit_gm':int(train.safe.sum()),
            'safe_validation_gm':int(validation.safe.sum()),'status':job['status'],
            'id_and_full_gm_metrics':metric(y[val],pred[ix[val]],train.scales),
            'safe_gm_metrics':metric(y[val][validation.safe],pred[ix[val]][validation.safe],train.scales)['gm_S'],
            'validation_cost':validation.cost(pred),'initialization':'Published parameter-range midpoint; no frozen fitted parameters.'})
        event(log,'curve_fold_complete',fold=fold,metrics=folds[-1]);print('CURVE_FOLD_COMPLETE '+json.dumps(folds[-1]),flush=True)
    with (out/'curve_oof_predictions.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.writer(f);w.writerow(['point_id','grid_index','vgs_V','vds_V','measured_id_A','predicted_id_A','measured_gm_S','predicted_gm_S'])
        for r,i,m,p in zip(rows,ix,y,oof):w.writerow([r['point_id'],int(i),r['vgs_V'],r['vds_V'],*list(np.array([m[0],p[0],m[1],p[1]]))])
    summary={'scope':'Three contiguous Vgs curve groups; only the 4824 author-training rows. Reuses known data, not a new blind test.',
      'all_validation_groups_disjoint_from_corresponding_fit':True,'test_targets_used':False,'folds':folds,
      'all_training_rows_validated_once':True,'overall_oof_metrics':metric(y,oof,Targets(ix,y).scales),
      'bounds_and_protocol_selected_using_cv':False}
    atomic_json(out/'curve_cv.json',summary);return summary
