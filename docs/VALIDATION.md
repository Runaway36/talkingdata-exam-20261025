# 实际验收记录

日期：2026-10-25（北京时间）。当前交付版本为 v3。下列是实际执行结果；后半部分保留 v2 历史记录。

## 最终兼容加固：60项测试

模型评测后按最终审阅修复了桶长配置与可信评分故障分流，默认任务输入和答案不变。最终本地60/60、Docker60/60、默认正确/错误/空样例1/0.4/0、只读挂载reward1均通过。见[最终加固说明](FINAL_HARDENING.md)、[本地汇总](../artifacts/final-hardening-20261025/local/summary.json)、[Docker汇总](../artifacts/container-validation-20261025T115153289433Z/summary.json)。下述51项及模型评测保留其原始版本与时间；新旧源码指纹没有混用。

## 当前 v3：修改与验证

固定数据和业务统计口径不变。奖励改为完整事件与有正确分析支撑的优先级计分；题面去掉所需 API 清单，保留全部统计规则，并公开格式违规条件。新版任务与答案标识为 `alert-impact-v3-seed-*`，旧任务文本不能按新规则评分。

| 业务对照 | v2 | v3 |
| --- | ---: | ---: |
| 完整正确 | 1 | 1 |
| 三个异常数量全部错误，其他字段及排名正确 | 0.833333 | 0 |
| 完整正确但多报一个事件 | 0.964286 | 0.833333 |
| 默认示例：一个非优先事件数量错误且两项排名反序 | 0.694444 | 0.4 |
| 空答案（真值非空） | 0 | 0 |

v3 的部分奖励衡量完整业务结果的完成情况：优先事件完整正确且位置正确可以获得两个单位。数值只差 1 和差很多都属于该事件未完成；它不衡量数值误差大小。

- 本地 `python scripts/validate.py`：退出码 0，**51/51 测试通过**。seed 17、42、99 的参考解均得 1；错误样例均得 0.4；空答案均得 0；Harness 样例得 1。
- Docker `python scripts/validate_container.py`：构建、默认启动、51 项测试、只读挂载脚本调用全部通过。镜像 `talkingdata-alert-rlvr:exam-v3`；运行使用禁网、1 CPU、256 MiB 内存及只读文件系统。
- 独立静态复核确认新公式的满分条件、空真值、误报和排名依赖边界；补充题面的格式约束后重新完成上述验证。

机器证据：[v3 本地汇总](../artifacts/validation-20261025T111622025933Z/summary.json)、[v3 测试原始输出](../artifacts/validation-20261025T111622025933Z/unit-tests.stderr.txt)、[v3 默认样例](../artifacts/validation-20261025T111622025933Z/demo-17.json)、[v3 Docker 汇总](../artifacts/container-validation-20261025T111622006031Z/summary.json)。

双路红队随后发现输入大小限制未公开及整数值 JSON 表示歧义，现已公开限制并采用精确十进制解析。新增回归覆盖大小边界、等价表示和极小非零小数。原始审计与修复后复核见[红队记录](../artifacts/redteam-v3/README.md)。

以上程序性验收验证实现与既定规则，单独不构成模型难度证据。随后已完成冻结 v3 的真实模型评测，见[最终评测报告](../artifacts/model-eval-final/report.md)：

- DeepSeek 非思考模式和 Qwen2.5-1.5B-Instruct 各3实例×4次，合计24次全部正常执行，无基础设施错误，严格 pass@1/pass@4 均为0。
- Qwen 11次交final：5次合法错答、6次格式违规；另1次预算内未交final，原始reward=null保留。完整率与逐事件差异见[Qwen运行记录](../artifacts/model-eval-final/qwen25-15b-run01/run-notes.md)。
- 两个独立新上下文 GPT/Codex sub-agent 分别通过5次业务API取得数据，均独立解对seed17并得1，构成该实例可解证据，不代表与其他Harness公平对齐的排名。
- DeepSeek 思考模式、4096 token/轮的补充诊断仅对seed17独立4次，reward为0、1、0、0；三条失败分别有1、2、3次截断。该条件单列，不并入原1024 token批次。
- 真实模型答案没有非零非满分奖励；主要评测按严格0/1成功报告，未验证连续奖励的表现排序效度。程序构造的部分分用例只验证公式。

红队及最终独立核查另覆盖全部10,000个内置seed核算、2,535个答案变异和协议边界，范围与限制见[最终独立核查](../artifacts/model-eval-final/independent-audit-final.md)。原始网络和Qwen运行异常未在本轮复现；Qwen旧错误缺失真实诊断，不能声称已确认根因。v2 真实模型试跑见[历史评测记录](../artifacts/model-pilot-v2/README.md)，不混入 v3 分母；尚未实施RL训练。

## v2 历史记录

以下记录对应 v2 当时的版本与验证范围，原始产物保留不变。

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

在上述 v2 程序验收时点，尚未运行真实大模型、批量 rollout 或 RL 训练；其后完成的 v2 模型试跑已另存历史评测记录。不能由样例满分推断模型成功率、挑战难度或训练收益。该版本覆盖单一合成场景及有限边界用例，不保证覆盖所有真实运维情况。Python 私有属性和单容器不是任意代码攻击下的安全隔离；训练方应只向模型注册业务 API。
