# D4–D7 正确性记录

这是计划、前置条件、观察历史和通知作用域的确定性检查，不是任务成功率。

验收命令：

```text
python -m unittest tests.algorithm.test_invariants tests.algorithm.test_d4_d7 tests.algorithm.test_d4_d7_flow -v
```

结果：38 项通过。其中原有不变量 13 项保持通过，D4–D7 单点与跨模块演练 25 项通过。

## 编译

24 条开发题都先经过公开任务视图，再编译成 `read` 然后 `write`。来源均为 `structured_task_compilation`。`write` 依赖 `read`，引用 `ev:{source_key}`，参数只保留 `value_from`，不写入 `15:00` 或 `16:00`。

公开视图允许的键是 `task_id`、`prompt`、`source_key`、`target_key`、`readable`、`writable`、`goal_structure`、`dependency_structure`。带有 `events`、`initial_facts`、`success`、`constraints` 或 `environment_event` 的原始任务会在读取这些值之前被拒绝。`s1_meeting_a` 的公开计划序列化结果不包含隐藏值 `16:00`。同一公开视图重复编译，节点、依赖和序列化结果一致。

`compile_oracle_fixture` 只在测试辅助里把同一编译器的结果标成 `oracle_fixture`。`agent/algorithms/controller.py`、`evals/statebench/b0.py` 和 `evals/statebench/runner.py` 都不引用它。

图错误按固定顺序返回：

| 输入 | 结果 |
| --- | --- |
| 重复 id、自依赖、悬空依赖、不受支持的动作 | `PLAN_INVALID` |
| 两个及以上不同节点构成的有向环 | `PLAN_CYCLE` |
| 全部节点 `DONE` 且目标未验证 | `STOP / GOAL_UNVERIFIED` |
| 目标已验证且没有未确认的相关或未知作用域通知 | `STOP / GOAL_MET` |

## 前置条件

| 引用 | 结果 |
| --- | --- |
| 没有 `requires_evidence` | `VALID` |
| 全部 `VALID` | `VALID` |
| 任一 `INVALID` | `INVALID` |
| `INVALID` 与 `UNKNOWN` 同时存在 | `INVALID` |
| 缺失、`UNKNOWN` 或 `SUPERSEDED` | `UNKNOWN` |
| `VALID` 与 `SUPERSEDED` 同时存在 | `UNKNOWN` |

`UNKNOWN` 进入 `OBSERVE / MISSING_EVIDENCE`，并写明事实键。`INVALID` 进入既有阻塞或重规划，不 `CONTINUE`。未确认的相关通知和未知作用域通知先于 `GOAL_MET`。

## 观察历史

`v1 -> v2 -> v3` 之后，当前槽位是 `v3 / VALID`，历史保留 `SUPERSEDED:v1`、`SUPERSEDED:v2`、`VALID:v3`。相同 `observed_at` 得到两个观察号。后到的 `v1` 不能覆盖当前 `v2`，当前槽位已经是 `INVALID` 时也不能把旧观察恢复成 `VALID`。同一 `source_version` 的不同值记为冲突，当前槽位不动，新记录归档为 `UNKNOWN`。无法比较的普通版本字符串不替换当前槽位。其他事实键的观察不改变当前事实。

已替代的旧值不能使信念侧目标成立。`resolve_args` 只在当前证据为 `VALID` 时取值。

## 通知分类

计划使用 `meeting.time` 时：

| 通知键 | 关系 | 待处理节点 | 证据 |
| --- | --- | --- | --- |
| `meeting.time` | `relevant` | `write` | 保持 `VALID` |
| `meeting.room` | `unrelated` | 空 | 保持 `VALID` |
| `meeting` | `unknown` | 复查 `write`，观察 `meeting.time` | 保持 `VALID` |
| `meeting.time.zone` | `unknown` | 复查具体事实 | 不改为 `INVALID` |
| `note.tag` | `unrelated` | 空 | 保持 `VALID` |

`A(DONE) -> B(DONE) -> C(PENDING)` 的可达集合是 `a, b, c`。去掉 `DONE` 之后只剩 `c`。待处理集合属于这个差集。

成功写入不旧于通知的当前 `VALID` 证据后，调用方确认通知，下一次决策不再因同一通知观察。观察没有更新当前槽位时，确认条件不成立，下一次仍是同一条观察决策。`decide` 不修改信念，也不在内部确认通知。未投递的隐藏变化不进入信念。

## 三条轨迹

相关变化：`meeting.time` 当前为 `v1 = 15:00`，`read` 已完成，`write` 未执行。通知 `meeting.time` 后，决策是 `OBSERVE / FACT_CHANGED`，观察键是 `meeting.time`，目标节点是 `write`，证据仍是 `VALID`。注入 `v2 = 16:00` 后，`v1` 归档为 `SUPERSEDED`，当前证据成为 `v2`。确认通知后决策是 `CONTINUE`，`resolve_args` 取到 `16:00`。

无关变化：计划依赖 `meeting.time`，通知是 `meeting.room`。关系是 `unrelated`，`write` 不在影响集合里，证据保持 `VALID`，决策继续。

未知作用域：计划依赖 `meeting.time`，通知是 `meeting`。关系是 `unknown`，决策是 `OBSERVE / UNKNOWN_SCOPE`，复查 `meeting.time` 和未执行的 `write`。影响集合为空，新观察到达前不把证据改成 `INVALID`。

## 非 Oracle 与回归

输出不依赖隐藏事件、初始真值和评分答案。较旧观察不能覆盖较新的当前槽位。已确认通知不会再次产生同一条观察决策。全部节点完成不等于 `GOAL_MET`。原有 INV-01 到 INV-10 的判定没有改写，13 项不变量测试通过。算法包没有引入 channel、OneBot 或 statebench。
