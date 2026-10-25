# Qwen2.5-1.5B-Instruct 最终固定批次运行记录

日期：2026-10-25（北京时间）。正式批次从 19:30:56 至 19:37:12，墙钟约 375.32 秒；各 episode 记录耗时合计 372.45 秒。

**固定 3 个实例 × 4 次采样全部实际执行完成，没有基础设施错误。pass@1=0，pass@4=0。** 这只是当前三个固定实例、指定模型与 text-JSON 工具协议下的观察，不代表总体通过率或模型内在难度。

## 冻结条件与证据

- 模型：本地 `Qwen2.5-1.5B-Instruct`，固定 Hugging Face 快照 `989aa7980e4cf806f80c7fef2b1adb7bc71aa306`；离线加载，没有下载。
- 设备与数值条件：所有 12 次加载日志均为 `cuda:0`、`torch.bfloat16`；PyTorch `2.11.0+cu128`、CUDA 12.8、SDPA。没有改变精度、设备、模型或 attention 实现。
- 任务版本：v3；数据实例 seed 为 17、42、99，各独立执行 4 次，每次新进程及新 conversation，无跨尝试反馈。
- 生成条件：temperature=0.7、do_sample=true、top_p=1.0、top_k=0；每次最多 12 轮、每轮最多 1024 输出 token。
- 采样 seed：`20261025 + task_instance_seed * 10000 + attempt * 100`，每轮再加 `turn - 1`。已核对全部 144 个计划轮次 seed 互不重复；实际 39 个生成响应的采样参数和轮次 seed 均匹配。
- 核心 `alert_rlvr/*.py` SHA256 在运行前保存，每个 episode 的 metadata、批次 summary、运行结束后的源码均一致。任务、业务逻辑、评分器和 README 未修改。
- 正式明细与指标：[summary.json](summary.json)；独立运行条件核查：[independent-run-audit.json](independent-run-audit.json)。后者读取本批已保存结果和诊断字段，没有对旧批次重评分。
- 冻结文件与实验脚本哈希：[formal-batch-launch.json](../qwen25-15b-preflight-20261025/formal-batch-launch.json)。

## 完整率与评分口径

| 项目 | 结果 |
|---|---:|
| 计划尝试 / 实际完成执行 | 12 / 12 |
| execution_error | 0 |
| 提交了 final 的尝试 | 11 / 12（91.67%） |
| final 协议合法 | 5 / 12（41.67%） |
| final 协议非法 | 6 / 12 |
| 走满 12 轮但没有 final | 1 / 12 |
| 完整正确答案 | 0 / 12 |
| pass@1（每实例四次通过比例，再对三实例平均） | 0 |
| pass@4（每实例四次至少一次完整正确，再对三实例平均） | 0 |
| 实际有数值 reward 的尝试 | 11，均为 0 |
| 原始 reward=null 的尝试 | 1 |
| summary.mean_reward | 0 |

`seed42-attempt01` 在固定轮次预算内没有交出 final，因此原始记录保持 `reward: null`，不存在一次实际最终答案评分。批次汇总将未完成 final 的尝试按失败计入 pass@k，并在 `mean_reward` 中按 0 聚合；11 个实际评分的平均值也为 0。该情况不是基础设施错误，不能与执行异常混合归因。

| 数据 seed | 尝试数 | 合法但错误 final | 非法 final | 没有 final | 完整正确 | pass@1 | pass@4 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 17 | 4 | 2 | 2 | 0 | 0 | 0 | 0 |
| 42 | 4 | 2 | 1 | 1 | 0 | 0 | 0 |
| 99 | 4 | 1 | 3 | 0 | 0 | 0 | 0 |

## 逐事件差异

下表的 expected 字段来自本批冻结评分器已写入 `summary.json` 的诊断，不是本报告重新独立证明的业务真值。非法 final 和无 final 的尝试不进入逐字段诊断；不能将它们的字段表现当作已成功解析的答案。

| seed | 事件 | expected 异常请求数 | 合法 final 对照次数 | 其中缺失事件 | severity 正确 | 服务集合正确 | 数值正确 | 完整事件正确 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 17 | INC-AUTH | 48 | 2 | 1 | 1 | 0 | 0 | 0 |
| 17 | INC-DB | 174 | 2 | 1 | 1 | 0 | 0 | 0 |
| 17 | INC-PAY | 120 | 2 | 2 | 0 | 0 | 0 | 0 |
| 42 | INC-AUTH | 48 | 2 | 2 | 0 | 0 | 0 | 0 |
| 42 | INC-DB | 171 | 2 | 2 | 0 | 0 | 0 | 0 |
| 42 | INC-PAY | 175 | 2 | 2 | 0 | 0 | 0 | 0 |
| 99 | INC-AUTH | 53 | 1 | 1 | 0 | 0 | 0 | 0 |
| 99 | INC-DB | 140 | 1 | 1 | 0 | 0 | 0 | 0 |
| 99 | INC-PAY | 212 | 1 | 1 | 0 | 0 | 0 | 0 |

