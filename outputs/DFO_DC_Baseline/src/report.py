"""Render scientific figures and a self-contained Chinese review page."""
import sys,json,csv,base64,html,hashlib,platform,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];WS=ROOT.parent.parent
sys.path.insert(0,str(WS/'work/dfo_deps'))
sys.path.insert(0,str(ROOT/'.deps'))
os.environ['MPLCONFIGDIR']=str(ROOT/'.cache/matplotlib')
import numpy as np
import scipy,matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from baseline import load,read_json,write_json,sha
from config import ACTIVE,BOUNDS

out=ROOT/'results';figs=out/'figures';figs.mkdir(exist_ok=True)
replay_note=''
if (out/'reproducibility.json').exists():
    replay_result=read_json(out/'reproducibility.json')
    replay_note=f"一键复跑验证：{replay_result['passed']}；独立目录重新拟合得到相同参数，逐点预测最大差异 {replay_result['max_absolute_prediction_difference']:.3g}。复跑只检验固定流程，不参与模型选择；证据见 results/reproducibility.json。"
evaluation=read_json(out/'test_evaluation.json');freeze=read_json(out/'freeze.json');qa=read_json(out/'local_qa.json')
initial=np.load(out/'initial_predictions.npz')['prediction'];final=np.load(out/'frozen_predictions.npz')['prediction']
params=read_json(ROOT/'models/fitted_parameters.json')
train,ti,ty=load(ROOT/'data/train.csv');test,ei,ey=load(ROOT/'data/test.csv')
measured=np.empty((6030,2));measured[ti]=ty;measured[ei]=ey
vg=np.round(np.arange(-3,0,.1),1);vd=np.round(np.arange(0,20.01,.1),1)
plt.rcParams.update({'font.size':10,'axes.grid':True,'grid.alpha':.2,'figure.dpi':130})
fig,axs=plt.subplots(2,2,figsize=(13,9),layout='constrained')
colors=plt.cm.viridis(np.linspace(0,1,7))
for g,c in zip([5,10,15,20,24,27,29],colors):
    sl=slice(g*201,(g+1)*201)
    axs[0,0].plot(vd,measured[sl,0]*1000,'.',color=c,ms=2)
    axs[0,0].plot(vd,final[sl,0]*1000,color=c,label=f'Vgs={vg[g]:.1f} V')
    axs[0,1].plot(vd,measured[sl,0]*1000,'.',color=c,ms=2)
    axs[0,1].plot(vd,initial[sl,0]*1000,'--',color=c)
axs[0,0].set(title='After fit: dots = measured, lines = ASM-HEMT',xlabel='Vds (V)',ylabel='Id (mA)');axs[0,0].legend(fontsize=8,ncol=2)
axs[0,1].set(title='Before fit: published-range midpoint initialization',xlabel='Vds (V)',ylabel='Id (mA)')
for d,c in zip([1,10,50,100,200],plt.cm.plasma(np.linspace(0,.9,5))):
    ix=np.arange(30)*201+d
    axs[1,0].semilogy(vg,np.maximum(measured[ix,0],1e-12),'.',color=c)
    axs[1,0].semilogy(vg,np.maximum(final[ix,0],1e-12),color=c,label=f'Vds={vd[d]:.1f} V')
    axs[1,1].plot(vg,measured[ix,1]*1000,'.',color=c)
    axs[1,1].plot(vg,final[ix,1]*1000,color=c)
axs[1,0].set(title='Transfer curves after fit',xlabel='Vgs (V)',ylabel='Id (A)');axs[1,0].legend(fontsize=8)
axs[1,1].set(title='Transconductance after fit (0.1 V finite difference)',xlabel='Vgs (V)',ylabel='gm (mS)')
fig.savefig(figs/'curve_comparison.png');plt.close(fig)

fig,axs=plt.subplots(1,2,figsize=(12,4.8),layout='constrained')
for j,ax in enumerate(axs):
    im=ax.imshow((final[:,j]-measured[:,j]).reshape(30,201)*1000,origin='lower',aspect='auto',extent=[0,20,-3,-.1],cmap='coolwarm',norm=matplotlib.colors.TwoSlopeNorm(vcenter=0))
    ax.set(title=['Id error (mA), after fit','gm error (mS), after fit'][j],xlabel='Vds (V)',ylabel='Vgs (V)');fig.colorbar(im,ax=ax)
fig.savefig(figs/'residual_map.png');plt.close(fig)

