# 题目一：告警业务影响分析 RLVR

**所选题目：题目一——复杂业务分析 RLVR 任务构建。**

**任务已有独立可解证据：两个新上下文的 GPT/Codex sub-agent 分别只用题面与业务工具，各调用 5 次 API，独立解对 seed17 并得满分。** 两次均有逐桶计算和原始工具返回，见[第一次](artifacts/model-eval-final/gpt-subagent-run01/reasoning.md)、[第二次](artifacts/model-eval-final/gpt-subagent-run02/reasoning.md)。这证明该实例可解；GPT 的 Harness、token 预算和部署标识未与其他模型对齐，不能据此制作通用模型排行榜。

一个单场景、可复现的告警分析任务：Agent 从分散的业务 API 获取告警、事件影响范围、服务资料、请求观测和维护记录，计算各事件的受影响服务和异常失败请求数，给出处置优先级。独立验证器只看最终结果，返回 0～1 奖励，不调用大模型。

本项目交付 Python RLVR 任务模块，通过导入方式接入训练控制器；不是 Harbor 任务包。运行样例、测试和 Docker 均不依赖 Harbor。

当前任务版本为 **v3**：保留 v2 的业务数据和正确答案口径，调整题面提示及奖励定义。每个完整正确的事件分析、每个有正确分析支撑的处置位置各计一个得分单位。

业务数据是合成的固定快照，不连接真实监控平台或企微。容器启动自动生成 SQLite 并运行正确、错误及空答案样例，无需凭据、外部服务、下载数据或手工建库。

## 已执行的模型评测

题面、业务代码和评分器在最终批次前冻结，未因模型表现修改。主要成功判据为 `valid and reward == 1`；下列条件分别报告，不合并分母。

| 条件 | 实例与次数 | 严格成功 | pass@1 观测值 | pass@4 观测值 |
|---|---|---:|---:|---:|
| DeepSeek `deepseek-flash`，非思考，1024 输出 token/轮 | seed17/42/99，各4次 | 0/12 | 0 | 0 |
| Qwen2.5-1.5B-Instruct，CUDA BF16，1024 输出 token/轮 | seed17/42/99，各4次 | 0/12 | 0 | 0 |
| DeepSeek `deepseek-flash`，思考模式补充诊断，4096 token/轮 | 仅 seed17，4次 | 1/4 | 0.25 | 1 |
| GPT/Codex sub-agent，两个独立新上下文 | 仅 seed17，各1次 | 2/2 | 不作总体估计 | 未测 |

原定两模型均最多12轮，temperature=0.7、top_p=1，Qwen top_k=0；每次为新 conversation。DeepSeek 服务端采样 seed 不可控。两批均无基础设施错误；Qwen 有5次合法错答、6次非法 final、1次预算内未交 final，后者原始 reward 保持 null。DeepSeek 补充思考模式的三条失败轨迹分别有1、2、3次输出截断，且温度参数被服务端忽略，不能将其与原批直接比较。详细条件、分项和证据见[最终模型评测](artifacts/model-eval-final/report.md)。

**全部自然产生的真实模型分数均为0或1，没有中间分。** 因此本次主要评测报告严格成功率，不声称已验证连续奖励可以排序 Agent 能力；下文冻结公式和作者构造的部分分样例保留，仅用于解释评分规则。没有开展 RL 训练或证明训练收益。

## 快速运行

需要 Python 3.10+（本地实测 3.13），运行依赖只有标准库，包含 sqlite3。以下命令在仓库根目录运行：

```bash
python -m pip install -r requirements.txt
python -m examples.demo
python -m unittest discover -s tests -v
python -m examples.harness_integration
```

Windows 上已安装多个版本时，可将 `python` 换成 `py -3.13`，或使用自己虚拟环境中的解释器。

已实际完成本地 **51/51 测试**，Docker 构建、默认启动、51项测试和外部脚本只读挂载均通过；完整命令与原始日志见[验收记录](docs/VALIDATION.md)。

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

