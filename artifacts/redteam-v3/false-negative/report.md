# v3 false-negative 红队报告

审计时间：2026-10-25。范围：当前 Python 模块交付；未调用外部模型、未联网、未推送、未修改业务实现。所有新增文件均在本目录。

本轮业务与评分源码由 root 固定为本地基准 commit `4cef31f`（未推送）；文档的精确被读版本以文末逐文件指纹为准。后续补充题面契约不改变本报告作为修订前审计证据的性质。

结论：找到 **1 项当前可达的低影响契约缺口**：合法、业务完全正确的 JSON 因未在题面/CONTRACT 披露的 1 MB 原始字节上限而被清零。未找到当前公开生成器 0..9999 种子中的业务计算误扣。另记录 **2 项当前生成器不可达的数值泛化边界**，以及 **1 项整数 JSON 表示的契约歧义**；后三项不冒充当前业务实例的确定性缺陷。

## 独立核查方法与覆盖范围

先读取 `config.py` 实际模型题面、`environment.py` 及 `API_SCHEMAS`、`data.py`、`verifier.py`、`docs/CONTRACT.md`，再按题面独立写逐桶计算。`audit.py:independent_answer` 只从公开业务 API 取数据，未导入或复制 `examples/reference_agent.py`，未调用 `expected_answer`。日期按 Python datetime 比较，基线用 Python 精确整数 `//`，按事件/服务/桶去重并累计。最后只调用 `compute_reward(task, answer)` 核查结果。

- 全部 **10,000 个合法 seed（0..9999）**：独立结果全部 reward=1；其中 98 个 seed 存在事件总量同分。优先顺序分布为 `INC-DB,INC-PAY` 4668 次、`INC-PAY,INC-DB` 5332 次。运行耗时约 20.67 秒。
- seed 17 的 **48 种等价答案**：6 种明细顺序 × 2 种服务顺序 × dict/compact JSON/pretty JSON/ID Unicode 转义，全部 reward=1。
- **12 个额外手算 fixture**：向下取整、等于/低于基线、部分影响桶、恰好结束边界、完整/部分/取消维护、告警恰好结束/稍晚结束、重复告警、staging 排除，全部 reward=1。这些不是公开生成器新增覆盖，不计入 10,000 个真实实例。
- 未将额外字段、重复 ID、数值字符串、负数、布尔值、错误 priority 等明确违反题面格式或业务规则的答案伪装成 false negative。
- 全 seed 穷举只证明该固定生成分布中的这套独立算法没有发现分歧，不能证明任意 DB、任意序列化或未来结构无缺陷。

