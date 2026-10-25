# 冻结主批次与附加条件：独立最终审计

**主批次 24 次已全部完成审计。DeepSeek 与 Qwen 均为 0/12 严格通过；当前没有实际中间分，不声称分数能对两者或其错误答案排序。** DeepSeek 12 次都是合法错答；Qwen 5 次合法错答、6 次格式违规、1 次预算耗尽未提交答案。Qwen 的最后一种结果原始 reward 为 null，不是验证器实际打出的 0。

主批次于 **2026-10-25 11:39:09 UTC** 完成核查，**11:41:31 UTC** 补齐附加 DeepSeek 4 次和 GPT 两次的核查，共覆盖 30 次运行，按不同条件分别解释，不合并成一个通过率。保留了之前的 [初审报告](independent-audit.md) 与证据。任务、数据、评分器、阈值及真实模型输出均未修改；本审计没有运行模型或联系 GPT solver。

## 冻结与实际产物完整性

[本次独立证据](independent-audit-evidence-20261025T113909690721Z/run-integrity.json) 由 [只读审计脚本](independent-audit-check.py) 重新读取最终产物生成，重放 API 并重算已有答案，不覆盖旧结果。复现：

```powershell
python -B artifacts/model-eval-final/independent-audit-check.py
```

核验结果：

- 24 次的业务代码哈希均匹配 [frozen-task.json](frozen-task.json)，当前业务源码仍匹配冻结记录。
- 两个批次保存的 Harness/driver 源码哈希也匹配被审文件，没有发现主批次中途换代码。
- 24 次原始题面、system+API schema、逐轮对话历史均一致对应；没有跨 attempt 答案或评分反馈。
- DeepSeek 的 65 次、Qwen 的 15 次已记录工具返回，全部与相应 seed 下新建 API 环境的结果一致，也完整进入后续模型请求。
- 23 份最终答案均保留为模型原文中的原始 JSON 片段；其保存评分与重算评分一致。
- Qwen `seed42-attempt01` 没有最终答案，原始 reward 为 null；检查了其完整 12 轮历史，没有捏造答案文件或补做验证器评分。
- 未发现基础设施执行错误或输出截断。DeepSeek 协议错误为 0；Qwen 有 13 次协议错误，以及 1 次模型请求了不存在的 API，后者是模型工具选择错误。

“全部工具返回一致”不等于“模型每次选择的工具都有效”。Qwen `seed99-attempt02` 请求了不存在的 `business_rules_engine`，环境按白名单返回 `UNKNOWN_API`；该错误响应忠实传回模型，不能归为基础设施故障。

## 主批次统计：按完整完成判据汇报

两批均使用 seed 17、42、99，每个实例 4 次独立新对话，temperature=0.7、最多 12 轮、每轮最多 1024 输出 token。DeepSeek 为 thinking disabled；Qwen 为本地 Qwen2.5-1.5B-Instruct。task seed 与本地 sampling seed 分开，DeepSeek 服务端 sampling seed 不可控。

| 主批次 | 严格通过 | 合法错答 | 格式违规 | 预算耗尽无 final | 运行异常 | pass@1 | pass@4 |
|---|---:|---:|---:|---:|---:|---:|---:|
| DeepSeek flash | 0/12 | 12 | 0 | 0 | 0 | 0 | 0 |
| Qwen2.5-1.5B-Instruct | 0/12 | 5 | 6 | 1 | 0 | 0 | 0 |

这里“严格通过”为 `valid=true && reward=1`。每个实例的 pass@1 是该实例 4 次中的成功比例，pass@4 是这 4 次中是否至少有 1 次成功，再对三个实例等权平均。三个实例在两批中均是 0/4；独立重汇总与各自 [DeepSeek summary](deepseek-flash-run01/summary.json)、[Qwen summary](qwen25-15b-run01/summary.json) 全部一致。

