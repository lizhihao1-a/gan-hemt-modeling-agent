"""Real backend fault recovery and workflow acceptance. No official calls."""
from pathlib import Path
import sys,os,argparse,json,time,subprocess
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT.parent.parent/'work/dfo_deps'));sys.path.insert(0,str(ROOT/'.deps'))
import numpy as np
from common import *
from backend import LocalBackend,OfficialMCPBackend,DomesticLLMPlanner,NotConfigured,NativeAttemptLimit
from analysis import fit_job

def backend_tests():
    out=ROOT/'results/acceptance_backend';out.mkdir(exist_ok=True);log=out/'events.jsonl'
    if log.exists():raise RuntimeError('Backend test evidence exists; preserve it rather than overwrite')
    checks={};started=time.perf_counter();x=np.full(23,.5)
    with LocalBackend(ROOT,log,timeout=2,retries=1) as sim:
        a,t=sim.simulate(x)
        b,_=sim.simulate(x,fault_once='crash_once')
        checks['native_worker_crash_recovers']=bool(np.max(abs(a-b))<1e-12)
        # Startup has its own 20 s deadline. Lower only the already-ready RPC deadline.
        sim.timeout=.15
        c,_=sim.simulate(x,fault_once='timeout_once')
        checks['native_worker_timeout_recovers']=bool(np.max(abs(a-c))<1e-12)
        before=sim.calls;bad=x.copy();bad[0]=1.01
        try:sim.simulate(bad);checks['out_of_bounds_rejected_before_native_call']=False
        except ValueError:checks['out_of_bounds_rejected_before_native_call']=sim.calls==before
        checks['two_injected_failures_observed']=sim.failures==2
        native_attempts=sim.calls
    with LocalBackend(ROOT,log,timeout=2,retries=1,attempt_limit=1) as capped:
        try:capped.simulate(x,fault_once='crash_once');checks['failed_retry_respects_real_attempt_limit']=False
        except NativeAttemptLimit:checks['failed_retry_respects_real_attempt_limit']=capped.calls==1 and capped.failures==1
        capped_attempts=capped.calls
    for cls,key in [(OfficialMCPBackend,'unconfigured_mcp_raises'),(DomesticLLMPlanner,'unconfigured_llm_raises')]:
        try:cls();checks[key]=False
        except NotConfigured:checks[key]=True
    _,ix,y=load_data(ROOT/'data/train.csv');unseen=set(range(6030))-set(ix)
    checks['training_gm_has_no_original_test_stencil']=all(not(set(stencil(int(i)))&unseen) for i in ix[safe_gm(ix)])
    protocol=read_json(ROOT/'protocol.json');folds=protocol['curve_folds'];safe_folds=True
    for groups in folds:
        val=np.isin(ix//201,groups);fit=~val
        safe_folds &= not bool(set((ix//201)[fit])&set((ix//201)[val]))
        for sub in [ix[fit],ix[val]]:
            known=set(sub)
            safe_folds &= all(set(stencil(int(i)))<=known for i in sub[safe_gm(sub)])
    checks['curve_groups_and_gm_stencils_isolated']=bool(safe_folds)
    fixture=out/'integrity_fixture.txt';fixture.write_text('frozen',encoding='utf-8');m={'integrity_fixture.txt':sha(fixture)}
    fixture.write_text('changed',encoding='utf-8')
    try:assert_manifest(m,out);checks['tampered_artifact_rejected']=False
    except RuntimeError:checks['tampered_artifact_rejected']=True
    probe=ROOT/'tests/lock_probe.py';lock=out/'probe.lock'
    with RunLock(lock):
        r=subprocess.run([sys.executable,str(probe),str(lock)],capture_output=True,text=True,timeout=20)
        checks['concurrent_run_lock_rejected']=r.returncode==0 and 'EXPECTED_LOCK_REJECTION' in r.stdout
    limited=protocol.copy();limited['job_simulation_limit']=2
    target=Targets(ix[:20],y[:20])
    job,pred=fit_job(ROOT,out/'budget_job',log,limited,target,np.full(23,.5),['VOFF'],10,'budget_probe')
    checks['real_call_budget_stops_and_exports_finite_checkpoint']=job['status']=='budget_exhausted' and np.isfinite(pred).all() and job['real_simulation_attempts']<=2
    result={'passed':all(checks.values()),'checks':checks,'fault_probe_native_attempts':native_attempts,'retry_budget_probe_native_attempts':capped_attempts,
        'seconds':time.perf_counter()-started,'notes':'Crash and timeout are deliberately injected into actual native worker processes; not optimizer failures or official tool calls.'}
    atomic_json(out/'backend_acceptance.json',result);print(json.dumps(result,indent=2));assert result['passed']

def final_tests():
    result=ROOT/'results';state=read_json(result/'run_state.json');checks={}
    checks['workflow_complete']=state['status']=='complete' and len(state['completed'])==5
    try:
        assert_manifest(state['inputs'],ROOT)
        for v in state['completed'].values():assert_manifest(v['artifacts'],ROOT)
        checks['all_input_and_completed_artifact_hashes_pass']=True
    except RuntimeError:checks['all_input_and_completed_artifact_hashes_pass']=False
    log=[json.loads(s) for s in (result/'events.jsonl').read_text(encoding='utf-8').splitlines()]
    starts={stage:sum(e['event']=='stage_started' and e['stage']==stage for e in log) for stage in state['completed']}
    checks['resume_did_not_repeat_completed_stages']=all(v==1 for v in starts.values()) and any(e['event']=='checkpoint_stop' for e in log) and any(e['event']=='run_resumed' for e in log)
    freeze_events=[i for i,e in enumerate(log) if e['event']=='model_frozen']
    reads=[i for i,e in enumerate(log) if e['event']=='test_targets_opened_after_freeze']
    checks['test_targets_only_opened_after_freeze']=len(freeze_events)==1 and len(reads)==1 and freeze_events[0]<reads[0]
    cv=read_json(result/'curve_validation/curve_cv.json')
    checks['three_curve_folds_use_training_domain_only']=cv['test_targets_used'] is False and len(cv['folds'])==3
    oof=list(csv.DictReader((result/'curve_validation/curve_oof_predictions.csv').open()))
    checks['all_4824_training_rows_validated_once']=len(oof)==4824 and len({r['point_id'] for r in oof})==4824
    v=read_json(result/'verification/card_verification.json');checks['independent_model_card_pass']=v['passed'] and v['exit_code']==0
    freeze=read_json(result/'agent/freeze.json');checks['local_final_model_qa_pass']=freeze['qa']['passed']
    checks['no_fabricated_official_or_llm_calls']=freeze['official_mcp_calls']==0 and freeze['domestic_llm_calls']==0 and all(e.get('transport','local_process')=='local_process' for e in log if e['event']=='tool_call')
    baseline=next((p/'DFO_DC_Baseline' for p in ROOT.parents if (p/'DFO_DC_Baseline').is_dir()),None)
    snapshot=read_json(ROOT/'reference/baseline_snapshot.json')
    def baseline_artifact(name):
        current=baseline/name
        if current.exists():return current
        if name.startswith('results/'):
            return baseline.parents[1]/'reports/baseline'/name.removeprefix('results/')
        return current
    checks['previous_frozen_baseline_unchanged']=all(sha(baseline_artifact(n))==h for n,h in snapshot.items()) if baseline else None
    native=sum(e['event']=='tool_call' for e in log);failures=sum(e['event']=='tool_result' and not e['ok'] for e in log)
    checks['each_real_simulation_attempt_has_result']=native==sum(e['event']=='tool_result' for e in log)
    checks['pipeline_has_no_injected_faults']=all(e.get('injected_fault') is None for e in log if e['event']=='tool_call')
    backend=read_json(result/'acceptance_backend/backend_acceptance.json');checks['backend_failure_recovery_tests_pass']=backend['passed']
    report={'passed':all(v is not False for v in checks.values()),'checked_utc':now(),'checks':checks,'external_baseline_available':baseline is not None,'real_pipeline_simulation_attempts':native,
        'pipeline_failed_simulation_attempts':failures,'backend_fault_tests':backend,'stage_start_counts':starts,
        'scope':'Local workflow/software acceptance; curve generalization and parameter identifiability are separate diagnostics.',
        'official_mcp_calls':0,'domestic_llm_calls':0}
    atomic_json(result/'acceptance.json',report)
    text='# 本地 Agent 运行验收\n\n'+('\n'.join(f'- {k}: {v}' for k,v in checks.items()))+f'\n\n真实流水线仿真尝试 {native} 次，失败 {failures} 次。故障注入测试另行隔离记录，不混入流水线统计。官方 MCP 与国内 LLM 调用均为 0。\n'
    (result/'acceptance.md').write_text(text,encoding='utf-8');print(json.dumps(report,indent=2,ensure_ascii=False));assert report['passed']

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('phase',choices=['backend','final']);a=p.parse_args()
    backend_tests() if a.phase=='backend' else final_tests()
