# StateBench 审计

这 80 题是受控模板实例，不是 80 种独立任务类型。
题数不表示有 80 种决策结构。下面列出冻结测试集里结构五元组完全相同的蓝图。

## 状态

| 项目 | 状态 |
| --- | --- |
| Schema 与文件完整性 | PASS |
| 重置与事件注入 | PASS |
| 评分器自动测试 | PASS |
| 人工任务语义复核 | PENDING |

人工任务语义复核保持 PENDING。能加载、哈希相符、自动评分通过，都不表示题意和评分已经被人工确认。

## 冻结测试集中的结构重复

- family_id=note:none, domain=note, goal_structure=copy_final_source_to_target, dependency_structure=read_then_write, event_type=none, constraint_type=single_target: bp_s0_note_5, bp_s0_note_9
- family_id=note:source_notified, domain=note, goal_structure=copy_final_source_to_target, dependency_structure=read_then_write, event_type=source_notified, constraint_type=single_target: bp_s1_note_5, bp_s1_note_9
- family_id=note:unrelated_notified, domain=note, goal_structure=copy_final_source_to_target, dependency_structure=read_then_write, event_type=unrelated_notified, constraint_type=single_target: bp_s2_note_5, bp_s2_note_9
- family_id=note:source_silent, domain=note, goal_structure=copy_final_source_to_target, dependency_structure=read_then_write, event_type=source_silent, constraint_type=single_target: bp_s3_note_5, bp_s3_note_9

## 机器检查

Schema：通过。
重置与事件：通过。
评分器：通过。
