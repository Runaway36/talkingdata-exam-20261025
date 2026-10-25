"""Versioned, shared business parameters and canonical task registration."""
import re

DEFAULT_SEED = 17
MAX_SEED = 9999
TASK_VERSION = 3
WINDOW_START = "2026-10-25T08:00:00Z"
WINDOW_END = "2026-10-25T08:30:00Z"
BUCKET_MINUTES = 5
TOP_K = 2
MAX_IDS = 50
MAX_ANSWER_BYTES = 1_000_000
SEVERITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
ELIGIBLE_SEVERITIES = ("P0", "P1")
ACTIVE_STATE = "firing"
PRODUCTION_ENVIRONMENT = "production"
APPROVED_MAINTENANCE = "approved"
BASIS_POINTS = 10_000
INCIDENT_POINTS = 1
PRIORITY_POINTS = 1
EXTRA_INCIDENT_PENALTY = 1


def validate_seed(seed):
    if type(seed) is not int or not 0 <= seed <= MAX_SEED:
        raise ValueError(f"seed must be an integer in [0, {MAX_SEED}]")
    return seed


def snapshot_id(seed=DEFAULT_SEED):
    return f"alert-impact-v{TASK_VERSION}-seed-{validate_seed(seed)}"


def make_task(seed=DEFAULT_SEED):
    return f"""任务编号：{snapshot_id(seed)}
你是监控平台的值班分析员，需要为下一班提供一份按实际业务影响排序的处置清单。
报告范围是 UTC [{WINDOW_START}, {WINDOW_END})；纳入截至窗口结束仍在触发（firing）的 P0/P1 告警所对应根因事件。
请给出各事件影响的生产服务、异常失败调用总量，并选出优先处理的前 {TOP_K} 个事件。

交接统计制度：
一个根因事件以 incident_id 标识，可有多条告警；事件等级取符合纳入条件告警中的最高等级。
服务归属及影响起止时间以事件登记关系为准；只统计环境为 production 的服务。
统计单位是服务调用失败次数，不是去重用户数，不涉及金额。每个 {BUCKET_MINUTES} 分钟观测桶须完整处于报告范围和事件影响时段内，同一事件、服务、桶只计一次。
已批准（approved）的计划维护完整覆盖的桶不属于事件业务影响；取消（cancelled）或只覆盖部分时间的维护不适用这一豁免。
常态失败量按每桶请求量与该服务基线计算并向下取整：request_count * baseline_failure_bps // {BASIS_POINTS}。异常失败量为实际 failed_requests 减去常态失败量，最低为 0，再累计各有效桶。
只列有正异常失败量的事件及服务。快照保证一个服务桶不会归属多个根因事件。
处置顺序按事件异常失败总量降序，同量时 P0 优先于 P1，再按 incident_id 字典序；事件不足 {TOP_K} 个时列出全部。

返回 JSON：snapshot_id；incidents 数组（每项含 incident_id、severity、service_ids、excess_failed_requests）；priority 数组（前 {TOP_K} 个事件 ID）。
excess_failed_requests 必须为非负整数值，数值等价的 JSON 写法（如 48、48.0、48e0）均接受；明细行与 service_ids 顺序无关，priority 顺序有意义。只能通过业务 API 获取数据，不能直接访问数据库。
JSON 只包含上述字段，不得重复 JSON 键、事件 ID、同一事件内服务 ID 或优先级 ID；priority 只能引用已提交事件。快照不符、额外字段或类型错误等格式违规得 0。
答案的 UTF-8 JSON 编码不得超过 {MAX_ANSWER_BYTES} 字节（包含空白字符），超过时按输入超限处理并得 0。
奖励只依据最终结果：完整正确的事件分析计 {INCIDENT_POINTS} 单位；位置正确且事件分析完整正确的优先级项计 {PRIORITY_POINTS} 单位。
奖励为所得单位除以（应输出事件数 × {INCIDENT_POINTS} + 应输出优先级项数 × {PRIORITY_POINTS} + 多报事件数 × {EXTRA_INCIDENT_PENALTY}）。无应输出事件且答案为空时得 1；不检查调用轨迹。"""


def resolve_task(task):
    if not isinstance(task, str):
        raise ValueError("task must be canonical natural-language text returned by make_task")
    normalized = task.replace("\r\n", "\n").strip()
    match = re.match(rf"任务编号：alert-impact-v{TASK_VERSION}-seed-(\d+)\n", normalized)
    if not match:
        raise ValueError("unknown task identifier")
    seed = validate_seed(int(match.group(1)))
    if normalized != make_task(seed):
        raise ValueError("task text does not match registered version")
    return seed
