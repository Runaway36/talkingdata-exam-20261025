# 告警业务影响分析 RLVR

**所选题目：题目一——复杂业务分析 RLVR 任务构建。**

一个单场景、可复现的告警分析任务：Agent 从分散的业务 API 获取告警、事件影响范围、服务资料、请求观测和维护记录，计算各事件的受影响服务和异常失败请求数，给出处置优先级。独立验证器只看最终结果，返回 0～1 奖励，不调用大模型。

本项目交付 Python RLVR 任务模块，通过导入方式接入训练控制器；不是 Harbor 任务包。运行样例、测试和 Docker 均不依赖 Harbor。

当前任务版本为 **v3**：保留 v2 的业务数据和正确答案口径，调整题面提示及奖励定义。每个完整正确的事件分析、每个有正确分析支撑的处置位置各计一个得分单位。

业务数据是合成的固定快照，不连接真实监控平台或企微。容器启动自动生成 SQLite 并运行正确、错误及空答案样例，无需凭据、外部服务、下载数据或手工建库。

## 快速运行

需要 Python 3.10+（本地实测 3.13），运行依赖只有标准库，包含 sqlite3。以下命令在仓库根目录运行：

```bash
python -m pip install -r requirements.txt
python -m examples.demo
python -m unittest discover -s tests -v
python -m examples.harness_integration
```

Windows 上已安装多个版本时，可将 `python` 换成 `py -3.13`，或使用自己虚拟环境中的解释器。

Docker：

```bash
docker build -t alert-rlvr .
docker run --rm --network none alert-rlvr
docker run --rm --network none alert-rlvr python -m unittest discover -s tests -v
docker run --rm --network none alert-rlvr python -m examples.demo --seed 42
```

默认样例输出任务、5 次业务 API 调用的参数/返回行数/部分数据、最终答案以及每个场景的分项奖励。它是程序性演示，不是模型能力评测或预生成训练轨迹。

## 任务输入与答案

```python
from alert_rlvr.config import make_task
task_text = make_task(seed=17)
```

完整自然语言任务由该函数返回。报告窗口为 UTC `[2026-10-25 08:00, 08:30)`，每个观测桶 5 分钟。

业务规则：

1. 处理截至窗口结束仍在触发的 P0/P1 告警；窗口之前发生但尚未结束的告警也可能相关。按 `incident_id` 合并重复告警，不能把已恢复的 P0 严重等级继承给仍活动的 P1。
2. 通过事件服务关系确定影响范围，只分析 production 服务；观测桶须完整落入报告窗口和事件影响区间。
3. approved 维护完整覆盖的桶不计影响。cancelled 维护和部分覆盖不排除，不能仅因“存在维护记录”就忽略服务。
4. 每桶常态失败数为 `request_count * baseline_failure_bps // 10000`，异常失败数为 `max(0, failed_requests - 常态失败数)`。
5. 同一事件/服务/桶仅计一次，按服务观测桶累加异常失败数；不用告警条数代替影响量。
6. 输出所有存在异常失败的事件及对应服务；按异常失败量降序、严重等级、事件 ID 排序选前 2 个。P1 的异常失败量可以大于 P0。

例如某服务桶有 1000 次请求、30 次失败，常态失败率为 100 bps（1%），异常失败量为 `30 - 1000×100//10000 = 20`；两条重复告警仍只计 20 次，approved 维护若完整覆盖该桶则不计入。这里统计的是服务调用失败次数，跨服务统计不等同于去重用户数或独立用户请求数。模拟数据保证同一个服务桶不归属多个根因事件；真实系统中的多故障因果归因不在此任务范围。

答案格式（以下为默认 seed=17 的可复现答案）：

```json
{
  "snapshot_id": "alert-impact-v3-seed-17",
  "incidents": [
    {"incident_id":"INC-AUTH","severity":"P1","service_ids":["svc-auth"],"excess_failed_requests":48},
    {"incident_id":"INC-DB","severity":"P0","service_ids":["svc-checkout","svc-search"],"excess_failed_requests":174},
    {"incident_id":"INC-PAY","severity":"P1","service_ids":["svc-pay"],"excess_failed_requests":120}
  ],
  "priority": ["INC-DB", "INC-PAY"]
}
```

