# 本地 Agent 运行验收

- workflow_complete: True
- all_input_and_completed_artifact_hashes_pass: True
- resume_did_not_repeat_completed_stages: True
- test_targets_only_opened_after_freeze: True
- three_curve_folds_use_training_domain_only: True
- all_4824_training_rows_validated_once: True
- independent_model_card_pass: True
- local_final_model_qa_pass: True
- no_fabricated_official_or_llm_calls: True
- previous_frozen_baseline_unchanged: True
- each_real_simulation_attempt_has_result: True
- pipeline_has_no_injected_faults: True
- backend_failure_recovery_tests_pass: True

真实流水线仿真尝试 4926 次，失败 0 次。故障注入测试另行隔离记录，不混入流水线统计。官方 MCP 与国内 LLM 调用均为 0。
