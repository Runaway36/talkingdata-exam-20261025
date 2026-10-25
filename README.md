# 告警业务影响分析 RLVR

**所选题目：题目一——复杂业务分析 RLVR 任务构建。**

一个单场景、可复现的告警分析任务：Agent 从分散的业务 API 获取告警、事件影响范围、服务资料、请求观测和维护记录，计算各事件的受影响服务和异常失败请求数，给出处置优先级。独立验证器只看最终结果，返回 0～1 奖励，不调用大模型。

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
  "snapshot_id": "alert-impact-v2-seed-17",
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

| 次序 | API | 获取的信息及依赖 |
| --- | --- | --- |
| 1 | `list_alerts(start, end, severities, states)` | 窗口相交的候选告警；去重得到事件 ID，并核对结束时状态 |
| 2 | `get_incident_services(incident_ids)` | 用事件 ID 取得服务 ID 和实际影响区间，不能从告警标题猜关联 |
| 3 | `get_service_profiles(service_ids)` | 生产/测试环境、常态失败率 |
| 4 | `get_request_metrics(service_ids, start, end)` | 每个观测桶的实际请求数和失败数，需要结合第 2、3 步计算 |
| 5 | `get_maintenance_windows(service_ids, start, end)` | 维护批准状态和覆盖时间，决定哪些桶可以计入 |

第 3～5 步可以换序；评分器不规定调用顺序、次数或参数写法。任一 API 都不返回最终事件影响总额或优先级。

环境还提供 `get_host_metrics`、`get_notification_history` 两个冗余接口，以及 owner_team、dashboard_url、retry_count、latency_p95_ms 等非必要字段。CPU 高、消息已发送或 P0 标签都不能代替异常失败量计算。

**调用必要性有业务依据：**相同告警下，改变关联范围、生产环境/常态失败率、实际失败数或维护覆盖，正确答案都会改变。独立反事实测试覆盖这些情况，不用“强制调用满 3 次”代替任务设计。

业务规则公开，隐藏的不是评分条件。需要推导的是查询条件与数据关系，例如旧告警仍可能相关、事件影响只覆盖部分桶、取消维护不能排除、重复告警不能重复累计，以及严重等级不能直接决定排序。

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
reward = 0.25 × 事件覆盖F1
       + 0.50 × 明细字段正确率
       + 0.25 × 优先级位置正确率
```

- 覆盖 F1 = `2 × 正确事件数 / (期望事件数 + 提交事件数)`，同时惩罚漏报和混入事件。
- 明细按 severity、service_ids、excess_failed_requests 三项核对，分母为全部期望事件的字段数；缺失事件不能缩小分母。
- 优先级按正确前 K 项的位置计分；缺项可部分得分。完整正确才能得 1。
- 快照不匹配、重复 ID、重复 JSON key、非法字段或类型、负数、NaN/Infinity 等协议错误得 0，并提供错误原因。

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

- 种子变化用于同一业务场景的数据变化，不代表多业务场景覆盖。
- 合成数据已内置，SQLite 写入发生在初始化阶段；没有模拟真实告警采集延迟、丢包或最终一致性。
- 已做的程序性测试不能证明对某个模型的难度或训练收益；尚未进行真实模型盲测及 RL 训练。
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
