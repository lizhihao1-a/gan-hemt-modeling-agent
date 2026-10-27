# PMMS 连接工程

请按 [本地部署说明](../../docs/MEQLAB_SETUP.md) 填写忽略的 `config.local.json` 并设置当前终端授权。`run.ps1 -Mode discover` 只启动并发现能力；`-Mode acceptance` 使用配套的最小 MOS 模型和 33 点数据验证参数扰动与模型卡跨会话重放。

原运行摘要位于 [reports/meqlab/internal_mos_acceptance.json](../../reports/meqlab/internal_mos_acceptance.json)。这不是 GaN 拟合结果。`session_host.py` / `submit_request.py` 提供文件队列，`--help` 可查看参数；所有会话输出仅保留本地。

客户端已增加环境变量授权支持，以及导出目录边界检查。导出路径必须是当前运行目录内的新建/空子目录，因为官方 `save_sim_result` 会删除目录后重新写出。
