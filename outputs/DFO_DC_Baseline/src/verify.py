"""Validate a model card in a separate ngspice executable, and audit target stencils."""
import sys,json,subprocess,csv,zipfile,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];WS=ROOT.parent.parent
sys.path.insert(0,str(WS/'work/dfo_deps'));sys.path.insert(0,str(ROOT/'.deps'))
import numpy as np
from baseline import read_json,write_json,sha,load,safe_gm_mask

out=ROOT/'results';vdir=out/'verification';vdir.mkdir(exist_ok=True)
freeze=read_json(out/'freeze.json');protocol=read_json(out/'fit_protocol.json')
assert sha(ROOT/'models/fitted_parameters.json')==freeze['parameters_sha256']
assert sha(out/'frozen_predictions.npz')==freeze['prediction_sha256']
assert sha(ROOT/'data/train.csv')==freeze['train_sha256']
_,ix,y=load(ROOT/'data/train.csv');_,testix,testy=load(ROOT/'data/test.csv')
assert len(set(ix)&set(testix))==0 and len(set(ix)|set(testix))==6030
assert safe_gm_mask(ix).sum()==protocol['safe_gm_full_train']
for key in ['fit_point_ids','validation_point_ids']:
    subset=set(protocol[key]);assert subset<=set(ix)
    for i,safe in zip(protocol[key],safe_gm_mask(protocol[key])):
        if safe:
            g=i//201;stencil=[i,i+201] if g==0 else ([i-201,i] if g==29 else [i-201,i+201])
            assert all(j in subset and j not in set(testix) for j in stencil)
card='../../models/fitted_model.lib'
netlist=f'''DFO card verification
.include {card}
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
.end
'''
(vdir/'card.cir').write_text(netlist,encoding='utf-8')
control=f'''.control
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
(vdir/'run.cir').write_text(netlist.replace('.end\n',control),encoding='utf-8')
(vdir/'spinit').write_text('osdi ../../models/asmhemt.osdi\nset num_threads=1\n',encoding='utf-8')
exe=ROOT/'runtime/ngspice_con.exe'
if not exe.exists():exe=WS/'work/dfo_tools/ngspice/Spice64/bin/ngspice_con.exe'
r=subprocess.run([str(exe),'-b','-n','run.cir'],cwd=vdir,env=dict(os.environ,SPICE_SCRIPTS=str(vdir)),capture_output=True,text=True,timeout=120)
(vdir/'ngspice_console.log').write_text(r.stdout+'\n'+r.stderr,encoding='utf-8')
assert r.returncode==0,(r.returncode,r.stdout,r.stderr)
cli=np.loadtxt(vdir/'cli_prediction.txt',skiprows=1)
frozen=np.load(out/'frozen_predictions.npz');prediction=frozen['prediction']
assert cli.shape==(6030,3),cli.shape
gm=np.gradient(cli[:,1].reshape(30,201),.1,axis=0).ravel()
diff_id=float(np.max(np.abs(cli[:,1]-prediction[:,0])))
diff_gm=float(np.max(np.abs(gm-prediction[:,1])))
diff_temp=float(np.max(np.abs(cli[:,2]-frozen['delta_temperature_K'].ravel())))
assert diff_id<1e-8 and diff_gm<1e-7 and diff_temp<1e-4
all_y=np.empty((6030,2));all_y[ix]=y;all_y[testix]=testy
meas_gm_diff=float(np.max(np.abs(np.gradient(all_y[:,0].reshape(30,201),.1,axis=0).ravel()-all_y[:,1])))
result={'model_card_cli_pass':True,'points_compared':6030,'max_id_difference_A':diff_id,
    'max_gm_difference_S':diff_gm,'max_delta_temperature_difference_K':diff_temp,
    'train_test_disjoint':True,'training_stencils_exclude_test_targets':True,
    'source_gm_full_grid_gradient_max_difference_S':meas_gm_diff,
    'safe_train_gm_count':int(safe_gm_mask(ix).sum()),'safe_test_gm_count':int(safe_gm_mask(testix).sum())}
write_json(out/'verification.json',result);print(json.dumps(result,indent=2))
