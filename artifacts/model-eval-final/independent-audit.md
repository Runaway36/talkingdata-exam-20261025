# 最终模型评测的独立审计

本报告初审截至 **2026-10-25 11:32:55 UTC**：DeepSeek 最终批次 12/12 已完成，全部是合法但业务错误的答案，reward 均为 0；Qwen 最终批次当时取得 4/12 份结果，2 份格式违规、2 份合法错答，均为 0；GPT/Codex fresh-context sub-agent 的单次答案得 1，独立逐桶核算一致。**这些结果没有展示 DeepSeek 与 Qwen 的非零分数差异，也不支持跨 Harness 的公平模型排名。** Qwen 未完成部分不计为零、不提前汇总整批 pass@4。

本审计未修改题面、业务数据、评分器、README 或模型输出，未运行模型，未向 GPT solver 发送消息。旧红队未重跑。这里只增加本报告、审计脚本与独立证据。

## 可复现证据

- 冻结依据：[frozen-task.json](frozen-task.json)。本次复核时，全部 `alert_rlvr/*.py` 的 SHA256 与冻结记录一致。
- 审计脚本：[independent-audit-check.py](independent-audit-check.py)。执行 `python -B artifacts/model-eval-final/independent-audit-check.py`，仅读取模型产物、重放业务 API、重算评分，输出新的带时间戳的独立证据目录。
- [本次逐运行完整性检查与独立重汇总](independent-audit-evidence-20261025T113255776793Z/run-integrity.json)。DeepSeek 12 份及当时 Qwen 4 份均未发现完整性检查失败。
- [seed 17 / 42 / 99 的 API 原始数据、独立逐桶账本及答案](independent-audit-evidence-20261025T113255776793Z/independent-truth.json)。使用先前独立审计的 Python 整数业务计算方法，只重新核算这三个实例；不调用参考解法或评分器 Oracle 生成真值。
- [作者构造的 0.8 / 0.4 对照](independent-audit-evidence-20261025T113255776793Z/controlled-scoring-examples.json)。此文件明确标为非模型输出，未进入任何模型统计。

## Harness 和原始证据是否忠实

审阅 `experiments/run_model_pilot.py`、`run_repeated_evaluation.py`、`local_qwen_driver.py` 后，又对上述 16 份已完成运行的实际文件进行了回放检查。

| 检查 | 代码机制与实际核验 |
|---|---|
| 原始题面 | `initial_input.json` 的 user 消息与相应 seed 的当前 `make_task` 逐字一致；没有删掉维护、基线、区间、正贡献服务或评分规则 |
| 工具定义 | system 消息包含完整 `API_SCHEMAS`；没有只给工具名、删掉参数约束 |
| 工具返回 | 每份 `turn-XX-tool.json` 的返回值均与对应 seed 的新建环境 `.call(name, arguments)` 一致；后续请求完整包含原样 JSON 返回，无人工摘要、截断、替换数据 |
| 对话历史 | 每一轮保存的 request 与前一轮历史、模型原文和工具返回/协议错误提示连续对应，没有漏消息或跨 attempt 反馈 |
| 最终答案 | `raw_answer_json` 提取原始 answer 文本，原样写入 `final_answer.json` 并直接交给评分器。实际文件均为最后一轮模型原文中的对应子串，未先将最终数字舍入成 Python float |
| 原始响应 | 保存每轮 `turn-XX-response.json`；DeepSeek 另含 provider 原始响应及 token 使用信息。最终结果的错误没有被修补后再评分 |
| 保存分数 | 重新以冻结规则评分原始 `final_answer.json`，与 `evaluation.json` 及 `result.json` 完全一致 |
| 本地 Qwen 上下文 | driver 使用标准 chat template，检查 `input_tokens + max_tokens <= context_limit`；越界报错，不静默截断输入。CUDA 加载/生成失败不自动切 CPU |

工具结果以 user 文本“工具返回：…”传给模型，属于预先确定的文本 JSON Harness，不能把它称为原生 function-calling 对照。每轮只能 call 或 final，不能附带普通推理正文，也没有计算器工具；DeepSeek 使用 thinking disabled。这些运行条件影响表现，属于结果解释的必要限定。

任务实际要求是在给定业务规则下选择 API、关联告警/事件/服务/观测数据、处理时间与维护例外、精确计算并排序。数据已提供 incident_id 和权威事件服务关系，因此不测“从未知因果线索发现故障根因”。本轮模型 Harness 不提供代码执行或计算器，而任务模块本身允许程序化 Agent 接入并计算；DeepSeek 在当前纯文本查询与计算条件下的低分，不能外推为它在代码工具环境中也做不到。GPT 单次虽然记录为不编程计算，仍保留推理预算与 Harness 不同的比较限制。本次不因结果形态修改阈值、评分公式或所声称的能力范围。

