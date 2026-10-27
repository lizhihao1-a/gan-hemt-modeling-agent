"""Rule-controlled modeling workflow; no network or LLM claims."""
import csv,os,subprocess,time
from pathlib import Path
import numpy as np
from common import *
from config import ACTIVE
from analysis import fit_job,diagnose,grouped_validation

def qa(pred,temp,x,protocol):
    limits=protocol['qa']
    checks={'finite':bool(np.isfinite(pred).all() and np.isfinite(temp).all()),
        'bounds':bool(np.all(np.array(x)>=0) and np.all(np.array(x)<=1)),
        'id_tolerance':bool(pred[:,0].min()>=limits['minimum_id_A']),
        'gm_tolerance':bool(pred[:,1].min()>=limits['minimum_gm_S']),
        'temperature_limit':bool((temp+298.15).max()<limits['maximum_model_temperature_K'])}
    return {'passed':all(checks.values()),'checks':checks,'min_id_A':float(pred[:,0].min()),
        'min_gm_S':float(pred[:,1].min()),'max_context_temperature_K':float(temp.max()+298.15),
        'near_bound':[k for k,u in zip(ACTIVE,x) if u<.01 or u>.99],
        'scope':'Local DC tolerance checks only; not official QA_pass_rate.'}

class RulePlanner:
    def __init__(self,protocol):self.protocol=protocol
    def next_action(self,metrics,check):
        id_error=metrics['id_A']['nrmse_train_range']
        gm_error=metrics['gm_S']['nrmse_train_range'] if metrics['gm_S'] else None
        reasons=[]
        if not check['passed']:reasons.append('local QA failed')
        if id_error>self.protocol['validation_id_nrmse_target']:reasons.append('validation Id target unmet')
        if gm_error is not None and gm_error>self.protocol['validation_gm_nrmse_target']:reasons.append('validation gm target unmet')
        return {'action':'refine_all_23' if reasons else 'accept_core_16',
                'reasons':reasons or ['predeclared validation and local QA thresholds satisfied'],
                'planner':'deterministic_rules','external_llm_calls':0}

