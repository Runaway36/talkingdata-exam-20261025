# v3 满分误判审计（2026-10-25）

**结论：在当前公开 seed 0..9999 的固定数据分布与静态最终 JSON 威胁模型内，本次没有找到“不正确最终结果却得 reward=1”的实例。** 已完成全部 10,000 个公开快照的独立复算、2,535 个答案变异、85 个格式/异常输入检查。另发现 1 个明确受控的大整数 fixture 满分误判：真实异常失败量 100，错误答案 96 得 1。该 fixture 不由当前任何 seed 生成，不应当作为当前公开题目存在可达漏洞的证据。

审计基线为本地 commit `4cef31fb80df1e0ce2bef19b650c1cea4254d911`；执行后再次核对 config、data、environment、verifier 与 CONTRACT 的 SHA256，均与执行时一致。业务源码未修改，未联网、未调用模型、未推送。新增内容均位于本审计目录。

## 实查证据与复现

- [审计脚本](audit.py)：stdlib；不导入样例解法，不调用 `expected_answer`。公开快照通过业务 API 取数，再按题面用 Python 任意精度整数逐桶复算。评分检查调用现有 `verifier.evaluate`。
- [执行汇总与源码 SHA256](run-20261025T110928510662Z/summary.json)：Python 3.14.3；全部公开 seed 已覆盖；0 个独立真值不匹配，0 个错误变异满分，0 个协议拒绝失败。
- [默认实例 API 原始数据、逐桶账本和独立答案](run-20261025T110928510662Z/seed-17-independent-truth.json)：另保存 seed 0、23、91、9999 的同类证据。
- [85 个协议输入的实际评分](run-20261025T110928510662Z/protocol-results.json)。
- [空集、单事件与溢出受控 fixture 的实际评分](run-20261025T110928510662Z/controlled-fixtures.json)。
- [实际完整任务原文](run-20261025T110928510662Z/canonical-task.txt)。

在仓库根目录复现：

```powershell
python artifacts/redteam-v3/false-positive/audit.py
```

脚本每次建立带 UTC 时间戳的新目录，不覆盖上述结果。受控 fixture 只替换评分器的可信建库依赖以提供测试数据，不替换 Oracle SQL、评分公式或校验逻辑。这是测试注入，并非声称模型有能力修改可信快照。

## 当前公开实例：未找到满分误判

题面原文（`alert_rlvr/config.py:52-53`）：

> 奖励只依据最终结果：完整正确的事件分析计 1 单位；位置正确且事件分析完整正确的优先级项计 1 单位。
>
> 奖励为所得单位除以（应输出事件数 × 1 + 应输出优先级项数 × 1 + 多报事件数 × 1）。无应输出事件且答案为空时得 1；不检查调用轨迹。

本审计独立逐桶复算 seed 17：

| 事件 | 独立核算 | 等级 | 正贡献服务 |
|---|---:|---|---|
| INC-DB | checkout 的 36+39+31+37，加 search 的 15+16，合计 174 | P0 | svc-checkout、svc-search |
| INC-PAY | 18+18+19+23+22+20 = 120 | P1 | svc-pay |
| INC-AUTH | 9+11+10+10+8 = 48 | P1 | svc-auth |

AUTH 08:05 桶被完整 approved 维护覆盖，因此不计；cancelled 和局部覆盖维护不豁免其他桶。DB 只纳入完整落在对应服务影响区间内的桶；cart 在基线以内不列服务；LOG 完整维护不列事件；staging、P2、resolved 和范围外告警不贡献应输出结果。优先级为 `INC-DB, INC-PAY`。这些判断来自 API 原始行、题面和独立整数计算，不是将被测 Oracle 输出重新命名为真值。

执行范围：

| 检查 | 数量/范围 | 结果 |
|---|---|---|
| 全部公开快照的独立业务复算 | seed 0..9999，10,000 个 | 独立答案均得 1；无 Oracle 差异 |
| 事件与 priority 组合变异 | 默认 3 个事件，每个取完整正确、遗漏、错数量、错等级、错服务；再组合有/无额外事件和所有合法长度 0..2 的 priority 排列，共 2,535 个 | 只有 1 个语义全对答案得 1；其余均不足 1 |
| JSON / 类型 / 异常输入 | 85 个 | 全部 reward=0 且 valid=false；未抛出未处理异常 |
| 事件行与 service_ids 顺序反转 | 默认真实多服务实例 | 得 1，符合题面“顺序无关”，不是误判 |
| API 返回可变对象 | 修改返回告警字典后重新查询 | 可信快照未改变 |
| 真空集受控 fixture | 空答案、多报答案 | 分别得 1、0 |
| 单事件受控 fixture | 全对答案、漏报答案 | 分别得 1、0 |