合计 15 个期望事件对照位置中，13 个事件缺失；2 个事件 severity 对齐，但服务集合和异常请求数仍不正确。severity 的局部对齐只是诊断，不代表 v3 已奖励某个完整事件。

六个非法 final 的首个验证错误分别为：

- `seed17-attempt01`、`seed17-attempt02`、`seed42-attempt02`：异常请求数不是非负整数。
- `seed99-attempt01`、`seed99-attempt04`：snapshot_id 不匹配。
- `seed99-attempt03`：incident_id 重复。

## 具体轨迹案例

本批所有实际 reward 都为 0，没有高分案例，不能人为挑选一个“高分”结果。下面区分不同失败方式。

1. **读取告警后将资源当作服务，且没有查询计数依据。** [seed17-attempt04](seed17-attempt04/) 只调用了一次 `list_alerts`，随后 final 将 `host-auth`、`host-db` 填为 service_ids；AUTH 计数报 0（expected 48），DB 报 200（expected 174），PAY 缺失，额外输出 BASE、LOG。priority 为 `[INC-DB, INC-AUTH]`，expected 为 `[INC-DB, INC-PAY]`。这里已经有少量真实数据，但没有完成从事件服务关系到请求指标的查询链。
2. **没有查数据便编造事件。** [seed17-attempt03](seed17-attempt03/) 没有业务工具调用，输出 `incident_1`、`incident_2` 及 3000、2000 等计数；格式合法但与目标快照事件不符。seed42 的 attempt03/04 同样出现非快照事件 ID。
3. **重复查询无效 ID，耗尽预算。** [seed42-attempt01](seed42-attempt01/) 第 3 至 12 轮连续十次调用 `get_incident_services`，参数始终为 `[incident_1, incident_2]`，每次合法返回空列表。没有 final，原始 reward 为 null。这是模型没有利用空结果修正行动，不是工具服务崩溃。
4. **调用不存在的工具，随后交空答案。** [seed99-attempt02](seed99-attempt02/) 调用 `business_rules_engine`，业务白名单返回 `UNKNOWN_API`；随后 final 的 incidents 和 priority 为空。协议合法、得分 0。该错误返回是正常工具反馈，不是基础设施故障。
5. **非法计数。** [seed17-attempt01](seed17-attempt01/) 输出 AUTH=-5、BASE=-2、DB=-3，直接违反非负整数约束；其 final 原始 JSON 未经 float 重序列化，完整保存在 `final_answer.json`。

本批共 15 次工具调用，其中 1 次工具错误响应；共 13 次文本 action 协议错误；0 次生成长度截断。原始模型响应、工具参数、工具返回与最终答案逐轮保留，不能将这些不同失败合并成单一“算术能力不足”原因。

## 旧运行异常与本轮恢复的边界

旧记录 [model-eval-v3/qwen25-15b-run01/seed17-attempt01](../../model-eval-v3/qwen25-15b-run01/seed17-attempt01/) 曾在第三轮发生 RuntimeError。旧 driver 的 `_error` 将普通 RuntimeError 的真实消息替换为泛化文本，stderr 又仅打印同一精简结果，因此旧异常的实际 Torch/CUDA 根因查不到。

此前已经完成的最小代码修复是在 stderr 保留完整 traceback，stdout 保持精简 JSON 协议。不能把日志修复表述成修复了某个 CUDA、显存、精度或 SDPA 根因。

本轮先做了两项独立运行检查，均不计入正式 pass@4：

- [原始前三轮同进程重放](../qwen25-15b-preflight-20261025/original-turns-01-to-03-replay/)：逐轮使用原保存请求和原 sampling seed，一次加载同进程处理 3 个请求；26.975872 秒，3 个响应、0 个执行错误，原异常未复现。
- [完整 seed17 检查 episode](../qwen25-15b-preflight-20261025/seed17-episode01/)：30.416 秒，无执行异常；最终答案因负数计数被判非法，reward=0。该检查与正式批次严格区分，不增加正式分母。

随后正式 12 次全部无执行异常，说明本轮固定条件下执行链已恢复并可完成批次；这仍不证明旧 RuntimeError 根因已解决。没有因排障自动修改精度、设备、解码策略、上下文或轮次预算，也没有在失败后删掉不利样本。结束后已确认没有本批 Qwen driver 或 batch 进程继续运行，模型 GPU 分配已释放。

## 解释范围

本结果同时依赖任务版本、指定 1.5B 模型、BF16/CUDA 运行、text-JSON 工具协议、采样参数和预算。它不能支持对所有 Qwen 模型、其他原生 function-calling harness 或总体任务分布的外推。旧 v2 温度 0 试跑和本 v3 温度 0.7 批次条件不同，不能把跨版本分差只归因于任务修改。