def fit_agent(root,out,log,protocol):
    rows,ix,y=load_data(root/'data/train.csv');val=np.isin(ix//201,protocol['agent_validation_curves']);fit=~val
    ft=Targets(ix[fit],y[fit]);vt=Targets(ix[val],y[val],ft.scales)
    plan={'train_curve_indices':sorted(map(int,set((ix//201)[fit]))),
        'validation_curve_indices':protocol['agent_validation_curves'],'fit_points':int(fit.sum()),
        'validation_points':int(val.sum()),'safe_fit_gm':int(ft.safe.sum()),'safe_validation_gm':int(vt.safe.sum()),
        'initialization':'published-range midpoint','test_targets_used':False,
        'core_parameters':ACTIVE[:16],'refine_parameters':ACTIVE,'bounds_expansion':False}
    out.mkdir(parents=True,exist_ok=True);atomic_json(out/'plan.json',plan)
    candidates=[]
    def candidate(job,pred):
        temp=np.load(out/job['label']/'prediction.npz')['temperature']
        check=qa(pred,temp,job['x'],protocol)
        metrics=metric(y[val],pred[ix[val]],ft.scales)
        safe_metrics=metric(y[val][vt.safe],pred[ix[val]][vt.safe],ft.scales)
        decision_metrics={'id_A':metrics['id_A'],'gm_S':safe_metrics['gm_S']}
        return {'job':job['label'],'x':job['x'],'active':job['active'],'qa':check,
          'validation_cost':vt.cost(pred),'validation_metrics':metrics,'safe_validation_metrics':safe_metrics,
          'decision_metrics':decision_metrics}
    core,pred=fit_job(root,out/'core',log,protocol,ft,np.full(23,.5),ACTIVE[:16],protocol['core_max_nfev'],'core')
    candidates.append(candidate(core,pred))
    decision=RulePlanner(protocol).next_action(candidates[-1]['decision_metrics'],candidates[-1]['qa'])
    event(log,'planner_decision',**decision);atomic_json(out/'decision.json',decision)
    if decision['action']=='refine_all_23':
        refined,pred=fit_job(root,out/'refine',log,protocol,ft,np.array(core['x']),ACTIVE,protocol['refine_max_nfev'],'refine')
        candidates.append(candidate(refined,pred))
    viable=[c for c in candidates if c['qa']['passed']]
    if not viable:raise RuntimeError('All candidate models failed local QA; no model exported')
    chosen=min(viable,key=lambda c:c['validation_cost']);atomic_json(out/'candidates.json',candidates)
    full=Targets(ix,y)
    refit,pred=fit_job(root,out/'refit',log,protocol,full,np.array(chosen['x']),chosen['active'],protocol['refit_max_nfev'],'refit')
    temp=np.load(out/'refit/prediction.npz')['temperature'];check=qa(pred,temp,refit['x'],protocol)
    fallback=False
    if not check['passed']:
        # Physics-based rollback; no test measurements are available to this function.
        fallback=True;refit={'x':chosen['x']}
        z=np.load(out/chosen['job']/'prediction.npz');pred=z['prediction'];temp=z['temperature'];check=chosen['qa']
        event(log,'qa_fallback',selected_job=chosen['job'])
    x=np.array(refit['x']);params=parameters(x)
    atomic_json(root/'models/fitted_parameters.json',params)
    (root/'models/fitted_model.lib').write_text(model_card(params),encoding='utf-8')
    np.savez_compressed(out/'frozen_prediction.npz',prediction=pred,temperature=temp)
    freeze={'frozen_utc':now(),'parameters_sha256':sha(root/'models/fitted_parameters.json'),
      'model_card_sha256':sha(root/'models/fitted_model.lib'),'prediction_sha256':sha(out/'frozen_prediction.npz'),
      'source_model_sha256':sha(root/'models/asmhemt.osdi'),'train_sha256':sha(root/'data/train.csv'),
      'protocol_sha256':sha(root/'protocol.json'),'selected_validation_job':chosen['job'],
      'validation_cost':chosen['validation_cost'],'x':x.tolist(),'qa':check,'qa_fallback':fallback,
      'planner':'deterministic_rules','test_targets_used':False,'official_mcp_calls':0,'domestic_llm_calls':0}
    atomic_json(out/'freeze.json',freeze);event(log,'model_frozen',**{k:v for k,v in freeze.items() if k not in ['x','qa']})
    return freeze

def verify_card(root,out,freeze,pred,temp):
    out.mkdir(parents=True,exist_ok=True)
    net='''Independent Agent card verification
.include ../../models/fitted_model.lib
.temp 25
.options tnom=25 reltol=1e-5 abstol=1e-12
vd d 0 0
vg g 0 0
vs s 0 0
vb b 0 0
N1 di gi s b dt nfet
rth_external dt 0 1e12
r_gate g gi 0.3178
r_drain d di 0.4938
.save i(vd) v(dt)
.control
dc vd 0 20 0.1 vg -3 -0.1 0.1
let id_result=-i(vd)
set numdgt=16
set wr_vecnames
set wr_singlescale
wrdata cli_prediction.txt id_result v(dt)
destroy all
quit
.endc
.end
'''
    (out/'run.cir').write_text(net,encoding='utf-8')
    (out/'spinit').write_text('osdi ../../models/asmhemt.osdi\nset num_threads=1\n',encoding='utf-8')
    r=subprocess.run([str(root/'runtime/ngspice_con.exe'),'-b','-n','run.cir'],cwd=out,
        env=dict(os.environ,SPICE_SCRIPTS=str(out)),capture_output=True,text=True,timeout=30)
    (out/'ngspice_console.log').write_text(r.stdout+'\n'+r.stderr,encoding='utf-8')
    if r.returncode:raise RuntimeError('Standalone model-card verification failed: '+r.stderr)
    values=np.loadtxt(out/'cli_prediction.txt',skiprows=1)
    if values.shape!=(6030,3):raise RuntimeError('Unexpected standalone output dimensions')
    gm=np.gradient(values[:,1].reshape(30,201),.1,axis=0).ravel()
    diff=[float(np.max(abs(values[:,1]-pred[:,0]))),float(np.max(abs(gm-pred[:,1]))),float(np.max(abs(values[:,2]-temp)))]
    if diff[0]>1e-8 or diff[1]>1e-7 or diff[2]>1e-4:raise RuntimeError('Exported model card does not reproduce predictions')
    result={'passed':True,'exit_code':r.returncode,'points':6030,'max_difference_id_A':diff[0],
            'max_difference_gm_S':diff[1],'max_difference_delta_temperature_K':diff[2]}
    atomic_json(out/'card_verification.json',result);return result

def verify(root,out,log,protocol):
    model=root/'results/agent';freeze=read_json(model/'freeze.json')
    for p,key in [(root/'models/fitted_parameters.json','parameters_sha256'),(root/'models/fitted_model.lib','model_card_sha256'),
                  (model/'frozen_prediction.npz','prediction_sha256'),(root/'data/train.csv','train_sha256')]:
        if sha(p)!=freeze[key]:raise RuntimeError('Frozen artifact changed: '+str(p))
    values=np.load(model/'frozen_prediction.npz');pred=values['prediction'];temp=values['temperature']
    card=verify_card(root,out,freeze,pred,temp)
    if (out/'test_metrics.json').exists():
        result=read_json(out/'test_metrics.json')
        if result['freeze_sha256']!=sha(model/'freeze.json'):raise RuntimeError('Evaluation belongs to another model')
        event(log,'evaluation_reused');return result
    event(log,'test_targets_opened_after_freeze',freeze_sha256=sha(model/'freeze.json'),previously_viewed_test=True)
    _,trainix,trainy=load_data(root/'data/train.csv');scales=Targets(trainix,trainy).scales;metrics={}
    for split in ['train','test']:
        rows,ix,y=load_data(root/f'data/{split}.csv');safe=safe_gm(ix)
        if split=='test' and set(ix)&set(trainix):raise RuntimeError('Train and test overlap')
        metrics[split]={'n':len(ix),'full_metrics':metric(y,pred[ix],scales),
            'safe_gm_count':int(safe.sum()),'safe_gm_metrics':metric(y[safe],pred[ix[safe]],scales)['gm_S']}
        with (out/f'{split}_predictions.csv').open('w',newline='',encoding='utf-8') as f:
            w=csv.writer(f);w.writerow(['point_id','grid_index','vgs_V','vds_V','measured_id_A','predicted_id_A','measured_gm_S','predicted_gm_S','gm_stencil_inside_split'])
            for r,i,m,p,s in zip(rows,ix,y,pred[ix],safe):w.writerow([r['point_id'],int(i),r['vgs_V'],r['vds_V'],m[0],p[0],m[1],p[1],int(s)])
    result={'evaluated_utc':now(),'freeze_sha256':sha(model/'freeze.json'),'previously_viewed_test':True,
      'purpose':'Post-freeze regression evaluation; not a new blind test and not model selection.',
      'metrics':metrics,'card_verification':card,'official_mcp_calls':0,'domestic_llm_calls':0}
    atomic_json(out/'test_metrics.json',result);event(log,'verification_complete',card_pass=card['passed'])
    return result