明细行和 `service_ids` 顺序不影响奖励；`priority` 顺序有业务含义。seed 改变观测值，因此其他 seed 不能复用上述数字。

## API 与典型路径

`AlertEnvironment` 是 Python 类，不需要 HTTP 服务或多容器通信。各接口返回 JSON 兼容的数据；字段完整定义见 [接口文档](docs/API.md) 和 `environment.API_SCHEMAS`。

下面是作者提供的参考执行路径；Harness 给模型的输入只有任务文本和工具 schema，不包括这张路径表。

| 次序 | API | 获取的信息及依赖 |
| --- | --- | --- |
| 1 | `list_alerts(start, end, severities, states)` | 窗口相交的候选告警；取得事件 ID，并核对截止时仍活动的告警 |
| 2 | `get_incident_services(incident_ids)` | 用事件 ID 查询服务及影响区间，取得后续查询的服务 ID |
| 3 | `get_service_profiles(service_ids)` | 服务环境和常态失败率，决定生产环境筛选与基线计算 |
| 4 | `get_request_metrics(service_ids, start, end)` | 请求数和失败数，结合关系区间及基线计算异常量 |
| 5 | `get_maintenance_windows(service_ids, start, end)` | 维护状态和覆盖时间，决定排除哪些观测桶 |

第 3～5 步可以换序。评分器不规定调用顺序、次数或参数写法；题面给出完整业务规则，不列解题所需 API 清单或执行步骤。

`get_host_metrics` 返回主机 CPU、内存使用率及采集时间；`get_notification_history` 返回历史通知渠道、送达状态和发送时间。二者不参与本题的异常失败计数，是供工具选择的冗余业务信息；owner_team、dashboard_url、retry_count、latency_p95_ms 也不进入计算。模型可见的工具描述只说明返回内容，不直接标注“冗余”。

改变关联范围、生产环境/常态失败率、实际失败数或维护覆盖会改变正确答案，独立反事实测试覆盖这些依赖。当前 seed 主要改变指标数值，关系与维护等结构仍固定；反复训练可能记住这些结构，因此这些测试不证明训练后的策略每次仍必须查询全部来源。

## 奖励与验证

```python
from alert_rlvr.config import make_task
from alert_rlvr.verifier import compute_reward, evaluate

reward = compute_reward(make_task(17), final_answer)  # float in [0, 1]
details = evaluate(make_task(17), final_answer)       # 分项解释
```

`final_answer` 可以是 Python dict 或 JSON 字符串。输入任务是本版本 `make_task(seed)` 产生的自然语言文本；验证器校验任务版本和全文，不声称能解释任意改写的自然语言需求。

对于协议合法答案：

```text
reward = (C + R) / (N + K + X)
```

`config.py` 中 `INCIDENT_POINTS`、`PRIORITY_POINTS`、`EXTRA_INCIDENT_PENALTY` 当前均为 1，分别对应事件得分单位、优先级得分单位和多报事件的分母增量。

| 符号 | 含义 |
| --- | --- |
| N | 应输出的事件数 |
| K | 应输出的 priority 长度，即 `min(top_k, N)` |
| C | 完整正确的事件数：severity、service_ids 集合、excess_failed_requests 三项必须全部正确 |
| R | ID 位置正确且对应事件分析完整正确的 priority 项数 |
| X | 提交了但不属于期望集合的额外事件数 |

一个完整正确的事件分析计一个单位，一个正确且有完整分析支撑的处置位置再计一个单位。因此，优先事件可以贡献两个单位；只猜中事件、部分字段或排名不单独得分。缺失保留在分母内，额外事件增加分母。全部期望和提交都为空时得 1；其余情况完整正确才得 1。

默认快照有 3 个事件和 2 个优先位置：

| 构造答案 | reward |
| --- | --- |
| 全部正确 | `5/5 = 1` |
| 三个异常失败数量全部错误，其他字段和排名正确 | `0/5 = 0` |
| 正确答案额外添加一个事件 | `5/6` |
| 默认错误样例：一个数量错误，并反转两个 priority 位置 | `2/5 = 0.4` |

