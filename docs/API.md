# 业务 API 定义

全部方法在 `AlertEnvironment` 类中，以 Python 类方法实现。模型调用推荐使用 `env.call(name, arguments)`，它只允许下表七个名称，参数错误返回结构化错误。可信 Python 控制器也可直接调用这些业务方法。

成功：`{"ok":true,"snapshot_id":"...","data":[...]}`。
失败：`{"ok":false,"snapshot_id":"...","error":{"code":"INVALID_ARGUMENT","message":"..."}}`。

每次环境实例对应一个不可变快照；新实例使用相同 seed 时重建同样的数据。没有 SQL 查询入口或文件路径参数。所有查询使用参数绑定，未知 ID 返回空列表。

## 通用参数

- 时间：严格 UTC `YYYY-MM-DDTHH:MM:SSZ`，须在报告窗口内且 start < end。查询区间右端不包含；指标只返回完整落入区间的观测桶。
- ID：非空字符串列表，1～50 项；重复查询 ID 自动去重，未知 ID 不产生伪记录。
- 可选 severity：P0/P1/P2/P3；可选 state：firing/resolved/suppressed。未提供时不过滤。
- `call` 拒绝未知工具、非 dict 参数及未知参数。环境关闭后返回 `ENVIRONMENT_CLOSED`；数据库读取错误返回 `DATA_UNAVAILABLE`。

| 方法 | 参数 | 主要返回字段 | 业务意义 |
| --- | --- | --- | --- |
| list_alerts | start, end, severities=None, states=None | alert_id, incident_id, resource_id, severity, state, started_at, ended_at, title, description, source | 窗口相交告警。相交不等于在结束时仍活动，调用者需结合结束时间 |
| get_incident_services | incident_ids | incident_id, service_id, impact_start, impact_end | 根因事件影响服务与时间，不能依据标题猜测 |
| get_service_profiles | service_ids | service_id, name, environment, baseline_failure_bps, owner_team, dashboard_url | 生产环境筛选、常态失败率参数 |
| get_request_metrics | service_ids, start, end | service_id, bucket_start, bucket_end, request_count, failed_requests, retry_count, latency_p95_ms | 实际计数；单独不能算有效异常失败量 |
| get_maintenance_windows | service_ids, start, end | maintenance_id, service_id, starts_at, ends_at, status, reason | 返回所有相交维护，不替调用者过滤取消或部分覆盖 |
| get_host_metrics | resource_ids | resource_id, cpu_percent, memory_percent, collected_at | 冗余诊断数据 |
| get_notification_history | incident_ids | notification_id, incident_id, channel, delivered, sent_at | 冗余历史通知数据，不发生发送副作用 |

参数 JSON Schema 通过 `API_SCHEMAS` 导入或 `python -m alert_rlvr.tools --catalog` 获取。字段单位及业务计算以 `make_task(seed)` 与 [任务契约](CONTRACT.md) 为准。

## 真实调用示例

```python
from alert_rlvr.environment import AlertEnvironment

with AlertEnvironment(seed=17) as env:
    result = env.call("list_alerts", {
        "start": "2026-10-25T08:00:00Z",
        "end": "2026-10-25T08:30:00Z",
        "severities": ["P0", "P1"],
        "states": ["firing"]
    })
    assert result["ok"]
    print(result["data"])
```

默认 seed 的典型路径返回行数分别是 7 条告警、8 条事件服务关系、8 条服务资料、48 个指标桶、6 条维护。末尾得到 3 个正影响事件；完整返回样例和每步两行数据节选保存在实际运行的 demo JSON 中。