这条路径需要从业务约束推导查询依赖，不能只按题面关键词调用工具。例如：先从告警取得 `incident_id`，再查询关系表得到真实 `service_id` 和影响区间；告警里的 `resource_id=host-db` 不能直接当作服务 ID。`firing` 标签也不足以证明截止时仍活动，必须联合检查 `started_at < cutoff`、`ended_at is null or ended_at > cutoff` 以及严重等级。一个桶是否计入，还要联合比较报告窗口、`impact_start/impact_end`、桶起止时间；维护排除要求同一服务、`status=approved`、维护起止完整覆盖该桶三个条件同时成立。只看到“维护”或“P0”不能直接推出排除或优先处理。

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

适用于具有可信训练控制器的工具使用 RLVR：每次 rollout 创建固定快照，模型在业务工具约束下完成多源关联与聚合，结束后获得可程序验证的终局 reward。它测量给定规则下的工具选择、实体关联、时间例外处理、精确计算与排序；事件归属已由输入给定，不测发现真实故障根因，也不代表全部 agentic 能力。

调用模式见 [harness_integration.py](examples/harness_integration.py)：训练控制器创建环境，把 `task`、工具 schema 和 `env.call` 提供给模型；模型返回最终结果后，由控制器调用验证器。

```python
from alert_rlvr.environment import AlertEnvironment, API_SCHEMAS
from alert_rlvr.verifier import evaluate

def run_training_rollout(model_tool_loop, seed=42):
    with AlertEnvironment(seed=seed) as env:
        final_answer = model_tool_loop(env.task, API_SCHEMAS, env.call)
        report = evaluate(env.task, final_answer)
        if "trusted snapshot could not be evaluated" in report["errors"]:
            raise RuntimeError("Verifier infrastructure failed; exclude this rollout")
        return {
            "reward": report["reward"],
            "success": report["valid"] and report["reward"] == 1.0,
        }
```

`model_tool_loop` 由训练方实现；本项目交付环境与终局评分接口，不包含优化器或已经执行的 RL 训练。运行异常由外层控制器单列，不能冒充模型业务错答；原始 JSON 答案应直接交评分器，避免先转 float 丢失小数精度。

当前异常接口的限制：`compute_reward` 仅返回数值，可信快照建库或评分自身失败时也返回0。训练接入应像上例使用 `evaluate` 检查对应错误，将这类运行排除并记录；不能把该0分当成Agent答错。本次验收未遇到此类评分故障。

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

## 验收与红队范围

双路红队分别检查“正确答案被扣分”和“错误答案得满分”，原始反例、检查范围与处理记录见[红队记录](artifacts/redteam-v3/README.md)。

对齐检查公开了输入大小上限，接受整数值等价的 `48/48.0/48e0` 并精确拒绝非零小数。已有全部10,000个内置 seed 的独立核算、2,535个答案变异和协议检查；这些证据限于当前生成器及已测反例，不是穷尽证明。生成器范围外的 SQLite 大整数风险、固定关系结构的记忆捷径和恶意同进程代码隔离均仍有边界，见[最终独立核查](artifacts/model-eval-final/independent-audit-final.md)。

## Badcase：证据与归因边界

| 原始证据 | 观察 | 支持归因到哪一步 | 不能据此断言 |
|---|---|---|---|
| [DeepSeek原批](artifacts/model-eval-final/deepseek-flash-run01/summary.json) | 65次工具调用均成功，12次合法 final；36个期望事件中等级正确29项、服务集合正确19项，异常量正确0项 | 查询链能执行，部分信息提取成功，最终数量计算/筛选仍有错 | 不能仅从最终错数确定模型内部在哪一步算错，也不能归因于接口不可用 |
| [Qwen seed17 attempt04](artifacts/model-eval-final/qwen25-15b-run01/seed17-attempt04/final_answer.json) | 仅查告警，拿host ID作service ID；AUTH=0、DB=200、PAY缺失 | 实体层级混淆，缺少关系/指标等必要证据便作答 | 不能把它简化为纯算术能力不足 |
| [Qwen seed42 attempt01](artifacts/model-eval-final/qwen25-15b-run01/seed42-attempt01/result.json) | 连续10次用虚构事件ID查询关系，返回空列表，最终无final | 未利用空结果修正查询，固定轮次内未完成 | 工具正常返回空结果，不是环境崩溃 |
| [DeepSeek补充思考诊断](artifacts/model-eval-final/score-order-diagnostic-run01/summary.json) | 4次中1次完整正确，三条失败有输出截断 | 该模型在此实例可成功；失败受当前输出预算影响 | 不能把截断失败直接解释为业务理解不可能，也不能与1024预算原批混评 |

