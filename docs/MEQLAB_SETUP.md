# MeQLab / PMMS 本地部署

已测试的软件是 Windows MeQLab 1.26.2（261022 分发包）及包内配套 PMMS。软件、官方 asmhemtdemo 和授权从比赛渠道分别获取，不随此仓库上传。不同队友使用各自合法授权，不把服务器地址或许可证提交到 Git。

## 连接

1. 解压 Windows 包，保留完整目录结构；确认 MeQLab 可执行文件和 `pmms.exe` 存在。
2. 在当前终端设置比赛提供的 `PRIMARIUS_LICENSE_FILE`。也可以在忽略的本地配置中填写 `license_document`，客户端仅将解析结果传给它启动的子进程。
3. 复制 `outputs/MeQLab_Local_Integration/config.example.json` 为同目录 `config.local.json`，填写本机绝对路径。`runtime_root` 使用新建的专用工作目录；`project_path` 使用测试项目。
4. 从仓库根目录运行：

```powershell
.\outputs\MeQLab_Local_Integration\run.ps1 -Mode discover -Python python
```

工具发现通过后可运行 `-Mode acceptance`；脚本只使用诊断 MOS，创建独立工程和导出目录，结果不计为 GaN 拟合验收。配套控制数据/模型卡位于 `assets/`。

`pmms_client.py` 通过标准输入输出执行官方 MCP；当前测得 49 个工具、6 个资源、6 个提示模板。每次启动都重新发现能力，不依赖旧文档的 40 工具计数。业务失败可能出现在文本而 `isError=false`，客户端已识别中文错误前缀。仿真成功还必须检查导出数值有限且随参数改变，不能只看成功文字。

## 官方 demo

复制 `outputs/MeQLab_Official_Demo_Integration/config.demo.example.json` 为 `config.demo.local.json`。将官方压缩包解压为：

```text
<runtime_root>/official_demo/pristine/asmhemtdemo/
    asmhemt.va
    GaN_full.lib
    BestFittingProject/
```

保留 pristine 原件。脚本每次复制到新的运行名目录，仅修改工作副本中的模型路径。已收到的 demo ZIP SHA-256 为 `01d9fab6f24057c614b3416401f12545a62efaecbde1b03fee3a86f27c130a82`，该 demo 使用 ASM-HEMT 101.0.0；本地 DFO 基线使用 101.4.0，两者不能混用模型卡。

```powershell
python outputs/MeQLab_Official_Demo_Integration/probe_demo.py --name teammate_first_probe
```

运行名必须唯一。当前本机预期仍会出现 NaN，这是待修复阻碍。`diagnose_control.py` 提供 MOS Nano/Internal 对照与保存验证。`diagnose_nano_transport.py` 的插桩选项为排查用途，需要额外 JDK 编译；默认流程不启用它。

## 保存绕行

将以下内容写成独立 `.ini`，通过官方 `build_filter_by_template` 的 `filter_template_path` 传入绝对路径：

```ini
Prepare
com.platformda.extraction.processor.ProjectSetup.getCurrentProject().save(true);
End
```

直接 `save_current_project` 使用缓存视图列表，在本机触发空值；上述分支收集当前视图后保存。已两次验证参数恢复，尚未验证有效 GaN 曲线恢复。

## 本地文件规则

- `save_sim_result.path` 是导出**目录**，官方实现会删除该目录后重建。客户端只接受专用结果目录内的新建/空目录，拒绝覆盖现有文件，避免误删工程。
- 同一会话顺序调用；写操作超时后先确认实际状态，不能盲目重放。会话队列使用唯一请求 ID。
- PMMS、原生仿真及应用日志可能含授权信息。日志保留在忽略的结果目录，提交前只提取脱敏摘要。
- Q&A 的 A14/A17/A47 允许在并行 Nano 正常时忽略缺少单路许可：GUI 取消 Single Nano，保留 Parallel Nano。该设置仍需通过有限数值验证，不能以授权检出代替仿真验收。