`_object_text` 容许“整段 fenced JSON”外壳后再解析，但不从任意正文中搜索可评分片段。最终业务 JSON 未经修补。该容错应作为 Harness 行为理解，而不是模型严格遵守“不要 Markdown”的证据。

## 运行错误和答错的区分

`run_model_pilot.py` 将模型已提交的格式违规结果记为 `invalid_final_answer`；合法但错误的结果仍为 `completed`，需继续看 reward，不能把 completed 误读成通过。预算用尽无 final 为 `budget_exhausted_without_final_answer`，是本预算下未完成，不等于已经拿到一份可分析的业务错答。

网络、加载、本地推理等异常为 `execution_error`，reward 保持 null。`run_repeated_evaluation.py` 对这类结果设 `passed=None` 并停止批次，不产生 complete=true 的正式总体分数。没有结果文件或批次超时同样留下 incomplete/error，而不是补零伪装成模型错答。

预算用尽无 final 时，`result.json` 的原始 reward 同样为 null，**并没有一份最终答案被验证器打成 0**。它会按“预定 12 轮预算内未完成”计入 pass 统计的失败项；完整批次 `mean_reward` 的 `reward or 0` 将此类未作答按 0 纳入分母。这是预算内完成表现的统计约定，因此此处均分准确含义是“将预算耗尽未答按 0 的每次尝试均分”，不是“仅对已获验证器分数的答案取平均”。它与运行异常导致批次中止、不给正式均分不同。报告必须单列预算耗尽、格式违规、合法错答和运行异常，不能把四者都称为纯业务计算错误。

本次 DeepSeek 12 次均 `completed`，没有协议错误或输出截断；其 65 次实际工具调用返回全部 `ok=true`。因此本批 0 分不是网络不可用、接口错误、缺少工具数据或 token 截断的直接产物。模型得到数据后为什么仍给出错误数量，无法仅凭最终答案断言其内部原因。

Qwen preflight 和原始 turn replay 保存在独立目录，不应与 `qwen25-15b-run01` 的 12 次正式预算混合。当前已核查的 Qwen 4 次都有最终答案，属于模型输出/协议表现；预检恢复运行只证明当前路径能跑，不代表此前故障根因或硬件归因已经证明。

## pass@4 统计审计

重复评测固定 seed 17、42、99，各开 4 次新进程/新对话；没有把前一 attempt 的答案或评分反馈给下一 attempt。任务 seed 控制数据，sampling seed 控制本地生成，两者已区分。Qwen 的 per-turn RNG seed 块互不重叠；DeepSeek API 不支持该采样 seed，元数据明确记录服务端随机性不可控。独立上下文不等于已证明统计上的独立同分布。

代码以 `valid=true && reward==1` 为严格成功。对每个实例，`pass_at_1 = 4 次中成功次数 / 4`，`pass_at_4 = 至少有一次成功的指示值`；最后对三个固定实例等权平均。n=k=4 时，这是这四次观测的 pass@4 口径，不是“四次平均 reward”，也不是总体成功概率的精确估计。

DeepSeek 的 [summary.json](deepseek-flash-run01/summary.json) 已由独立脚本从原始结果重新聚合：三个实例均 0/4 成功，整体 pass@1=0、pass@4=0、mean reward=0，与保存值一致。只做三个固定结构实例、每个四次，不能据此声称广泛泛化、鲁棒性、内在难度或总体成功率。

## 逐事件人工核查：同为 0 分，错误并不相同

seed 17 的独立真值是：AUTH/P1/`[svc-auth]`/48；DB/P0/`[svc-checkout,svc-search]`/174；PAY/P1/`[svc-pay]`/120；priority 为 DB、PAY。

逐桶账本支持上述数字：AUTH 有效桶 `9+11+10+10+8=48`；DB 的 checkout `36+39+31+37=143`、search `15+16=31`，合计 174；PAY `18+18+19+23+22+20=120`。cart 六桶异常均为 0，不能列入 DB 正贡献服务；BASE 无正异常；LOG 被完整 approved 维护覆盖，二者不应输出。

### 代表答案一：DeepSeek seed17-attempt01

[原始最终答案](deepseek-flash-run01/seed17-attempt01/final_answer.json)；[实际评分](deepseek-flash-run01/seed17-attempt01/evaluation.json)。

| 项目 | 实际提交 | 独立判断 |
|---|---|---|
| AUTH | P1、svc-auth、0 | 等级与服务对，数量应为 48 |
| DB | P0、cart/checkout/search、0 | 等级对，cart 不应计入服务；数量应为 174 |
| PAY | P1、svc-pay、0 | 等级与服务对，数量应为 120 |
| 额外事件 | BASE、LOG，均填 0 | 都不应输出，共多报 2 |
| priority | 空 | 缺少 DB、PAY 两个位置 |

