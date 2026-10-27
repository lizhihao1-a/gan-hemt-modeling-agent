"""Scientific figures and a self-contained local review page."""
import csv,base64,html,sys
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from common import *
from config import ACTIVE

def render(root,out):
    result=root/'results';out.mkdir(parents=True,exist_ok=True)
    d=read_json(result/'diagnostics/diagnostics.json');cv=read_json(result/'curve_validation/curve_cv.json')
    f=read_json(result/'agent/freeze.json');ev=read_json(result/'verification/test_metrics.json')
    decision=read_json(result/'agent/decision.json');protocol=read_json(root/'protocol.json')
    plt.rcParams.update({'font.size':10,'axes.grid':True,'grid.alpha':.18,'figure.dpi':135})
    rows=sorted(d['parameters'],key=lambda r:r['rms_sensitivity'])
    fig,ax=plt.subplots(figsize=(10,7.5),layout='constrained')
    ax.barh([r['parameter'] for r in rows],[max(r['rms_sensitivity'],1e-12) for r in rows],color=['#db6d44' if r['near_bound'] else '#397eb1' for r in rows])
    ax.set_xscale('log');ax.set(xlabel='RMS residual derivative / normalized parameter range',title='Local sensitivity at the frozen baseline (orange = near search bound)')
    fig.savefig(out/'sensitivity.png');plt.close(fig)
    z=np.load(result/'diagnostics/jacobian.npz');fig,axs=plt.subplots(1,2,figsize=(15,7),layout='constrained')
    im=axs[0].imshow(abs(z['cosines']),vmin=0,vmax=1,cmap='magma');fig.colorbar(im,ax=axs[0],shrink=.65)
    axs[0].set_xticks(range(23),ACTIVE,rotation=90,fontsize=8);axs[0].set_yticks(range(23),ACTIVE,fontsize=8);axs[0].set_title('Absolute derivative cosine (coupling heuristic)')
    s=z['singular_values'];axs[1].semilogy(range(1,24),s/s[0],'o-');axs[1].axhline(1e-6,color='red',ls='--')
    axs[1].set(title='Local Jacobian singular spectrum',xlabel='Singular value index',ylabel='s / s_max')
    fig.savefig(out/'coupling_spectrum.png');plt.close(fig)
    fig,axs=plt.subplots(1,2,figsize=(13,4.5),layout='constrained')
    for name in dict.fromkeys(p['parameter'] for p in d['inward_perturbations']):
        ps=[p for p in d['inward_perturbations'] if p['parameter']==name]
        axs[0].plot([0]+[p['inward_fraction_of_range'] for p in ps],[0]+[p['cost_change_fraction']*100 for p in ps],'.-',label=name)
    axs[0].set(xlabel='Move inward / published range',ylabel='Training robust cost change (%)',title='One-parameter inward perturbations (no refit)');axs[0].legend(fontsize=7,ncol=2)
    colors=['#397eb1','#db6d44','#6a9b6c']
    axs[1].bar([f'Fold {r["fold"]}' for r in cv['folds']],[r['id_and_full_gm_metrics']['id_A']['nrmse_train_range']*100 for r in cv['folds']],color=colors)
    axs[1].set(title='Contiguous Vgs group validation',ylabel='Held-group Id RMSE / fit Id range (%)')
    fig.savefig(out/'bounds_curve_validation.png');plt.close(fig)
    train,ti,ty=load_data(root/'data/train.csv');test,ei,ey=load_data(root/'data/test.csv')
    measured=np.empty((6030,2));measured[ti]=ty;measured[ei]=ey
    prediction=np.load(result/'agent/frozen_prediction.npz')['prediction'];vg=np.round(np.arange(-3,0,.1),1);vd=np.arange(201)*.1
    fig,axs=plt.subplots(1,2,figsize=(13,5),layout='constrained')
    for g,c in zip([5,10,15,20,24,27,29],plt.cm.viridis(np.linspace(0,1,7))):
        ix=np.arange(g*201,(g+1)*201);axs[0].plot(vd,measured[ix,0]*1000,'.',color=c,ms=2)
        axs[0].plot(vd,prediction[ix,0]*1000,color=c,label=f'Vgs={vg[g]:.1f} V')
    axs[0].set(title='Final rule-agent model (dots = measured)',xlabel='Vds (V)',ylabel='Id (mA)');axs[0].legend(fontsize=8,ncol=2)
    axs[1].scatter(ey[:,0]*1000,prediction[ei,0]*1000,s=6,alpha=.4)
    axs[1].plot([0,160],[0,160],'k--');axs[1].set(title='Previously viewed author test split',xlabel='Measured Id (mA)',ylabel='Predicted Id (mA)')
    fig.savefig(out/'agent_curves.png');plt.close(fig)
    events=[read_json_line for read_json_line in [__import__('json').loads(s) for s in (result/'events.jsonl').read_text(encoding='utf-8').splitlines()]]
    call_count=sum(e['event']=='tool_call' for e in events);failed=sum(e['event']=='tool_result' and not e['ok'] for e in events)
    cvtable='\n'.join(f"|{r['fold']}|{r['held_out_curve_indices'][0]}–{r['held_out_curve_indices'][-1]}|{r['fit_points']} / {r['validation_points']}|{r['id_and_full_gm_metrics']['id_A']['rmse']*1000:.3f}|{r['id_and_full_gm_metrics']['id_A']['nrmse_train_range']*100:.2f}%|{r['safe_validation_gm']}|{r['status']}|" for r in cv['folds'])
    pairs='；'.join(f"{p['a']} / {p['b']} ({p['absolute_derivative_cosine']:.4f})" for p in d['high_coupling_pairs'][:5]) or '本阈值下无'
    bounds=[r['parameter'] for r in d['parameters'] if r['near_bound']]
    metrics=ev['metrics']['test'];idmet=metrics['full_metrics']['id_A'];gmmet=metrics['safe_gm_metrics']
    text=f'''# GaN HEMT 本地建模 Agent 验收报告

本地规则状态机已完成参数诊断、按 Vgs 连续区间分组交叉验证、候选拟合与选择、全训练集重拟合、冻结导出、独立模型卡仿真和冻结后的回归评估。

## 参数诊断

只使用作者原始 4824 个训练点，其中安全 gm 目标 {d['safe_gm_targets']} 个，在上一版冻结参数处进行局部差分。23 参数 Jacobian 在相对奇异值阈值 1e−6 下数值秩为 **{d['numerical_rank']}/23**；条件数约 {d['condition_number']:.3g}。这是归一化残差与参数范围下的局部数值诊断，不能解释为统计置信区间、全局可辨识性或唯一物理解。

接近公开范围边界的 {len(bounds)} 个参数：{', '.join(bounds)}。变化步长 0.003 和 0.001 均在原范围内，边界处使用单边差分。单参数向内移动 2%、5%、10% 的代价变化见图；没有扩大范围，也没有在每次扰动后重拟合其他参数。

较强导数耦合（绝对余弦 >0.98）示例：{pairs}。参数敏感性、步长一致性、所有耦合对和弱方向组合均保存在 diagnostics.json / parameter_sensitivity.csv / jacobian.npz。弱参数与耦合参数需靠独立温度、栅漏电或其他测量约束。

## 整条曲线组验证

只在原作者训练域内，将 30 个 Vgs 曲线组分为三个连续区间。每一折从公开范围中点重新拟合全部 23 个参数，未使用旧冻结拟合参数作初值，也未用该折验证目标选择参数范围。每个验证区间的 Vgs 曲线完全不出现在对应拟合区间；可用点仍限于作者训练域，原始 1206 个测试点不参与此步骤。

|折|留出 Vgs 网格组|拟合 / 验证点数|Id RMSE (mA)|Id RMSE / 该折训练极差|安全验证 gm 点|优化器状态|
|---|---|---|---|---|---|---|---|
{cvtable}

低/高 Vgs 区间包含外推，中间区间为跨区间插值；因此比随机留点评估更难。超出预算的折只代表本轮预算下的表现，不能解释为全局最优。gm 目标只在差分所需 Id 点完全属于当前子集时使用。交叉验证用于揭示局限，没有根据其结果扩大边界或调换预算，也不是新的盲测数据。

## Agent 闭环与最终模型

状态流：预检查 → 诊断 → 曲线组验证 → 规则规划 → 参数拟合 → 验证误差与本地 QA → 必要时细化 → 候选选择 → 全训练集重拟合 → QA 回退（如需要）→ 冻结 → 导出验证 → 报告。

先拟合 16 个核心参数；若验证 Id NRMSE 超过 2%、安全 gm NRMSE 超过 5% 或本地 QA 未通过，则在同一训练子集上细化全部 23 个参数。本次规则决策：**{decision['action']}**，原因：{'; '.join(decision['reasons'])}。候选仅用预设 Vgs 组内部验证选择，随后仅用 4824 个训练点重拟合。所有初值来自公开范围中点及同一训练流程，未使用旧最佳参数作为新 Agent 的初值；诊断数据不用于改变交叉验证或候选计划。

最终本地 QA：{f['qa']['passed']}；接近边界的参数：{', '.join(f['qa']['near_bound']) or '无'}。独立命令行读取导出模型卡，6030 点对齐通过，最大 Id 差异 {ev['card_verification']['max_difference_id_A']:.3g} A。

原始留出集 1206 点电流 RMSE **{idmet['rmse']*1000:.3f} mA**；按留出集观测极差归一化 **{idmet['nrmse_own_range']*100:.3f}%**。安全 gm 子集 {metrics['safe_gm_count']} 点，RMSE **{gmmet['rmse']*1000:.3f} mS**。这个测试集在之前阶段已查看，本轮只在冻结后作回归检查，不作为新的盲测或模型选择证据。

当前日志包含 {call_count} 次真实本地仿真尝试，其中失败 {failed} 次。每次均记录参数、操作 ID、尝试号、耗时及结果。SciPy max_nfev 不包含全部数值 Jacobian 仿真，因此预算同时设有真实仿真次数上限和每项作业时间上限。单次仿真超时会终止隔离进程，最多重试一次。

## 恢复和验收

状态、输入/源码校验与阶段产物哈希持久化至 run_state.json。恢复时先验证校验值，跳过已完成阶段；已完成优化作业可以复用，未完成的优化作业按固定初值重新执行，未声称逐迭代无损续算。运行锁防止同一目录同时执行两个控制器。进程崩溃、超时、参数越界、产物篡改、恢复跳过及正式连接器禁用的验证结果见 results/acceptance.json（生成后可查看）。

本地流程验收与模型泛化精度分别报告；“流程完成”不表示所有参数已充分辨识或跨器件准确。

## 官方衔接状态

实际官方 MCP 调用 **0**，国内 LLM 调用 **0**。当前策略是可审计的规则状态机，不能冒充已接入 LLM 的参赛 Agent。官方连接器和 LLM 入口在未配置时明确报错，不返回模拟成功。待提供官方端点、鉴权约定、实际工具 schema、ASM 版本、模型卡/评分格式以及国内模型服务配置后，才能实现并验收对应适配器；未猜测官方工具名称或接口字段。

缺少跨温度、栅电流、C–V、射频和陷阱动态数据，本项目仍仅是 DFO_4x50 单器件、25 °C 模型上下文的 DC 工程闭环。下一轮独立泛化验证需要新的器件或未参与过开发的数据。

技术参考：[SciPy 1.15.3 least_squares](https://docs.scipy.org/doc/scipy-1.15.3/reference/generated/scipy.optimize.least_squares.html)、[SciPy SVD](https://docs.scipy.org/doc/scipy-1.15.3/reference/generated/scipy.linalg.svd.html)、[ngspice 共享库](https://ngspice.sourceforge.io/shared.html)。原始来源、模型版权与工具校验沿用项目 provenance.json 和许可证文件。
'''
    (out/'validation_report.md').write_text(text,encoding='utf-8')
    images=''.join(f'<section><img alt="{name}" src="data:image/png;base64,{base64.b64encode((out/name).read_bytes()).decode()}"></section>' for name in ['sensitivity.png','coupling_spectrum.png','bounds_curve_validation.png','agent_curves.png'])
    page=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>GaN HEMT 本地 Agent 验收</title><style>body{{font:16px/1.7 system-ui,sans-serif;background:#eef3f8;color:#183048;max-width:1250px;margin:auto;padding:30px}}h1{{margin-bottom:0}}.muted{{color:#63778e}}.cards{{display:flex;gap:15px;margin:25px 0}}.card,section,details{{background:white;padding:22px;border-radius:14px}}.card{{flex:1}}strong{{font-size:30px;display:block;color:#176c9c}}img{{width:100%;height:auto}}section{{margin:22px 0}}pre{{white-space:pre-wrap;font:14px/1.8 system-ui}}a{{color:#176c9c}}</style><h1>GaN HEMT · 本地建模 Agent</h1><p class="muted">真实 ASM-HEMT / ngspice · 参数诊断 · 曲线分组验证 · 规则状态机闭环</p><div class="cards"><div class="card">局部数值秩<strong>{d['numerical_rank']} / 23</strong>阈值 1e−6；不代表唯一物理解</div><div class="card">留出电流 RMSE<strong>{idmet['rmse']*1000:.3f} mA</strong>已有测试集上的冻结后回归</div><div class="card">正式平台接入<strong>尚未配置</strong>MCP 0 次 · 国内 LLM 0 次</div></div><p>曲线分组验证与随机留点评估回答不同问题；请结合分组误差、参数耦合与边界诊断判断结果。</p>{images}<details><summary>完整验收报告与局限</summary><pre>{html.escape(text)}</pre></details><p><a href="validation_report.md">完整报告</a> · <a href="../agent/freeze.json">模型冻结记录</a> · <a href="../acceptance.json">运行验收结果</a> · <a href="../../README.md">工程运行说明</a></p></html>'''
    (out/'overview.html').write_text(page,encoding='utf-8')
    atomic_json(out/'report_summary.json',{'local_jacobian_rank':d['numerical_rank'],'diagnostic_bound_count':len(bounds),
        'local_simulation_attempts':call_count,'local_failed_attempts':failed,'test_id_rmse_A':idmet['rmse'],
        'official_mcp_calls':0,'domestic_llm_calls':0,'planner':'deterministic_rules'})
