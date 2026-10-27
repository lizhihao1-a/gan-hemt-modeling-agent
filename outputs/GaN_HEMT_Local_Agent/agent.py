"""Usage: python agent.py run [--resume] [--stop-after curve_validate]."""
from pathlib import Path
import sys,os,json,argparse,hashlib,time
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT.parent.parent/'work/dfo_deps'));sys.path.insert(0,str(ROOT/'.deps'))
os.environ['MPLCONFIGDIR']=str(ROOT/'.cache/matplotlib')
from common import *
from analysis import diagnose,grouped_validation
from workflow import fit_agent,verify

STAGES=['diagnose','curve_validate','fit','verify','report']
DIRS={'diagnose':'diagnostics','curve_validate':'curve_validation','fit':'agent','verify':'verification','report':'report'}

def inputs():
    files=[ROOT/'protocol.json',ROOT/'agent.py',*sorted((ROOT/'src').glob('*.py')),
        ROOT/'data/train.csv',ROOT/'data/test.csv',ROOT/'models/asmhemt.va',ROOT/'models/asmhemt.osdi',
        ROOT/'reference/fitted_parameters.json',ROOT/'reference/freeze.json']
    return manifest(files,ROOT)
def preflight():
    protocol=read_json(ROOT/'protocol.json')
    if protocol['official_mcp_enabled'] or protocol['domestic_llm_enabled']:
        raise RuntimeError('Official backends are unavailable; configure and validate actual adapters first')
    _,ix,y=load_data(ROOT/'data/train.csv')
    if len(ix)!=4824:raise RuntimeError('Expected original author 4824-row training set')
    folds=protocol['curve_folds'];flat=[g for fold in folds for g in fold]
    if sorted(flat)!=list(range(30)):raise RuntimeError('Curve folds must partition 30 gate-voltage groups')
    for split in ['train','test']:
        if sha(ROOT/f'data/{split}.csv')!=read_json(ROOT/'data/manifest.json')[split+'_sha256']:
            raise RuntimeError('Original split checksum mismatch')
    if sha(ROOT/'reference/fitted_parameters.json')!=read_json(ROOT/'reference/freeze.json')['parameters_sha256']:
        raise RuntimeError('Reference baseline is not the frozen model')
    return protocol
def run(resume=False,stop_after=None):
    result=ROOT/'results';result.mkdir(exist_ok=True);statefile=result/'run_state.json';log=result/'events.jsonl'
    with RunLock(result/'run.lock'):
        protocol=preflight();fingerprint=inputs()
        if statefile.exists():
            if not resume:raise RuntimeError('Run exists. Use --resume or copy to a fresh project; frozen outputs are preserved.')
            state=read_json(statefile);assert_manifest(state['inputs'],ROOT)
            if state['inputs']!=fingerprint:raise RuntimeError('Run inputs/source changed; resume refused')
            for record in state['completed'].values():assert_manifest(record['artifacts'],ROOT)
            event(log,'run_resumed',already_completed=list(state['completed']))
        else:
            if resume:raise RuntimeError('No checkpoint to resume')
            state={'created_utc':now(),'inputs':fingerprint,'completed':{},'status':'running',
                'transport':'local_process','planner':'deterministic_rules','official_mcp_calls':0,'domestic_llm_calls':0}
            atomic_json(result/'predeclared_protocol.json',protocol);event(log,'run_started',protocol_sha256=sha(ROOT/'protocol.json'))
        for stage in STAGES:
            if stage in state['completed']:continue
            state['active_stage']=stage;state['status']='running';atomic_json(statefile,state)
            out=result/DIRS[stage];out.mkdir(exist_ok=True);started=time.perf_counter();event(log,'stage_started',stage=stage)
            try:
                if stage=='diagnose':diagnose(ROOT,out,log,protocol)
                elif stage=='curve_validate':grouped_validation(ROOT,out,log,protocol)
                elif stage=='fit':fit_agent(ROOT,out,log,protocol)
                elif stage=='verify':verify(ROOT,out,log,protocol)
                else:
                    from reporting import render
                    render(ROOT,out)
                files=[p for p in out.rglob('*') if p.is_file()]
                if stage=='fit':files += [ROOT/'models/fitted_parameters.json',ROOT/'models/fitted_model.lib']
                state['completed'][stage]={'completed_utc':now(),'seconds':time.perf_counter()-started,'artifacts':manifest(files,ROOT)}
                atomic_json(statefile,state);event(log,'stage_complete',stage=stage,seconds=state['completed'][stage]['seconds'])
                if stage==stop_after:
                    state['status']='checkpointed';atomic_json(statefile,state);event(log,'checkpoint_stop',stage=stage)
                    print('CHECKPOINTED '+stage,flush=True);return
            except BaseException as e:
                state['status']='interrupted' if isinstance(e,KeyboardInterrupt) else 'failed';state['error']=repr(e)
                atomic_json(statefile,state);event(log,'stage_failed',stage=stage,error=repr(e));raise
        state['status']='complete';state['active_stage']=None;state.pop('error',None);state['completed_utc']=now()
        atomic_json(statefile,state);event(log,'run_complete',completed_stages=STAGES)
        print('COMPLETE '+str(result/'report/overview.html'),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['run','status']);p.add_argument('--resume',action='store_true')
    p.add_argument('--stop-after',choices=STAGES);args=p.parse_args()
    if args.action=='status':print(json.dumps(read_json(ROOT/'results/run_state.json'),ensure_ascii=False,indent=2))
    else:run(args.resume,args.stop_after)