三个期望事件没有一个“等级、服务集合、数量全部正确”，故 C=0；priority 为空，R=0；X=2。实际分数 `0/(3+2+2)=0`。该模型已成功取到所有需要的数据：5 次调用返回 7 条告警、8 条事件关系、8 条服务档案、6 条维护、42 条指标，数据完整进入下一轮消息。不能将它解释成接口没有给出必要数据。

### 代表答案二：DeepSeek seed17-attempt04

[原始最终答案](deepseek-flash-run01/seed17-attempt04/final_answer.json)；[实际评分](deepseek-flash-run01/seed17-attempt04/evaluation.json)。

这份答案在业务语义上与 attempt01 相比，只把 DB 的 `service_ids` 中零贡献的 `svc-cart` 删去了；AUTH、DB、PAY 仍全部填 0，仍多报 BASE/LOG，priority 仍为空。**它的 DB 服务集合更准确，但同样得 0。** 数量仍错使 DB 的完整事件分继续为 0；当前评分没有服务字段层的部分分数，因而这项局部改善完全不可见。

另一份 [seed17-attempt03](deepseek-flash-run01/seed17-attempt03/final_answer.json) 则报 DB=1510、漏 AUTH、多报 BASE、PAY=0，priority 仅写 DB，仍为 0：即使第一处 priority ID 碰巧正确，DB 分析不完整正确，位置分也不计。这里不能凭“它至少写了一个优先级”就认为 reward 应高于空 priority。

### Qwen 已取得的代表答案

[seed17-attempt01](qwen25-15b-run01/seed17-attempt01/final_answer.json) 把 `host-auth` / `host-db` 等主机 ID 写作 service_ids，并提交 -5、-3 等负数量与三个 priority 项，实际 `valid=false, reward=0`。它只调用过一次 list_alerts，没有取得权威服务关系、基线和指标；主机 ID 确实出现在告警行，但不能充当服务 ID。

[seed17-attempt03](qwen25-15b-run01/seed17-attempt03/final_answer.json) 未成功调用业务工具，直接写出 `incident_1`、`incident_2` 等不存在于快照的事件，结构合法但 reward=0。两者都是 0，与 DeepSeek 已取得完整数据、部分字段正确但数量全错的答案有明显不同。**这些差异需要通过格式状态、覆盖情况和逐字段证据说明，不能假装现有 reward 在这批输出上已经提供了良好区分。**

## GPT 单次成功的可证明范围

[GPT 最终答案](gpt-subagent-run01/final_answer.json) 的三个事件、服务集合、数量和 priority 与本审计独立真值完全一致；重新评分 reward=1，和 [保存的评价](gpt-subagent-run01/evaluation.json) 一致。其 [业务推导记录](gpt-subagent-run01/reasoning.md) 中维护、影响区间、基线与逐桶加总也可逐项核对，并非仅凭评分器报 1 认定成功。

该结果来自一次 fresh-context GPT/Codex sub-agent，精确部署标识不可得，Harness、推理预算与输出预算未与 DeepSeek/Qwen 对齐。它可以证明“另一路独立 Agent 能在这份 seed17 数据上给出正确业务结果”，不能记为 GPT 的 pass@4，不能与两个 12 次批次作公平排行榜，也不能将差异单独归因于模型、模型规模或本地 GPU。

## 作者构造的 0.8 / 0.4 对照：解释规则，不冒充模型结果

真实模型样本中没有 0.8 或 0.4；以下两个结果由审计者基于独立真值明确构造，单独保存在 [controlled-scoring-examples.json](independent-audit-evidence-20261025T113255776793Z/controlled-scoring-examples.json)，未计入 pass@1/pass@4/均分。

| 作者构造输入 | 完整事件 C | 正确且受支持位置 R | 额外事件 X | 实际 reward |
|---|---:|---:|---:|---:|
| 只将 AUTH 数量由 48 改为 0；DB、PAY 全对，priority 仍 DB、PAY | 2 | 2 | 0 | 4/5 = 0.8 |
| 与上一份所有事件明细完全相同，再把 priority 改成 PAY、DB | 2 | 0 | 0 | 2/5 = 0.4 |

这个受控比较中，低分比高分具体多错的是两个优先级位置，差 0.4；不是错误数量的绝对偏差大小。它说明冻结公式在这一受控对照上怎样分配分数，不能据此补充声称真实模型已表现出这两个分数层次。

## 尚不能下的结论

当前真实样本的主要分数形态是 0 与单次 GPT 的 1，缺少同 Harness 的中间分数证据。可以报告本批在既定条件下的通过情况和具体错法；不能称任务已完成难度标定、具有跨结构泛化证明、验证器已穷尽鲁棒性攻击，或当前 reward 已能细分所有错误程度。若后续 Qwen 正式批次完成，应只更新完整批次的真实统计，保留本次部分快照和受控例子的来源边界。