两批保存的 mean_reward 均为 0。对 Qwen，准确口径是：**已有 11 份最终答案得分均为 0；剩余 1 次在预定预算内未答，汇总用 `reward or 0` 将其按 0 纳入尝试均分。** 不能声称 Qwen 的 12 份最终答案都被验证器评了 0，因为实际上只有 11 份最终答案。若发生 `execution_error`，代码会中止批次、保持 complete=false，不进入这样的正式均分；这次没有此类异常。

这些是 3 个固定实例、每个 4 次的实际观测，不是总体通过概率、跨结构泛化或任务内在难度的估计。两个模型都未通过，不能从本批 pass@1/pass@4 或 reward 排出强弱。

## 逐事件核对与错误分类

[独立 API 数据与逐桶真值](independent-audit-evidence-20261025T113909690721Z/independent-truth.json) 不使用评分器 Oracle 生成答案：

| seed | AUTH/P1 | DB/P0 | PAY/P1 | priority |
|---|---:|---:|---:|---|
| 17 | 48 | 174 | 120 | DB、PAY |
| 42 | 48 | 171 | 175 | PAY、DB |
| 99 | 53 | 140 | 212 | PAY、DB |

正贡献服务均为 AUTH→svc-auth，DB→svc-checkout 与 svc-search，PAY→svc-pay。BASE 无正异常、LOG 被完整批准维护覆盖，因此不输出。seed 17 的独立逐桶明细仍为 AUTH `9+11+10+10+8=48`，DB `(36+39+31+37)+(15+16)=174`，PAY `18+18+19+23+22+20=120`。

以下是诊断，不是用同为 0 的 reward 制造质量排名：

1. **DeepSeek seed17-attempt01 与 attempt04**：两份都将 AUTH、DB、PAY 填为 0，多报 BASE/LOG，priority 为空。attempt04 比 attempt01 去掉了 DB 服务列表中零贡献的 cart，服务集合这一项已改善，但数量仍错，所以二者 reward 都是 0。当前完整事件计分规则不会反映这类字段层进步。见 [attempt01](deepseek-flash-run01/seed17-attempt01/final_answer.json)、[attempt04](deepseek-flash-run01/seed17-attempt04/final_answer.json)。
2. **DeepSeek seed17-attempt03**：DB 填 1510、漏 AUTH、PAY 填 0、多报 BASE；priority 的第一个 ID 是 DB，但该事件明细不完整正确，位置分也不成立，因此仍为 0。不能因为它写了一个正确 priority ID 就认为它应获得更高分。见 [原始答案](deepseek-flash-run01/seed17-attempt03/final_answer.json)。
3. **Qwen seed17-attempt01**：把 host-auth、host-db 等资源 ID 写成服务 ID，提交负数量且 priority 超过两项；实际先因负数量被判格式违规。它只取过 list_alerts，没有取得权威服务关系、基线和业务指标，不能把这种输出归为“拿到全部数据但只算错”。见 [原始答案](qwen25-15b-run01/seed17-attempt01/final_answer.json)。
4. **Qwen seed42-attempt01**：前两轮协议错误，随后连续 10 次用虚构的 `incident_1`、`incident_2` 查询 get_incident_services，均得到合法空集，直到 12 轮预算耗尽。该运行没有最终答案，不能进行逐事件答案评分；它反映本预算内未能纠正查询对象。见 [运行结果](qwen25-15b-run01/seed42-attempt01/result.json)、[第三轮工具记录](qwen25-15b-run01/seed42-attempt01/turn-03-tool.json)、[第十二轮工具记录](qwen25-15b-run01/seed42-attempt01/turn-12-tool.json)。

DeepSeek 主批 12 次都已获取业务数据，却没有一个期望事件的数量正确；Qwen 则还出现格式、事件/服务识别、工具选择与预算内完成方面的失败。可以分别描述这些观测，不能据此将同为 0 的答案硬排序，也不能从轨迹倒推出未观测的内部原因。

## 能力解释与附加条件边界

任务目标是在给定规则下选择 API、进行跨来源关联、处理时间与维护例外、精确计算并排序。根因事件 ID 与权威关系由数据提供，任务不要求发现未知故障根因。本轮主 Harness 没有代码执行或计算器工具；任务模块本身可由程序化 Agent 接入，所以 DeepSeek 的主批低分不能外推为它在代码工具环境下也无法完成。