快照不匹配、重复 ID、重复 JSON key、非法字段或类型、负数、NaN/Infinity 等协议错误得 0。合法答案的 `evaluate` 报告包含 `matched_count`（C）、`priority_matches`（R）、`extra_count`（X）；`components.incidents=C/N`、`components.priority=R/K` 是解释性比例，不是另一次加权评分。对应期望集合为空时，该分项在提交也为空时为 1，否则为 0。协议错误报告给出错误原因及零分，不提供逐事件诊断查询接口。

验证器通过独立 SQL 在可信快照上计算真值；样例解法使用业务 API 和 Python 循环，二者不共享求解函数。评分输入没有工具轨迹。对照测试包含正确答案、漏事件、混入事件、错误数量/排序、重复提交、等价排序，以及错误边界实现应失败的手算数据。

## 训练 Harness 接入

调用模式见 [harness_integration.py](examples/harness_integration.py)：训练控制器创建环境，把 `task`、工具 schema 和 `env.call` 提供给模型；模型返回最终结果后，由控制器调用验证器。

```python
from alert_rlvr.environment import AlertEnvironment, API_SCHEMAS
from alert_rlvr.verifier import compute_reward

with AlertEnvironment(seed=42) as env:
    # 模型收到 env.task 和 API_SCHEMAS，只允许调用 env.call(name, arguments)。
    # final_answer = your_model_tool_loop(env.task, API_SCHEMAS, env.call)
    # reward = compute_reward(env.task, final_answer)
    pass
```

另提供可运行的 JSONL 业务工具进程：

```bash
python -m alert_rlvr.tools --catalog
python -m alert_rlvr.tools --seed 17
```

stdin 每行请求形如 `{"id":1,"tool":"get_service_profiles","arguments":{"service_ids":["svc-pay"]}}`，stdout 每行一个响应。工具白名单不含 SQL、评分器或参考答案。

挂载本地训练脚本（POSIX shell，PowerShell 可用绝对路径代替 `$(pwd)`）：

```bash
docker run --rm --network none \
  --mount "type=bind,source=$(pwd)/examples,target=/workspace,readonly" \
  alert-rlvr python /workspace/mounted_controller.py
```

镜像设置 `PYTHONPATH=/app`，因此挂载脚本可以直接导入 `alert_rlvr`。内置模块在镜像内，挂载只用于外部控制器代码。

**边界：**Python 类的私有连接是接口约定，不是防恶意同进程 Python 代码的沙箱。可信 Harness 持有数据库和验证器，只把业务工具暴露给模型；有任意文件/代码执行权限的模型不能与可信评分器共享文件权限。JSONL 进程是可选接入方式，不宣称单容器能抵御任意攻击。

## 复现、验收与限制

```bash
python scripts/validate.py
```

该命令执行测试、3 个 seed 的调用样例和 Harness 样例，写入新的 `artifacts/validation-*` 目录，不覆盖既有结果。实际执行结果见 [验收记录](docs/VALIDATION.md)。

- 种子变化用于同一固定业务结构下的数值变化；未实现关系、维护和告警结构随机化，不能据此证明跨结构泛化。
- 合成数据已内置，SQLite 写入发生在初始化阶段；没有模拟真实告警采集延迟、丢包或最终一致性。
- v2 已完成两个模型、三个 seed 各一次的 [真实模型小样本记录](artifacts/model-pilot-v2/README.md)，并保留 [独立上下文设计审阅](artifacts/design-review/independent-review.md)。这些是旧题面、旧奖励的证据；v3 尚待模型评测，未开展 RL 训练。
- 当前为小数据快照、单次分析任务；没有建设实时流平台、通知发送链路或线上权限系统。
- 模型或训练基础设施异常应由 Harness 单独记录，不等同于模型提交错误业务结果。

## 目录

```text
alert_rlvr/   config、SQLite 数据、业务 API、独立验证器、可选工具进程
examples/     API 参考解、正确/错误样例、训练控制器与挂载调用示例
tests/        独立手算边界、反事实、协议及集成验收
scripts/      可复现验收入口
docs/         任务契约、接口定义、实际验收记录
artifacts/    本次运行的机器可读证据
Dockerfile    单容器入口（自动运行样例）
```