复现（仓库根目录，Python stdlib）：

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
python artifacts/redteam-v3/false-negative/audit.py
python artifacts/redteam-v3/false-negative/edge_probes.py
```

每次运行创建新的时间戳证据目录，使用排他写入；不覆盖本次或历史证据。

主要证据：

- `evidence-20261025T110903051238Z/summary.json`
- `evidence-20261025T110903051238Z/independent-answer-seed-17.json`
- `evidence-20261025T110903051238Z/independent-buckets-seed-17.json`
- `evidence-20261025T110903051238Z/equivalent-representations.json`
- `edge-evidence-20261025T111015778254Z/manual-business-boundaries.json`

## FN-01：正确 JSON 仅增加合法空白，因未披露字节限制得 0

分类：当前可达；低影响格式契约缺口。不是业务数值算法错误，不建议因该反例声称日常答案普遍受影响。

**题面原文**（`alert_rlvr/config.py:49-53`）：

> 返回 JSON：snapshot_id；incidents 数组（每项含 incident_id、severity、service_ids、excess_failed_requests）；priority 数组（前 2 个事件 ID）。
>
> excess_failed_requests 必须为非负整数；明细行与 service_ids 顺序无关，priority 顺序有意义。
>
> JSON 只包含上述字段，不得重复 JSON 键、事件 ID、同一事件内服务 ID 或优先级 ID；priority 只能引用已提交事件。快照不符、额外字段或类型错误等格式违规得 0。
>
> 奖励只依据最终结果：完整正确的事件分析计 1 单位；位置正确且事件分析完整正确的优先级项计 1 单位。

题面没有字节限制。`docs/CONTRACT.md:50-70` 的答案及评分规则也没有披露该限制；实现 `config.py:12` 则固定 `MAX_ANSWER_BYTES=1_000_000`，`verifier.py:46-49` 在 JSON 解析之前按原始 UTF-8 字节数拒绝。

**具体 task**：`make_task(17)`，原文已保存在 `evidence-20261025T110903051238Z/task-seed-17.txt`。

**具体业务答案**：

```json
{"snapshot_id":"alert-impact-v3-seed-17","incidents":[{"incident_id":"INC-AUTH","severity":"P1","service_ids":["svc-auth"],"excess_failed_requests":48},{"incident_id":"INC-DB","severity":"P0","service_ids":["svc-checkout","svc-search"],"excess_failed_requests":174},{"incident_id":"INC-PAY","severity":"P1","service_ids":["svc-pay"],"excess_failed_requests":120}],"priority":["INC-DB","INC-PAY"]}
```

将其序列化为 compact JSON，结尾添加 ASCII 空格，使总字节数恰为 1,000,001。完整原始答案保存在 `evidence-20261025T110903051238Z/correct-but-over-byte-limit.json`；没有增加字段或改变数字、ID、数组。构造式为 `raw + ' ' * (1000001 - len(raw.encode('utf-8')))`。

**实测**：

| 同一答案的表示 | 实际 reward | valid | error |
|---|---:|---|---|
| 总计 1,000,000 bytes | 1.0 | true | 无 |
| 总计 1,000,001 bytes | 0.0 | false | `answer exceeds byte limit` |

程序同时验证 `json.loads(at_limit) == json.loads(above_limit) == independent_answer` 为 true；`compute_reward` 独立调用也返回 0.0。详见 `byte-limit-result.json`。

**预期理由**：JSON 末尾空白合法；按已向模型公开的规则，C=3、R=2、N=3、K=2、X=0，应该得 1。实现施加了模型未收到的传输限制，因此是题面与实现契约不一致，不是答案违反已明确规定的格式。

**复现命令**：上述 `python artifacts/redteam-v3/false-negative/audit.py --seed-count 1` 即可快速复现本条，仍会生成新的独立证据目录。

**影响范围**：任何当前合法 seed 都可以如此构造；实际影响集中在超大空白填充或序列化输出。通常几百字节的模型答案不触发。保留资源上限是合理选择，建议把明确字节上限及计算方式补入实际模型题面和 CONTRACT，使其成为公开协议，而不是删除保护。

## G-01：大整数乘积转浮点，精确取整业务结果被漏掉

分类：**当前公开生成器不可达的泛化边界**。不是 `make_task(17)` 原始数据的错误答案；只在测试中替换可信建库函数为新 fixture，评分计算代码完全不改。

**题面原文**（`config.py:45`）：

> 常态失败量按每桶请求量与该服务基线计算并向下取整：request_count * baseline_failure_bps // 10000。异常失败量为实际 failed_requests 减去常态失败量，最低为 0，再累计各有效桶。

**具体 task / fixture**：沿用 `make_task(17)` 的业务规则文本，测试注入单事件 `INC-EXACT`、P1/firing、单 production 服务 `svc-exact`、完整 08:00..08:05 桶、无维护。请求数 9007199254740995，基线 5000 bps，实际失败数 4503599627370498；均为 SQLite INTEGER 范围内的非负值，失败数不大于请求数。

**手算与 answer**：

```text
9007199254740995 * 5000 // 10000 = 4503599627370497
4503599627370498 - 4503599627370497 = 1
```

```json
{"snapshot_id":"alert-impact-v3-seed-17","incidents":[{"incident_id":"INC-EXACT","severity":"P1","service_ids":["svc-exact"],"excess_failed_requests":1}],"priority":["INC-EXACT"]}
```

**实测 reward**：0.0；valid=true，expected_count=0，extra_count=1。即 SQL oracle 将真实的 1 次异常失败消去，误把这个完整事件看成多报。原因位置为 `verifier.py:135-136`：SQLite 中整数乘积溢出会转为 REAL；该数值随后除法的浮点结果比正确 floor 值高 1。

**预期理由**：规则要求精确乘法与向下取整，手算 C=1、R=1、N=1、K=1、X=0，应得 1。

**复现命令**：`python artifacts/redteam-v3/false-negative/audit.py --seed-count 1`；fixture 定义在 `audit.py:numeric_fixture('product_precision')`，实测保存在 `out-of-distribution-numeric-fixtures.json`。

**影响范围**：当前 data.py 每桶请求量仅 1000..1200，基线固定且小，不可能出现本数值；当前 10,000 个实例不受影响。只说明将来若扩充到无限制整数数据，现有 SQL 算术不满足题面描述的任意精确整数公式。应选择限制并公开数值范围，或对大值使用精确算术。

## G-02：单桶计数合法但服务累计超出 SQLite INTEGER，正确结果得 0

分类：**当前公开生成器不可达的泛化边界**；与 G-01 分开记录，根因是 SUM 聚合整数溢出。

**题面原文**（`config.py:45,50`）：

> 异常失败量为实际 failed_requests 减去常态失败量，最低为 0，再累计各有效桶。
>
> excess_failed_requests 必须为非负整数。

**具体 task / fixture**：沿用 `make_task(17)` 规则，单 `INC-EXACT`/P1/firing、单 production 服务 `svc-exact`、基线 0；08:00..08:05 和 08:05..08:10 两桶，每桶 `request_count=failed_requests=4611686018427387904`。每个存储数值都在 SQLite 有符号 64 位 INTEGER 范围内，无维护且完整包含。

**手算与 answer**：两桶各 `2**62`，事件总量 `2**63 = 9223372036854775808`。

```json
{"snapshot_id":"alert-impact-v3-seed-17","incidents":[{"incident_id":"INC-EXACT","severity":"P1","service_ids":["svc-exact"],"excess_failed_requests":9223372036854775808}],"priority":["INC-EXACT"]}
```

**实测 reward**：0.0，valid=false，error=`trusted snapshot could not be evaluated`。`verifier.py:156` 的 `SUM(excess_failed_requests)` 超过 SQLite INTEGER 范围并抛错，随后由 `evaluate` 捕获并清零。Python/JSON 该非负整数本身可正确表示，题面没有公开累计上界。

**预期理由**：精确累加结果如上，其他事件字段及排名均正确，按业务规则应该得 1。

**复现命令**：`python artifacts/redteam-v3/false-negative/audit.py --seed-count 1`；fixture 定义在 `audit.py:numeric_fixture('sum_overflow')`，证据同 G-01 文件。

**影响范围**：当前生成器的请求范围及桶数完全不会触发；只限定未来数值分布扩展，不应当作当前交付阻断项。

## A-01：整数值小数/指数 JSON 被拒绝，当前先记契约歧义

**题面原文**：`excess_failed_requests 必须为非负整数`（`config.py:50`）；`docs/CONTRACT.md:68` 规定“非法类型”清零，但未给答案 JSON Schema，也未规定整数值是否必须使用不带小数点/指数的词法表示。实现 `verifier.py:102` 要求解析后的 Python 类型严格为 `int`。

**具体 task / answer**：使用 FN-01 的同一正确 seed 17 答案，仅把数量改写成 `48.0/174.0/120.0` 或 `48e0/174e0/120e0`。完整原始 JSON 和报告保存在 `edge-evidence-20261025T111015778254Z/numeric-spelling.json`。

**实测**：原整数 JSON reward=1；两种整数值表示均 reward=0，error=`excess_failed_requests must be a nonnegative integer`。`json.loads` 后数值与原答案相等，但运行时类型为 float。

**判断**：业务数值等价已经证实；“违反整数类型格式”是否成立，取决于公开协议采用数学整数值还是 Python 解析类型。目前不能把这两种解释之一强行视为已明确约定，因此 **不计作确定 false negative**。直接提交 Python float dict 与普通整数 dict 的类型本来不同，更不应借数学等值直接宣称允许。

**复现命令**：`python artifacts/redteam-v3/false-negative/edge_probes.py`。

**影响范围及可选收敛方式**：所有 seed 都可以生成该表示。若要求严格词法整数，可在题面明示“JSON 数字不得带小数点或指数，Python dict 值必须是 int 且非 bool”；若接受数学整数值，可只在精确验证整数值及有限性后归一化。当前报告不修改或替实现选择该约定。

## 被审计文件指纹

SHA-256（审计完成时读取，用于识别后续修改是否属于复验对象）：

```text
alert_rlvr/config.py       5503E707BAF7B1266BE3239F166E13C180114901E0322DC8D2F2C699FBA8B5CB
alert_rlvr/data.py         81B3FB8B4AA3197505E8B3141F1D9486FBB067CE330B9D640E38B1D0AFE3A157
alert_rlvr/environment.py  FB64C24F5E6B95C0E391F77344B685B7AEB8BB2CC48E436505FD56A0143AF13A
alert_rlvr/verifier.py     E3C3D1032BD204E0384792BBD13C6E8188BDC9422B8D31A1A3D5749429474E3D
docs/CONTRACT.md           2F495A0F50B893667353823735A2C3C96739E84114563D3469AD49DE81846339
```