fig,axs=plt.subplots(1,2,figsize=(12,4.5),layout='constrained')
for j,ax in enumerate(axs):
    ax.scatter(ey[:,j]*1000,final[ei,j]*1000,s=7,alpha=.4)
    lo=min(ey[:,j].min(),final[ei,j].min())*1000;hi=max(ey[:,j].max(),final[ei,j].max())*1000
    ax.plot([lo,hi],[lo,hi],'k--',lw=1);ax.set(xlabel='Held-out measured '+['Id (mA)','gm (mS)'][j],ylabel='Predicted',title='Original test split: 1206 points')
fig.savefig(figs/'heldout_parity.png');plt.close(fig)

trace=[json.loads(s) for s in (out/'optimization_trace.jsonl').read_text().splitlines()]
fig,ax=plt.subplots(figsize=(10,3.5),layout='constrained')
for stage in dict.fromkeys(t['stage'] for t in trace):
    ts=[t for t in trace if t['stage']==stage];ax.semilogy([t['call'] for t in ts],[t['cost'] for t in ts],label=stage)
ax.set(xlabel='Real ngspice simulations',ylabel='Training robust cost',title='Optimization trace (test targets excluded)');ax.legend(ncol=4,fontsize=8)
fig.savefig(figs/'optimization_trace.png');plt.close(fig)

with (out/'parameter_review.csv').open('w',newline='',encoding='utf-8-sig') as f:
    w=csv.writer(f);w.writerow(['parameter','value','status','published_lower','published_upper','near_bound'])
    for k,v in params.items():
        b=BOUNDS.get(k);w.writerow([k,v,'optimized' if k in ACTIVE else 'fixed',b[0] if b else '',b[1] if b else '',k in qa['near_bound_parameters']])

