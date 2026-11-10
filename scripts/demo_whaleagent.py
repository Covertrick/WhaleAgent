"""本地演示。不调用模型，也不连接 QQ。"""

from __future__ import annotations

from evals.statebench.reliability import run_matrix, summarize
from evals.statebench.v3.catalog import all_tasks
from evals.statebench.v3.world import play, score
from agent.application.conditional_write import WritePreconditions, judge_write


def main() -> None:
    task = next(item for item in all_tasks() if item["task_id"] == "s1_parallel_clock_v1")
    print("1 用户目标")
    print(task["public_goal"])
    print("2 计划来自本地校验过的依赖，不是这次进程里的模型输出")
    print("draft <- notes ; reminder <- clock ; clock 在第一次阅读后变化")
    correct = score(task, play(task, "correct"))
    stale = score(task, play(task, "wrong"))
    print("3 重新读取后的评分", "success" if correct["success"] else "fail", "checkpoint", correct["checkpoint_reached"])
    print("4 错误正文加 1999 时间", "success" if stale["success"] else "fail", "reasons", ",".join(stale["failure_reasons"]))
    verdict = judge_write(
        WritePreconditions("v1", "v2", "t1", "t1", cross_system=False)
    )
    print("5 来源在读取后变化", verdict)
    residual = judge_write(
        WritePreconditions("v1", "v1", "t1", "t1", cross_system=True, commit_window_changed=True)
    )
    print("6 Vault 与调度器之间的剩余竞态", residual)
    report = summarize(run_matrix())
    print("7 故障注入", report["scenarios"], "次；重复不可逆", report["duplicate_irreversible"])
    print("8 回执路径 STARTED -> dispatch -> UNKNOWN -> 按 operation_id 查询 -> 确认或停止")
    print("9 测试集", "已开封", "review", "developer_reviewed", "third_party", "no")


if __name__ == "__main__":
    main()