此前网络异常和 Qwen RuntimeError 原样保留；本轮未复现。Qwen 旧日志丢失底层错误，只修复了 traceback 记录，根因仍未确认；运行恢复不等于确认硬件、SDPA或精度根因已修复。

## 复现与限制

```bash
python scripts/validate.py
```

该命令执行测试、3 个 seed 的调用样例和 Harness 样例，写入新的 `artifacts/validation-*` 目录，不覆盖既有结果。实际执行结果见 [验收记录](docs/VALIDATION.md)。

题目一各项要求与文件、实际证据的对应关系见[交付要求映射](docs/REQUIREMENTS.md)。容器验收也可直接执行 `python scripts/validate_container.py`。

模型评测是可选实验，不是默认运行或评分器的依赖。复跑 DeepSeek 原定条件前配置环境变量 `DEEPSEEK_API_KEY`，然后使用新的输出目录：

```bash
python experiments/run_repeated_evaluation.py --backend deepseek --output artifacts/my-deepseek-run
```

本地 Qwen 需另备 Qwen2.5-1.5B-Instruct 权重与 CUDA 推理环境；可选依赖见 [requirements-qwen.txt](experiments/requirements-qwen.txt)。脚本不会下载权重或失败后自动切换 CPU：

```bash
python experiments/run_repeated_evaluation.py --backend qwen --output artifacts/my-qwen-run --local-python /path/to/python --model-path /path/to/Qwen2.5-1.5B-Instruct
```

以上各运行3个固定实例、每个4次独立作答。任意真实模型复跑不保证产生相同答案；业务快照与评分确定性、模型输出随机性须区分。已有原始轨迹可由 `python artifacts/model-eval-final/independent-audit-check.py` 离线核对，无需再次调用模型。

- 种子变化用于同一固定业务结构下的数值变化；未实现关系、维护和告警结构随机化，不能据此证明跨结构泛化。
- 配置常量便于定位规则，但数据生成器仍固定日期、六个五分钟桶。窗口或桶长的变更须同步修改生成器并重新验收，不能只改 `BUCKET_MINUTES` 就视为新任务已正确配置。
- 合成数据已内置，SQLite 写入发生在初始化阶段；没有模拟真实告警采集延迟、丢包或最终一致性。
- v2 的 [真实模型小样本记录](artifacts/model-pilot-v2/README.md) 与 [独立上下文设计审阅](artifacts/design-review/independent-review.md) 原样保留。v3 已完成上列独立模型评测；新旧题面、奖励、温度及预算不相同，不能将分差只归因于任务修改。未开展 RL 训练。
- 当前为小数据快照、单次分析任务；没有建设实时流平台、通知发送链路或线上权限系统。
- 模型或训练基础设施异常应由 Harness 单独记录，不等同于模型提交错误业务结果。

## 目录

```text
alert_rlvr/   config、SQLite 数据、业务 API、独立验证器、可选工具进程
examples/     API 参考解、正确/错误样例、训练控制器与挂载调用示例
tests/        独立手算边界、反事实、协议及集成验收
scripts/      可复现验收入口
experiments/  可选真实模型评测、独立作答桥接及本地推理驱动
docs/         任务契约、接口定义、实际验收记录
artifacts/    本次运行的机器可读证据
Dockerfile    单容器入口（自动运行样例）
```
