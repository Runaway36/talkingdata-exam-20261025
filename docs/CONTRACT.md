# 冻结实现约定 v3

这是本次考试内形成的告警业务分析任务。业务数据为确定性模拟快照，不连接真实监控平台或企微。

v3 保持 v2 数据结构、业务数值和 Oracle 计算口径，变更任务文本及奖励定义。任务文本保留所有业务规则，不列举解题所需 API 或操作步骤。

## 任务

固定 UTC 窗口 `[2026-10-25T08:00:00Z, 2026-10-25T08:30:00Z)`，5 分钟一个观测桶。分析窗口结束时仍为 firing 的 P0/P1 告警所关联的根因事件。告警不是事件：同一 incident_id 可有多条重复告警。事件影响范围由 incident_services 表提供，不能靠告警标题猜服务。

只统计 production 服务、落在事件影响区间内的完整观测桶；维护状态为 approved 且完整覆盖该桶时排除，cancelled 或只部分覆盖不能排除。模拟数据保证同一 service_id/bucket_start 不同时归属不同根因事件，避免无依据的因果分摊。

每个有效服务桶：`baseline_failures = request_count * baseline_failure_bps // 10000`；`excess_failed_requests = max(0, failed_requests - baseline_failures)`。同一事件/服务/桶只计一次。事件严重等级取符合条件告警中的最高等级。只输出异常失败请求数大于 0 的事件，service_ids 只包括贡献异常失败的服务。计量单位为服务调用失败次数，不是去重用户数，不涉及金额；跨服务的计数不声称等于独立用户请求数。

输出全部符合条件事件的明细，并选出前 2 个优先处理事件。按 excess_failed_requests 降序、严重等级 P0 优先、incident_id 字典序排序。明细行和 service_ids 顺序不影响正确性；priority 数组顺序有意义。

## Python 公开接口

包名 `alert_rlvr`。

- `config.make_task(seed=17) -> str`：规范自然语言任务，首行 `任务编号：alert-impact-v3-seed-{seed}`。
- `config.resolve_task(task: str) -> int`：只接受此版本生成的规范任务文本，支持 CRLF/首尾空白；未知或被篡改任务抛 ValueError；不声称理解任意自然语言。
- `config.snapshot_id(seed) -> str`：`alert-impact-v3-seed-{seed}`，seed 必须为 int（非 bool），0..9999。
- `data.build_database(seed=17) -> sqlite3.Connection`：可信环境内部建库，row_factory=sqlite3.Row。
- `environment.AlertEnvironment(seed=17)`：只读业务 API；`.task`、`.snapshot_id`；上下文管理和 `.close()`。
- 每个 API 返回 `{ok: true, snapshot_id: str, data: list[dict]}`；错误返回 `{ok: false, snapshot_id: str, error: {code: str, message: str}}`，不向 agent 泄露 SQL、数据库路径或异常堆栈。
- `.call(name, arguments)`：严格业务方法白名单，非法 name/参数不导致未捕获异常。
- `.list_alerts(start, end, severities=None, states=None)`：与查询窗口相交的告警（started_at < end 且 ended_at 为 null 或 > start）。
- `.get_incident_services(incident_ids)`：事件服务关系及影响区间。
- `.get_service_profiles(service_ids)`：环境、基线失败率等。
- `.get_request_metrics(service_ids, start, end)`：完整落入查询窗口的观测桶。
- `.get_maintenance_windows(service_ids, start, end)`：与查询窗口相交的维护记录，包括 cancelled。
- `.get_host_metrics(resource_ids)`：主机 CPU、内存使用率及采集时间。
- `.get_notification_history(incident_ids)`：历史通知渠道、送达状态及发送时间。
- `API_SCHEMAS`：环境模块提供 API 名称/描述/参数 JSON schema，供 tool-calling harness 注册。
- 所有 ID 列表最多 50 项；必须为非空字符串列表，拒绝 bool/错误类型；时间使用严格 UTC ISO 格式且 start < end，限制在快照窗口内。

## 数据表契约（列名固定）

- alerts(alert_id TEXT PRIMARY KEY, incident_id TEXT, resource_id TEXT, severity TEXT, state TEXT, started_at TEXT, ended_at TEXT nullable, title TEXT, description TEXT, source TEXT)
- incident_services(incident_id TEXT, service_id TEXT, impact_start TEXT, impact_end TEXT)
- services(service_id TEXT PRIMARY KEY, name TEXT, environment TEXT, baseline_failure_bps INTEGER, owner_team TEXT, dashboard_url TEXT)
- request_metrics(service_id TEXT, bucket_start TEXT, bucket_end TEXT, request_count INTEGER, failed_requests INTEGER, retry_count INTEGER, latency_p95_ms INTEGER)
- maintenance(maintenance_id TEXT PRIMARY KEY, service_id TEXT, starts_at TEXT, ends_at TEXT, status TEXT, reason TEXT)
- host_metrics(resource_id TEXT, cpu_percent REAL, memory_percent REAL, collected_at TEXT)
- notification_history(notification_id TEXT, incident_id TEXT, channel TEXT, delivered INTEGER, sent_at TEXT)

