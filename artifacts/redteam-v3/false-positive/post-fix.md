# 数字解析修复后的定向复核（2026-10-25）

**结论：本次 125 个定向检查全部符合预期，未找到 Decimal 修复引入的“错误数字得满分”路径。** 这是数字解析小改动的后续检查，不是重新执行或更新旧版 10,000 个 seed 审计；原 [report.md](report.md) 与旧脚本、旧证据均保留不变。

本次检查的是 `4cef31f` 之后尚未提交的数字解析和题面修改。执行时 config、verifier、data、CONTRACT 的准确 SHA256 保存在 [本次汇总](post-fix-run-20261025T111512480014Z/summary.json)，避免把旧基线结果混称为新代码结果。

复现命令：

```powershell
python -B artifacts/redteam-v3/false-positive/post_fix_numeric_audit.py
```

[新脚本](post_fix_numeric_audit.py) 只复用旧审计中通过业务 API、Python 整数独立核算并保存的 seed 17 真值，使用当前 `make_task(17)` 和当前评分器。未调用样例解法或 `expected_answer`，未改业务源码，未联网或调用模型。每次运行建立新证据目录。

## 实测内容

| 检查 | 实际结果 |
|---|---|
| `48`、`48.0`、`48e0`、`4.8e1`、`480e-1`、长零尾数等价写法 | 均 valid=true、reward=1 |
| 3 个事件一起使用等价指数写法 | reward=1 |
| `48 + 10^-d`、`48 - 10^-d`，d 为 1、2、6、15、16、17、18、28、29、50、100、1000、10000 | 原始 JSON 文本均被拒绝，reward=0；包括 10,000 位小数尾部的非零差异 |
| 等价的近整数指数写法，与大系数/负指数恰好抵消为 48 的写法 | 真小数均拒绝；恰好为 48 的均得 1 |
| `NaN`、`Infinity`、`-Infinity`、真假 bool、null、字符串数字、负数、小数、非法 JSON 数字 | 均拒绝，reward=0 |
| 正负极端指数与极小非零小数 | 无未处理异常，未出现错误答案满分 |
| 有限但错误的整数，如 `1e999`、`1e999999`、`0`、`49` | valid=true、reward=0.8；只修改非 priority 的 AUTH 数量，正确保留其余 4 个得分单位 |
| Python dict 中 48、48.0 | reward=1 |
| Python dict 中 `math.nextafter(48.0, ±inf)`、bool、NaN、Infinity | 均拒绝，reward=0 |
| 同一个 JSON 键重复出现 48 和 48.0 | 拒绝，reward=0 |

完整 [125 个输入与实际评分](post-fix-run-20261025T111512480014Z/cases.json) 已保存。`1e999` 表示有限的十进制整数，当前 Decimal 路径接受其类型后因业务数量错误失分，是预期行为；不应再将其等同于 JSON `Infinity`。

## 调用方提前丢失精度的边界

另做了一个区分边界的实测，未计为评分器原始 JSON 绕过：

1. 直接把含 `48.000000000000000001` 的最终 JSON 字符串传给当前 `evaluate`：`reward=0, valid=false`。
2. 调用方先对同一字符串执行普通 `json.loads`：Python 浮点值已经变成 `48.0`。
3. 再把这个已改变的 dict 传给 `evaluate`：`reward=1`。

见 [调用方预解析证据](post-fix-run-20261025T111512480014Z/caller-predecode-boundary.json)。第二步发生了不可逆的信息丢失，评分器之后收到的数值本身就是 48；这不是 Decimal 解析仍会舍入的证据。真实 Harness 应直接传递原始模型最终 JSON 字符串，才能同时保留小数精度和重复键信息。仓库中的 `examples/harness_integration.py` 将 agent 返回值原样传给评分器，本次未发现其自行执行这种有损预解析；外部 Harness 未纳入本次执行范围。

## 结论范围

这 125 个检查支持本次改动对等价整数、近整数小数、bool 和非有限数字的处理符合更新后的题面，没有证明任意数值输入或任意外部 Harness 都安全。原报告的 SQLite 大整数受控 fixture 是可信业务 Oracle 的不同层问题；本次未重新运行该 fixture，亦未将数字解析修复表述为它已解决。
