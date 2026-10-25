# seed 17 原始 API 记录独立算术核对

核对日期：2026-10-25（北京时间）。

**独立复算确认：`INC-DB=174`、`INC-PAY=120`、`INC-AUTH=48`；优先级为 `["INC-DB","INC-PAY"]`。**

本报告是原始 API 记录的独立算术核对，不是 LLM 正式作答轨迹，也不代表全数据分布的 oracle 正确性。范围仅为 `alert-impact-v2-seed-17` 及下述已保存的这一次运行记录。

复算仅使用 `deepseek-flash-seed17-run01/initial_input.json` 和 `turn-01-tool.json` 至 `turn-06-tool.json`。没有读取模型最终答案或评分文件，没有导入参考解、验证器或建库代码，也未修改业务实现、运行模型。本报告由此前已完成的只读核对整理而来，保存报告时没有重跑。

## 原始证据

- 任务规则：[initial_input.json](deepseek-flash-seed17-run01/initial_input.json)
- 告警：[turn-01-tool.json](deepseek-flash-seed17-run01/turn-01-tool.json)
- 事件服务关系：[turn-02-tool.json](deepseek-flash-seed17-run01/turn-02-tool.json)
- 服务资料：[turn-03-tool.json](deepseek-flash-seed17-run01/turn-03-tool.json)
- 维护记录：[turn-04-tool.json](deepseek-flash-seed17-run01/turn-04-tool.json)
- production 请求观测：[turn-05-tool.json](deepseek-flash-seed17-run01/turn-05-tool.json)
- staging 请求观测：[turn-06-tool.json](deepseek-flash-seed17-run01/turn-06-tool.json)

返回的 7 条合格告警对应 5 个事件，DB 的三条告警只合并为一个事件。每桶按 `request_count * baseline_failure_bps // 10000` 扣减基线，再取 `max(0, failed_requests - baseline_failures)`。仅计完整落入事件影响区间的 production 服务桶；approved 维护必须完整覆盖桶才排除。所有时间均为 UTC。

## 计入桶逐项核算

| 服务 | UTC 桶 | 请求数 | 原失败数 | 基线失败数 | 计入异常数 |
|---|---|---:|---:|---:|---:|
| svc-auth，100 bps | 08:00–08:05 | 1079 | 19 | 10 | 9 |
| svc-auth | 08:10–08:15 | 1144 | 22 | 11 | 11 |
| svc-auth | 08:15–08:20 | 1103 | 21 | 11 | 10 |
| svc-auth | 08:20–08:25 | 1151 | 21 | 11 | 10 |
| svc-auth | 08:25–08:30 | 1064 | 18 | 10 | 8 |
| svc-checkout，100 bps | 08:05–08:10 | 1077 | 46 | 10 | 36 |
| svc-checkout | 08:10–08:15 | 1196 | 50 | 11 | 39 |
| svc-checkout | 08:15–08:20 | 1028 | 41 | 10 | 31 |
| svc-checkout | 08:20–08:25 | 1191 | 48 | 11 | 37 |
| svc-search，300 bps | 08:10–08:15 | 1141 | 49 | 34 | 15 |
| svc-search | 08:15–08:20 | 1050 | 47 | 31 | 16 |
| svc-pay，50 bps | 08:00–08:05 | 1090 | 23 | 5 | 18 |
| svc-pay | 08:05–08:10 | 1148 | 23 | 5 | 18 |
| svc-pay | 08:10–08:15 | 1061 | 24 | 5 | 19 |
| svc-pay | 08:15–08:20 | 1063 | 28 | 5 | 23 |
| svc-pay | 08:20–08:25 | 1016 | 27 | 5 | 22 |
| svc-pay | 08:25–08:30 | 1154 | 25 | 5 | 20 |

## 维护与区间排除核查

- **auth：**08:05–08:10 的原失败数 21、基线 11，原本异常 10，但被 `M-AUTH-BUCKET` 完整覆盖且为 approved，计入 0。08:10–08:15 的维护为 cancelled，仍计入；08:17–08:19 只部分覆盖 08:15–08:20 桶，仍计入。因此 `9+11+10+10+8=48`。
- **checkout：**事件影响区间为 08:05–08:25。08:00–08:05 和 08:25–08:30 均不计；这两个桶各为 `611−11=600`，不能混入事件。08:11–08:14 的 approved 维护不完整覆盖任何桶，因此中间四桶全部有效，`36+39+31+37=143`。
- **search：**影响区间为 08:07–08:23，仅 08:10–08:15、08:15–08:20 完整落入。其余四桶均排除；对应原失败数为 `534、535、534、535`，基线为 `34、35、34、35`，每桶原异常 500，但不能计入。因此 `15+16=31`。
- **pay：**影响区间覆盖六桶；全窗口维护状态为 cancelled，六桶都计入。`18+18+19+23+22+20=120`。

## 零贡献服务和事件

| 对象 | 原始数据与规则 | 结论 |
|---|---|---|
| `INC-BASE / svc-baseline` | 六桶失败数 `115,105,98,111,110,110`；1000 bps 基线 `116,106,101,112,113,111` | 每桶 `max(0,失败−基线)=0`，事件不输出 |
| `INC-LOG / svc-log` | 六桶失败数 `406,440,420,498,484,469`，但 approved 维护完整覆盖 08:00–08:30 | 六桶全部排除，事件不输出 |
| `INC-DB / svc-cart` | 六桶失败数 `22,18,19,17,21,22`；200 bps 基线 `22,20,22,20,21,22` | 每桶异常为 0，不列入 DB 的 `service_ids` |
| `INC-PAY / svc-pay-stage` | 服务资料明确为 staging | 全部排除，不列入 PAY 的 `service_ids` |

## 独立汇总结果

DB 汇总为 `143+31=174`；PAY 为 120；AUTH 为 48。按异常失败请求数降序，前两名为 DB、PAY。本例数值不相等，无需使用严重等级或 incident_id 的并列排序规则。

```json
{
  "snapshot_id": "alert-impact-v2-seed-17",
  "incidents": [
    {
      "incident_id": "INC-AUTH",
      "severity": "P1",
      "service_ids": ["svc-auth"],
      "excess_failed_requests": 48
    },
    {
      "incident_id": "INC-DB",
      "severity": "P0",
      "service_ids": ["svc-checkout", "svc-search"],
      "excess_failed_requests": 174
    },
    {
      "incident_id": "INC-PAY",
      "severity": "P1",
      "service_ids": ["svc-pay"],
      "excess_failed_requests": 120
    }
  ],
  "priority": ["INC-DB", "INC-PAY"]
}
```

这些数值来自 API 原始记录逐桶计算，未将已有答案中的数值作为输入或断言。该核对确认本例的“原始记录 → 任务规则 → 汇总答案”链条，不证明数据生成规则、所有其他 seed 或完整评分实现不存在错误。
