# 统计

配对聚类 Bootstrap 的实现在 `evals/statebench/v3/statistics.py`。自检用 200 次重抽样和一份构造数据：EGAA 的观察次数少于 Always Refresh，区间上界小于 0。种子是 20261110。

这不是 v3 实验。真实对照没有样本，成功率差、费用差和每成功成本都未定义。样本不足时不能把「没有跑」写成非劣。