m=evaluation['metrics'];lines=[]
worst={}
for j,k in enumerate(['id_A','gm_S']):
    i=int(np.argmax(np.abs(final[:,j]-measured[:,j])))
    worst[k]={'grid_index':i,'vgs_V':float(vg[i//201]),'vds_V':float(vd[i%201]),'absolute_error':float(abs(final[i,j]-measured[i,j]))}
write_json(out/'worst_points.json',worst)
for split,label in [('train','训练集'),('test','原始留出集')]:
    for key,label2,unit,factor in [('id_A','漏电流 Id','mA',1000),('gm_S','跨导 gm','mS',1000)]:
        a=m[split]['before'][key];b=m[split]['after'][key]
        lines.append(f'|{label} ({m[split]["n"]})|{label2}|{a["rmse"]*factor:.4f} → {b["rmse"]*factor:.4f} {unit}|{a["nrmse_by_observed_range"]*100:.3f}% → {b["nrmse_by_observed_range"]*100:.3f}%|')
report=f'''# DFO_4x50 ASM-HEMT 直流基线验证报告

已完成真实 ASM-HEMT 编译、仿真、训练集参数拟合、模型冻结和原始留出集评估。最终采用修正差分信息交叉的协议 2；早期协议 1 已查看过同一测试集，保留审计记录，因此这里不宣称测试集从未被查看。

|数据|指标|RMSE 拟合前 → 后|按本集合观测极差归一化的 RMSE|
|---|---|---|---|
{chr(10).join(lines)}

gm 表格采用原始 1206 点标签作曲线描述；严格限定差分所需 Id 都在测试集内后，仅有 {m['test']['same_subset_gm_stencil_count']} 个 gm 点，其 RMSE 为 {m['test']['gm_safe_after']['rmse']*1000:.4f} mS。Id 的 1206 点均用于留出评估。

整个网格最大绝对 Id 误差为 {worst['id_A']['absolute_error']*1000:.3f} mA（Vds={worst['id_A']['vds_V']} V、Vgs={worst['id_A']['vgs_V']} V），最大绝对 gm 误差为 {worst['gm_S']['absolute_error']*1000:.3f} mS（Vds={worst['gm_S']['vds_V']} V、Vgs={worst['gm_S']['vgs_V']} V）。较明显残差集中在低漏压过渡区，应结合残差图判断，不能只看全局平均误差。

## 数据与模型

- 6030 个偏置点：Vds 0–20 V、步长 0.1 V；Vgs −3.0–−0.1 V、步长 0.1 V。保留作者原始 4824/1206 训练/测试标签。
- 数据来源：[作者仓库](https://github.com/rafapm/dfo_parameter_extraction)，固定提交 a8d945a1d2f70c27998be7d0071cd6602bca02b5。原始 Id 单位按作者 SPICE 输出解释为 A，gm 为 S；未按栅宽再次归一化。
- 使用作者 notebook 同目录的 ASM-HEMT Verilog-A 101.4.0（源码头标注 2023-04-30）；原始 MDL 中的 ModelVersion=101.2 是另一处上下文记录，不据此替换源码版本。
- OpenVAF 22.12.0 编译原始源码，ngspice 47 Windows x64 通过 OSDI 执行；选用旧编译器是因为其内置链接器可在本机无 MSVC 工具链时完成编译。不是逐位复现作者 Linux/ngspice 42 环境。
- 几何：L=150 nm，W=50 μm，NF=4；外部栅/漏串阻 0.3178/0.4938 Ω，保持作者 netlist 设置。SHMOD=1，TRAPMOD=0。
- TEMP/TNOM=25 °C 为模型上下文假设，实际测量温度未获独立确认。gm 由 Id 按 0.1 V 栅压网格计算数值导数，端点单边，与作者代码方法一致。

## 训练协议与隔离

23 个直流/输运参数在作者公开的搜索范围内优化；初值为范围中点（对数参数用几何中点），未读取或使用作者 best_params、拟合历史或模拟曲线。其余 12 个搜索参数固定，几何和开关固定。公开范围本身含器件先验，因此这不是从零盲提参。

训练集内部按固定种子 {20261020} 划分 3859 个拟合点、965 个验证点，运行 3 个预先设定的初值，以内部验证代价选出候选，再仅用全部 4824 个训练点重拟合。采用 asinh 和线性复合残差及 soft_l1 鲁棒损失；转换尺度为 1e−4 A / 1e−3 S，这些是目标函数设置，不是仪器精度。

数据审计发现，原始 gm 与完整 Id 网格的 numpy.gradient 完全一致，最大差异约 3.4e−16 S。随机按行切分会使一部分训练 gm 间接包含测试 Id。协议 2 要求每个参与目标函数的 gm 的整个差分模板都在当前拟合子集内；内部验证亦单独检查模板，线性归一化尺度只用安全目标计算。完整训练集保留 {read_json(out/'fit_protocol.json')['safe_gm_full_train']} 个安全 gm 目标，其余 gm 项不进入优化。原有 Id 标签和 4824/1206 划分不变。

先前协议的测试结果已在发现这一结构问题前查看；协议 2 仅修正 gm 及其归一化的数据依赖，未根据测试误差更换参数范围、随机种子、初值数、损失转换尺度或优化预算。最终参数与预测再次冻结后才计算协议 2 的测试指标，未继续调参。旧协议记录保存在 audit/protocol_1。测试集仍是同一网格的随机留出点，且 gm 是 Id 的派生量；这些结果不能代表跨器件、跨温度或整个未见曲线的泛化能力，也不等同于新的盲测。

真实仿真调用 {freeze['simulation_calls']} 次，失败 {freeze['failed_simulations']} 次，拟合耗时 {freeze['elapsed_seconds']:.1f} 秒。最终优化器状态：{freeze['refit_message']}。以函数评估次数限制结束时，表示本轮预算用尽，不能据此宣称全局最优。

## 参数与物理检查

预测全部有限：{qa['finite_predictions']}；参数均在搜索范围内：{qa['bounds_pass']}；最小 Id={qa['id_min_A']:.4g} A；最大 Id={qa['id_max_A']:.6g} A；最大模型自热升温={qa['delta_temperature_max_K']:.2f} K。

导出的多行模型卡由独立 ngspice 命令行重新加载并扫描 6030 点，正常退出；与冻结预测的最大差异：Id {read_json(out/'verification.json')['max_id_difference_A']:.3g} A，gm {read_json(out/'verification.json')['max_gm_difference_S']:.3g} S。训练/测试点不重叠及安全差分模板检查均通过。

{replay_note}

归一化位置距边界小于 1% 的参数：{', '.join(qa['near_bound_parameters']) or '无'}。边界命中提示范围限制或参数耦合，需要后续补充数据核查，不能把本次参数当作唯一物理解。

完整检查见 `results/local_qa.json`，参数逐项表见 `results/parameter_review.csv`。局部检查包含有限值、参数界限、Id/gm 容差及温升量级；这不是官方 QA_pass_rate。未利用单温 DC 数据去宣称验证电容、射频、陷阱动态、击穿、热时间常数或独立栅漏电模型。

## 交付物

- `curve_preview.html`：曲线、测试散点、残差分布、优化记录。
- `models/fitted_model.lib`、`models/fitted_parameters.json`：可复用模型卡与参数；`asmhemt.va/.osdi`：原始源码与本机编译件。
- `data/train.csv`、`data/test.csv`、manifest：原始标签与点 ID 可追溯。
- `results/train_predictions.csv`、`test_predictions.csv`：逐点实测、拟合前后预测。
- `results/fit_protocol.json`、`freeze.json`、`test_evaluation.json`、优化日志：协议、冻结证据与指标。
- `run.ps1`、`src/`、`requirements.txt`：复跑入口与实现。

## 下一阶段缺口

1. 官方 MeQLab / Primarius MCP 地址、鉴权方式、工具 schema、官方 ASM 版本及参数卡格式仍缺失；本项目未调用官方 MCP，未调用国内 LLM，也不等同于完整参赛 Agent。
2. 需要额外独立器件或整条留出曲线检验泛化，并获得温度、栅电流、C–V/S 参数和动态测量，分别约束热、漏电、电荷与陷阱参数。
3. 待官方接口就绪后，先做 ASM 版本/单位/几何映射与相同参数卡的仿真对齐，再将本地状态流程接到官方工具；正式评分以官方规则和官方隐藏测试为准。

工具来源：[ngspice 47 官方发行目录](https://sourceforge.net/projects/ngspice/files/ng-spice-rework/47/)、[OpenVAF 官方下载页](https://openvaf.github.io/download/)。源数据和模型保留原有版权声明，作者仓库 MIT 文本见 `THIRD_PARTY_LICENSE.txt`。
'''
(ROOT/'validation_report.md').write_text(report,encoding='utf-8')
cards=[]
for j,name,unit in [('id_A','Id','mA'),('gm_S','gm','mS')]:
    v=m['test']['after'][j];cards.append(f'<div class="card"><b>原始留出集 {name}</b><strong>{v["rmse"]*1000:.3f} {unit}</strong><span>RMSE · 极差归一化 {v["nrmse_by_observed_range"]*100:.2f}%</span></div>')
imgs=''.join(f'<section><img src="data:image/png;base64,{base64.b64encode(p.read_bytes()).decode()}" alt="{p.stem}"></section>' for p in [figs/'curve_comparison.png',figs/'heldout_parity.png',figs/'residual_map.png',figs/'optimization_trace.png'])
page=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>ASM-HEMT 直流基线验证</title><style>body{{font:16px/1.65 system-ui,sans-serif;background:#f2f5f9;color:#15233b;margin:auto;max-width:1250px;padding:32px}}h1{{margin-bottom:0}}.sub{{color:#5b6b80}}.cards{{display:flex;gap:18px;margin:25px 0}}.card,section,details{{background:white;border-radius:14px;padding:20px;box-shadow:0 3px 16px #1428400a}}.card{{flex:1}}.card strong{{display:block;font-size:32px;color:#175b9b}}.card span{{color:#5b6b80}}section{{margin:22px 0}}img{{width:100%;height:auto}}pre{{white-space:pre-wrap;font:14px/1.8 system-ui}}a{{color:#175b9b}}</style><h1>DFO_4x50 · ASM-HEMT 直流基线</h1><p class="sub">真实模型仿真与参数提取 · 4824 个训练点 / 1206 个独立测试点 · 模型已冻结</p><div class="cards">{''.join(cards)}</div><p>曲线图显示整个偏置网格；独立测试散点仅包含原始留出点。电流单位为整个器件的 A，未除以栅宽。</p>{imgs}<details><summary>展开完整验证说明</summary><pre>{html.escape(report)}</pre></details><p><a href="validation_report.md">验证报告</a> · <a href="results/test_predictions.csv">测试逐点结果</a> · <a href="results/parameter_review.csv">参数检查表</a></p></html>'''
(ROOT/'curve_preview.html').write_text(page,encoding='utf-8')
page=page.replace('4824 个训练点 / 1206 个独立测试点','4824 个训练点 / 1206 个原始留出点').replace('独立测试散点仅包含原始留出点','测试散点仅包含原始留出点')
page=page.replace('<p>曲线图显示整个偏置网格；','<p>最终训练已排除跨集合 gm 差分目标；早期协议曾查看同一测试集，审计过程见完整说明。</p><p>曲线图显示整个偏置网格；')
(ROOT/'curve_preview.html').write_text(page,encoding='utf-8')
write_json(ROOT/'results/environment.json',{'python':sys.version,'platform':platform.platform(),'numpy':np.__version__,'scipy':scipy.__version__,'matplotlib':matplotlib.__version__,'ngspice':'47 Windows x64','openvaf':'22.12.0'})
print('Report and four figures generated.')
