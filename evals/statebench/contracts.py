"""评分契约和检查点契约。文本一变，旧冻结清单就不再是同一协议。"""

from __future__ import annotations

from evals.statebench.hashing import sha256_text

SCORING_CONTRACT = """\
statebench-scoring-v1
assertions:
- equals_fact: 左侧事实的最终真值等于右侧事实的最终真值
- equals_literal: 事实的最终真值等于给定字面量
- exists: 事实键存在
- count_equals: 该键的成功写入次数等于给定计数
false_invalidations: 没有失效判定日志时返回 not_applicable，不把未调用失效动作记成 0
provenance_unknown: 来源对不上时单独记录，不判成有效，也不判成失效
stale_source_writes 与 wrong_final_values 分开计数
评分输入包含来源版本、目标写入和检查点是否到达
"""

CHECKPOINT_CONTRACT = """\
statebench-checkpoint-v1
trigger: 第一次成功读到来源事实之后，本轮工具批结束
apply: 下一次决策之前更新真值；没读到来源则不提前改真值，并记 checkpoint_reached=false
notification: type=state_change_notification, fact_key, change_detected=true, new_value=null
notify=false: 不注入消息；评分器仍能看见新版本
同一轮不能既读取来源，又提交依赖该读取的写入并跨过检查点
"""

CHECKPOINT_NAME = "after_first_source_read"
TRACE_SCHEMA = "statebench-trace-v1"
MANIFEST_SCHEMA = "statebench-v1"


def scoring_contract_sha256() -> str:
    return sha256_text(SCORING_CONTRACT)


def checkpoint_contract_sha256() -> str:
    return sha256_text(CHECKPOINT_CONTRACT)
