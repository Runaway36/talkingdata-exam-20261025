# 实际验收记录

日期：2026-10-25（北京时间）。本页记录请求次数口径 v2 的真实运行，非预期结果或模型评分。

## 本地 Python

- Windows，Python 3.13.5，新建项目虚拟环境，`pip install -r requirements.txt` 成功；运行无第三方依赖。
- `python scripts/validate.py` 退出码 0。
- `python -m unittest discover -s tests -v`：**41/41 通过**。
- seeds 17、42、99：API 参考解各执行 5 次必要查询，独立验证器奖励均为 **1.0**，且数值答案不同。
- 三个种子的“错误数量＋错误排序”样例奖励均为 **0.6944444444444444**；空答案均为 **0.0**。
- Harness 调用示例退出码 0，奖励 **1.0**。

机器证据：[汇总 JSON](../artifacts/validation-20261025T102742175050Z/summary.json)、[测试原始输出](../artifacts/validation-20261025T102742175050Z/unit-tests.stderr.txt)、[默认任务完整调用与评分](../artifacts/validation-20261025T102742175050Z/demo-17.json)。

| seed | AUTH / DB / PAY 异常失败请求数 | priority |
| --- | --- | --- |
| 17 | 48 / 174 / 120 | INC-DB, INC-PAY |
| 42 | 48 / 171 / 175 | INC-PAY, INC-DB |
| 99 | 53 / 140 / 212 | INC-PAY, INC-DB |

## Docker 与挂载

Docker Desktop Linux/amd64，Engine 29.7.2，镜像基于 python:3.13-slim。

实际构建：`docker build --progress=plain -t talkingdata-alert-rlvr:exam-v2 .`，退出码 0。后续测试均设置：

```text
--network none --cpus 1 --memory 256m --read-only --tmpfs /tmp:rw,nosuid,size=16m
```

| 验收路径 | 实测结果 | 证据 |
| --- | --- | --- |
| 容器默认启动 | 自动运行样例：正确 1、错误约 0.6944、空答案 0 | [输出](../artifacts/docker-default-v2.json) |
| 容器测试套件 | 41 项通过，退出码 0 | [测试输出](../artifacts/docker-tests-v2.txt) |
| 本地 examples 目录只读挂载为 /workspace | 外部脚本直接导入镜像内模块，seed=42 reward=1 | [挂载输出](../artifacts/docker-mounted-controller-v2.json) |
| 镜像构建 | 成功，无手工数据准备 | [构建日志](../artifacts/docker-build-v2.txt) |

这些运行证明本任务在上述限制下可执行，不构成大规模吞吐量或任意资源条件的性能承诺。

## 有针对性的验证

独立手算 fixture 验证去重、生产环境筛选、基线取整与零下限、完整/部分/取消维护、时间边界、同计数排序规则及预期异常量，不以参考解自身输出充当唯一正确答案。

反事实测试分别改变事件服务关联、服务资料、业务指标和维护记录，确认保持其他数据不变时，旧答案失去满分。这证明相应 API 数据在业务上必要。

协议反例包括 bool 冒充整数、负数、NaN/Infinity、重复 JSON key、重复事件/服务 ID、错误快照、未知任务、未知字段、非法 API 名称、SQL 注入形状的 ID。等价答案允许明细行和服务列表换序。

测试阶段实际发现并修复两项问题，并加入回归：

1. 工具请求 ID 含孤立 Unicode 代理字符时，JSONL 的 UTF-8 输出可能中断；响应改为 JSON Unicode 转义，下一请求仍能处理。
2. 只按“窗口相交＋firing”筛选可能把截止前结束的告警带入参考解，错误提升事件等级；增加截止时仍活动条件，与业务规则一致。

## 证据边界

尚未运行真实大模型、批量 rollout 或 RL 训练。不能由样例满分推断模型成功率、挑战难度或训练收益。该版本覆盖单一合成场景及有限边界用例，不保证覆盖所有真实运维情况。Python 私有属性和单容器不是任意代码攻击下的安全隔离；训练方应只向模型注册业务 API。