85 个协议输入覆盖：bool / float / string / null / negative 数量，NaN / Infinity / 1e999，重复事件/服务/priority、重复 JSON 键（含转义后相同键）、顶层与嵌套额外字段、错误快照、错误容器类型、未知 priority ID、孤立 surrogate、超字节上限、超长整数、循环 dict、过深和尾随垃圾 JSON。具体每个输入的构造与实际报告保存在脚本和协议结果中。未把“支持的 P2/P3 等级但业务不匹配”当作格式错误；业务匹配阶段仍不能为其计完整事件分。

静态复核提供了额外依据：合法、评分期间不变的提交中，`C <= N`、`R <= K`、`X >= 0`，当前常量均为 1，故 `(C+R)/(N+K+X)=1` 需要 `C=N`、`R=K`、`X=0`。`C` 要求 severity、服务集合、数量三者全部正确，`R` 还要求对应事件已计入 `C`。因此仅 ID/等级碰巧正确、漏报、多报或正确排序配错误数量不能通过分母或 priority 门控取得满分。此判断依赖可信 Oracle 的业务正确性；这也是另做独立复算的原因。

## 受控扩展边界：SQLite 大整数溢出导致错误 96 得 1

**范围：仅受控 fixture；当前公开生成器不可达。** `data.py:118` 的请求量固定在 1000..1200，当前最大基线为 1000 bps，因此中间乘积至多 1,200,000，不会触发本问题。此项用于提示未来扩大数据值域时必须重验，不能据此否定当前全部 seed 的验收。

题面原文（`alert_rlvr/config.py:45`）：

> 常态失败量按每桶请求量与该服务基线计算并向下取整：request_count * baseline_failure_bps // 10000。异常失败量为实际 failed_requests 减去常态失败量，最低为 0，再累计各有效桶。

在不改评分代码的前提下，构造一个 production 服务、一个 P0 firing 事件、一个完整 08:00..08:05 桶、无维护的可信测试快照：

```text
incident_id = INC-CONTROLLED
service_id = svc-controlled
request_count = 9223372036854775807
baseline_failure_bps = 100
failed_requests = 92233720368547858
```

各输入整数本身均能存入 SQLite INTEGER。独立精确核算：

```text
9223372036854775807 * 100 // 10000 = 92233720368547758
92233720368547858 - 92233720368547758 = 100
```

任务为 `make_task(17)` 的完整规范文本（原文已保存）。向该受控快照上的现有评分器提交如下最终 JSON：

```json
{
  "snapshot_id": "alert-impact-v3-seed-17",
  "incidents": [{
    "incident_id": "INC-CONTROLLED",
    "severity": "P0",
    "service_ids": ["svc-controlled"],
    "excess_failed_requests": 96
  }],
  "priority": ["INC-CONTROLLED"]
}
```

实际返回 `reward=1.0, valid=true, matched_count=1, priority_matches=1`；将同一答案的 96 改为正确的 100 后，实际返回 `reward=0.0, valid=true`。见 `controlled-fixtures.json` 的 `overflow.wrong_report` 与 `overflow.true_report`。

原因位于 `verifier.py:135-136`：SQLite 中 `request_count * baseline_failure_bps` 超过有符号 64 位整数范围后转为浮点，除法与减法随之以浮点计算，得到 `96.0`。最终 JSON 整数 `96` 与 Oracle 的浮点 `96.0` 比较相等，完整事件与该 priority 位置都被计分。因题目要求异常失败量 100，错误结果少计 4 次，任务并未完成。这是业务 Oracle 的数值边界错误，不是重复键或 bool/int 类型绕过。

如以后扩展快照值域，建议明确数据上界并校验中间乘积，或使用不会在乘法时溢出的精确整数核算。此次未修改实现。

## 未被本结果证明的内容

- 当前 seed 只改变数值，结构固定。10,000 个 seed 全查并不等于对任意新业务结构、任意脏数据或未来配置都证明正确。
- 协议攻击检查是明确列出的有限集合；没有声称穷尽全部解析器资源耗尽路径或 Python 对象并发行为。
- 直接在同进程 monkeypatch 评分器、并发篡改待评分 dict 或读取内部数据库，需要超出“模型提交静态最终 JSON、可信 Harness 持有评分器”的能力，未当作 JSON 满分误判开展攻击。测试 fixture 的依赖注入也不代表模型拥有该能力。
- 题面明确不检查调用轨迹，所以不调用 API 却猜中完整最终结果，应当得 1，不是评分漏洞。有限 seed 与固定结构可能形成训练记忆或查询捷径；这是训练分布和信息暴露边界，需要另行评价，不能冒充本次找到的 false positive。
- 本次检查不能证明不存在其他漏洞；结论严格限定为上述实现哈希、公开实例、实际变异与受控 fixture。