已完成的 [GPT/Codex 单次运行一](gpt-subagent-run01/evaluation.json) 和 [单次运行二](gpt-subagent-run02/evaluation.json) 均得 1，两个最终答案都与独立真值一致。分别核对了原始题面、system、工具 schema、5 次桥接调用及其返回，并重算评分，全部一致。其 Harness 和推理/输出预算与主批不同，精确部署标识不可得；两次 fresh-context 成功可以作为同一 seed17 的独立作答证据，即使要求不编程计算，也不能作为公平模型排名或 pass@4。本审计没有向 solver 传递答案或联系它们。

## 附加 DeepSeek thinking 条件：仍无实际中间分

[附加批次的计划与结果](score-order-diagnostic-run01/summary.json) 预先记录 thinking enabled、4096 token/轮、仅 seed17 四次；requested temperature=0.7、effective temperature=`ignored_in_thinking_mode`，并附有 [官方参数说明链接](https://api-docs.deepseek.com/guides/thinking_mode/)。本审计核对了这份条件记录和实际请求产物；本条件不能描述为与主批“同温度只改一个变量”的对照，也不并入主批的 pass@4 或均分。

[附加完整性证据](independent-audit-supplement-evidence-20261025T114131118485Z/integrity.json) 由新的 [补充审计脚本](independent-audit-supplement-check.py) 生成。四次运行的题面、schema、逐轮历史、工具返回、最终原始 JSON 与保存评分全部一致；summary 重聚合一致，没有基础设施执行错误。GPT 两次的检查也保存在此文件。复现命令为 `python -B artifacts/model-eval-final/independent-audit-supplement-check.py`，不触发模型调用。

| 附加 attempt | 最终状态 | 实际 reward | API 调用数 | 输出截断轮数 | 协议错误轮数 |
|---|---|---:|---:|---:|---:|
| 01 | 合法错答 | 0 | 0 | 1 | 1 |
| 02 | 完整正确 | 1 | 5 | 0 | 1 |
| 03 | 合法错答 | 0 | 1 | 2 | 3 |
| 04 | 格式违规 | 0 | 3 | 3 | 4 |

[attempt02 原始答案](score-order-diagnostic-run01/seed17-attempt02/final_answer.json) 的 AUTH=48、DB=174、PAY=120、正贡献服务及 DB/PAY 排序，与独立逐桶真值完全一致，重算仍为 1。该运行有一轮协议错误但最终完成，符合最终结果评分、不检查轨迹的契约。

三次失败都出现至少一轮 `finish_reason=length`，因此必须将输出预算、协议执行和业务作答共同视为该条件的实际表现，不能把这些失败归为不受运行条件影响的纯业务能力不足。也不能反向断言“只要增加 token 就一定会正确”：当前没有这个反事实证据。attempt01/03 的最终答案含快照中不存在的事件，attempt04 最终 snapshot_id 不匹配；它们确实没完成任务，但具体失败原因不能只由一个 0 分决定。

四次仅出现 `0,1,0,0`，实际中间分数量为 0。这提供了一次同一模型在另一种运行条件下成功的证据，却没有提供对中间质量答案做盲排序的样本；没有进行或声称完成中间分排序有效性分析。

## 最终采用的判据

30 次运行中各条件的实测结果都只出现最终 0/1，另有主批 Qwen 一次预算耗尽的原始 null。依据本次结果，以**严格完整通过/未通过**作为主要判据，未完成项再分格式、业务、工具/协议和预算原因诊断，不对同为 0 的答案宣称分数排序有效。

初审保留的作者构造 0.8/0.4 两答案只解释冻结公式，不是模型输出，不能用来填补本批不存在的中间分证据。没有为凑分数层次改变题目、阈值、评分或能力范围；也不将 24 次主批、4 次附加条件、2 次 GPT 独立作答合并成一个含义不清的总体通过率。
