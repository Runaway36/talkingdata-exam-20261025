# 题目一交付要求映射

所选方向：复杂业务分析 RLVR 任务构建。下表将要求对应到实现及已执行证据；运行示例、验证器测试和真实模型评测分别说明，不互相替代。

最终加固后本地与Docker均60项通过，默认数据及已保存评分与模型评测版本兼容；配置联动和可信评分故障分流见[FINAL_HARDENING.md](FINAL_HARDENING.md)。表中51项记录为模型评测前已执行的原始证据。

| 要求 | 交付位置与可核验实现 | 证据及解释边界 |
|---|---|---|
| 单一复杂业务场景 | [config.py](../alert_rlvr/config.py) 的 `make_task`：告警业务影响分析与处置排序 | 已给定根因事件 ID，要求关联、过滤、计算、排序，不声称发现未知故障根因 |
| 至少三个必要且独立的业务 API | [environment.py](../alert_rlvr/environment.py)：告警、事件服务关系、服务档案、请求指标、维护记录五类 API | 关系提供服务与影响区间；档案提供环境与基线；指标提供请求/失败数；维护决定桶是否排除。[test_reward.py](../tests/test_reward.py) 的必要来源反事实测试分别改变四类数据，使旧答案失去满分；不靠调用次数证明必要性 |
| 跨 API 关联与计算 | [reference_agent.py](../examples/reference_agent.py)：incident_id → service_id → 观测桶，结合基线和维护计算 | 只通过业务 API 求解；[默认样例实际产物](../artifacts/validation-20261025T111622025933Z/demo-17.json) 记录五次调用与结果 |
| 冗余数据与工具选择 | `get_host_metrics`、`get_notification_history`；owner_team、dashboard_url、retry_count、latency_p95_ms 等字段 | 冗余数据不进入公式；对应反事实测试确认修改这些值不改变答案。模型工具说明不直接标注“冗余” |
| 需由字段推导的业务约束 | [题面与规则](../alert_rlvr/config.py)：截止状态、等级合并、production、完整影响桶、approved 完整维护、基线取整、正贡献服务 | API 不直接返回异常失败总量、正确事件集合或 priority；需结合多源字段判断 |
| 挑战与可完成性证据 | [独立最终模型审计](../artifacts/model-eval-final/independent-audit-final.md) | 主批两模型共 24 次未严格通过；独立附加条件与 GPT 作答存在正确结果。仅支持记录条件下的表现，不证明总体难度、跨结构泛化或分数能细分所有错答 |
| SQLite 模拟数据 | [data.py](../alert_rlvr/data.py) 创建确定性内存 SQLite；初始化后 query_only | 模拟快照内置，无凭据、真实平台或手工建库要求 |
| Python 类封装 API，不向模型注册裸数据库 | `AlertEnvironment` 与 `API_SCHEMAS`；[tools.py](../alert_rlvr/tools.py) 可选 JSONL 白名单工具进程 | 模型可见入口没有 SQL、数据库连接、评分器或标准答案。私有属性不是恶意同进程 Python 的安全沙箱；隔离由可信 Harness 负责 |
| 独立统一奖励入口 | [verifier.py](../alert_rlvr/verifier.py) 的 `compute_reward(task, answer) -> float` 与 `evaluate` | 接受规范自然语言任务和最终 dict/JSON，输出 [0,1]；真值由独立 SQL 计算，不调用样例解法、LLM 或调用轨迹。只识别此版本注册题面，不声称解析任意自然语言改写 |
| 正误示例 | [demo.py](../examples/demo.py)：正确、错数量且反序 priority、空答案 | 三个 seed 实际分别得 1、0.4、0；这些是作者构造的程序对照，不是真实模型中间分证据 |
| 配置解耦与依赖清晰 | [config.py](../alert_rlvr/config.py) 集中窗口、seed、top-k、权重和输入限制；[requirements.txt](../requirements.txt) 声明核心仅标准库 | 本地模型实验的 PyTorch/Transformers 属于可选实验运行条件，不是业务环境或评分器依赖；改变数据结构仍须同步重新验收 |
| 异常处理 | 环境统一错误结构、`.call` 参数/白名单检查；评分器非法输入返回 0 和错误；样例保留非零异常退出 | [tests](../tests) 覆盖格式、类型、重复键、非有限数、非法 API、关闭环境等；模型运行异常与错答分开记录 |
| Docker 默认示例 | [Dockerfile](../Dockerfile)：Python 3.13、非 root 用户、`CMD python -m examples.demo` | [实际容器验收](../artifacts/container-validation-20261025T111622006031Z/summary.json)：构建、默认运行、51 项测试均通过；运行时禁网、只读文件系统 |
| 挂载外部训练脚本 | 镜像 `PYTHONPATH=/app`；[mounted_controller.py](../examples/mounted_controller.py) 导入镜像内环境与奖励入口 | 同一容器验收记录包含只读 bind mount 的外部脚本调用，seed42 reward=1 |
| README 所选题目、运行与验收 | [README](../README.md)；[API](API.md)；[CONTRACT](CONTRACT.md)；[VALIDATION](VALIDATION.md) | README 提供题目选择、Python/Docker 命令、答案/奖励、Harness 和挂载方式；原始验收记录链接到真实执行产物 |

核心程序验收依据为 [本地验收汇总](../artifacts/validation-20261025T111622025933Z/summary.json) 与 [容器验收汇总](../artifacts/container-validation-20261025T111622006031Z/summary.json)。单元与手算对照验证实现是否遵守规则；模型评测评价既定 Harness、预算和实例上的实际完成情况。当前主要模型判据是严格完整通过/未通过，未用作者构造部分分数代替模型分数排序证据。
