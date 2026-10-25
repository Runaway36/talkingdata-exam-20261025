# v3 false-negative 定向复核

2026-10-25。原 `report.md` 及原证据保持不变，仍对应修订前业务/评分基准 commit `4cef31f`。本文件记录长度契约及整数值 JSON 修订后的定向结果，不替代原来的全 seed 审计。

**结论：本次指定的两项收敛均通过。** 原 FN-01 的资源边界已向模型和契约公开；原 A-01 的整数 JSON 表示歧义已明确接受数值等价写法，实测 `.0`/`e0` 得满分。非零极小小数没有被舍入成整数而通过。

## 实际复核

只读检查 `config.make_task`、`verifier._parse_answer/_validate_answer` 和 `docs/CONTRACT.md`，再用原独立 API 算法重新获得 seed 17 答案，执行 **16 项针对性调用**。未重新扫 10,000 seed，未把 root 报告的 51 项测试当成本 agent 的执行结果。

| 检查项 | 实测结果 |
|---|---|
| 当前题面明确 `1000000 字节（包含空白字符）`，超限得 0 | 已包含 |
| CONTRACT 明确 `1,000,000 字节，包含空白字符` | 已包含 |
| 当前题面明确 `48、48.0、48e0` 数值等价 | 已包含 |
| 原整数 JSON、全部数量改 `.0`、改 `e0` | 各 reward=1，valid=true |
| 带很多尾随零的小数整数值；`480e-1` 等指数移位整数值 | 各 reward=1，valid=true |
| Python dict 中的有限整数值 float | reward=1，valid=true |
| `48.00000000000000000000000000000000000001` | reward=0，valid=false |
| `47.99999999999999999999999999999999999999` | reward=0，valid=false |
| `1e-10000` | reward=0，valid=false |
| `48.5`、`true`、`"48"`、`NaN`、`Infinity` | 各 reward=0，valid=false |
| 正确 JSON 加空白，总计 1,000,000 bytes | reward=1，valid=true |
| 再加 1 个空格，总计 1,000,001 bytes | reward=0，valid=false；`answer exceeds byte limit` |

上述数值调用同时核对 `evaluate` 报告和统一入口 `compute_reward`。大小边界仍然拒绝超限输入，但现在是题面已披露的格式限制，不再属于原 FN-01 的隐藏规则。

源码检查确认 JSON 的小数和指数数字由 `parse_float=Decimal` 精确读取；验证采用有限性与精确整数值比较，没有先转二进制 float。正、负方向接近 48 的两个极小非零小数均被拒绝，证明这些具体反例未被舍入成 48。Python dict 在调用前若已被调用者计算成某个 float，无法恢复调用者早先丢失的精度；本结论针对传入 JSON 数字文本的精确保留，不声称可追溯外部既有舍入。

## 复现与证据

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
python artifacts/redteam-v3/false-negative/post_fix_probe.py
```

本次证据目录：`post-fix-evidence-20261025T111417765112Z/`。

- `targeted-results.json`：16 项完整输入、预期、实际报告、实际 reward；5 项契约披露检查；`all_pass=true`。
- `current-task-seed-17.txt`：本次模型实际题面。
- `independent-answer-seed-17.json`：重新通过公开业务 API 独立计算的答案。
- `source-hashes.json`：本次被读 config、verifier、CONTRACT 的 SHA-256，便于区分后续变更。

未修改业务实现、旧报告或旧结果。G-01/G-02 仍是原报告中的当前生成器不可达大整数边界；这次未重跑、未扩展算法范围，也未宣称它们已经修复。