至少包含：重复告警、P2 噪声、resolved 高等级告警、staging 服务、全窗口维护、部分桶维护、取消维护、部分覆盖维护、基线内失败、影响区间外指标。数据随 seed 确定性变化；三个种子应产生不同的数值答案。所有字节/消息均为合成数据。

## 答案与评分

答案为 dict 或 JSON 字符串：
`{snapshot_id, incidents: [{incident_id, severity, service_ids, excess_failed_requests}], priority: [incident_id, ...]}`。

输入资源上限为 `config.MAX_ANSWER_BYTES`，默认 UTF-8 JSON 编码 1,000,000 字节，包含空白字符；超过时返回输入超限错误和 0 分。该限制同时写入模型实际收到的题面，不作为隐藏业务规则。

异常失败量按非负整数值验证：`48`、`48.0`、`48e0` 等价，非零小数部分、bool、字符串数值、NaN/Infinity 不接受。JSON 小数采用精确十进制解析，避免把极小的小数部分舍入成整数。

`verifier.evaluate(task, answer) -> dict` 返回 reward、valid、components（incidents、priority）、errors、expected_count；合法答案报告另含 matched_count、priority_matches、extra_count。`verifier.compute_reward(task, answer) -> float` 为统一训练入口。不接收也不检查调用轨迹。验证器独立从可信快照计算预期结果（SQL 实现），不调用样例解法、不调用 LLM。

合法答案奖励为 `(C + R) / (N + K + X)`：

- N：应输出事件数；K：应输出 priority 长度，即 `min(top_k, N)`。
- C：完整正确事件数，severity、service_ids 集合、excess_failed_requests 三项必须全部正确。
- R：处于正确 priority 位置、且对应事件计入 C 的项数。事件分析有错时，即使排名碰巧正确也不得该位置分。
- X：提交集合中不属于期望集合的额外事件数。

上述公式使用当前配置：`INCIDENT_POINTS=1`、`PRIORITY_POINTS=1`、`EXTRA_INCIDENT_PENALTY=1`。实现分别用这些常量计事件单位、优先级单位与额外事件分母增量。`matched_count=C`、`priority_matches=R`、`extra_count=X`；`components.incidents=C/N`、`components.priority=R/K` 仅解释各类正确比例，对应期望集合为空时提交也为空记 1，否则记 0。

一个完整事件分析与一个正确处置位置各计一个单位，优先事件因此可以贡献两个单位。缺失事件/位置不缩小分母，额外事件扩大分母；没有字段层部分得分。全部期望和提交都为空时 reward=1。默认 N=3、K=2：全对得 1，三个数量全错得 0，正确加一个额外事件得 5/6，默认“一个数量错＋反序 priority”样例得 2/5。

priority 最多 top_k 项，重复或不在提交明细中的 ID 为协议错误；缺项可按上述规则部分得分。快照不匹配、重复事件/服务 ID、非法类型、负数、非有限数、重复 JSON key、未知字段等协议错误 reward=0。不强制明细行或服务列表顺序。

业务配置常量放 config.py。未知任务/非法输入返回错误报告和 0 分，不崩溃。评分报告只供可信控制器使用，不增加逐事件诊断工具；参考答案只在可信评分侧使用。

## 版本与训练范围

seed 目前改变观测数值，事件服务关系、维护等结构仍固定。该分布不保证反复训练后仍需查询全部业务来源，也未覆盖跨结构泛化。v2 的 [模型小样本](../artifacts/model-pilot-v2/README.md) 与 [静态设计审阅](../artifacts/design-review/independent-review.md) 保留原样；其分数不能视为 v3 模型结果。

v3 已在冻结题目与评分器后完成 DeepSeek 非思考模式和 Qwen2.5-1.5B-Instruct 各3实例×4次，严格 pass@4 均为0；两个新上下文 GPT/Codex sub-agent 各独立5次API解对seed17。另有单独列条件的 DeepSeek 思考模式4096 token补充诊断，seed17四次成功一次。原始证据和比较边界见[最终模型评测](../artifacts/model-eval-final/report.md)。真实模型结果没有自然中间分，主要指标采用 `valid and reward == 1` 的严格0/1成功判据；本契约公式保持冻结，不把构造的部分分样例当作连续奖励排序效度证据。没有开展 RL 训练。

## 模块职责

data.py 构造可信快照；environment.py 封装查询；verifier.py 独立计算奖励；examples/reference_agent.py 仅使用业务 API；tests/ 使用独立手算 fixture 验证业务边界。共享配置管理规则常量，求解计算不共享实现函数。更改快照时间范围或业务数据结构时，须同步更新数据生成器并重新验收。
