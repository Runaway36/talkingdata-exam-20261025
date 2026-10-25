"""Versioned, shared business parameters and canonical task registration."""
import re

DEFAULT_SEED = 17
MAX_SEED = 9999
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
REWARD_WEIGHTS = {"coverage": 0.25, "fields": 0.50, "priority": 0.25}


def validate_seed(seed):
    if type(seed) is not int or not 0 <= seed <= MAX_SEED:
        raise ValueError(f"seed must be an integer in [0, {MAX_SEED}]")
    return seed


def snapshot_id(seed=DEFAULT_SEED):
    return f"alert-impact-v2-seed-{validate_seed(seed)}"


def make_task(seed=DEFAULT_SEED):
    return f"""任务编号：{snapshot_id(seed)}
你是监控平台的值班分析员。请分析 UTC 窗口 [{WINDOW_START}, {WINDOW_END}) 内，
截至窗口结束仍需处置（firing）的 P0/P1 告警所对应根因事件的业务影响，并选出优先处理的前 {TOP_K} 个事件。
告警可能重复；请以 incident_id 合并，不要用告警标题猜测影响服务。事件与服务关系、服务资料、请求观测和维护记录须从业务 API 查询。
仅计 production 服务。每个 {BUCKET_MINUTES} 分钟观测桶必须完整位于报告窗口和事件影响区间内；同一事件、服务、桶只统计一次。
approved 维护若完整覆盖一个观测桶，该桶属于计划停机，不能计入事件影响；cancelled 维护或仅部分覆盖均不排除。
每桶常态失败请求数 = request_count * baseline_failure_bps // {BASIS_POINTS}；异常失败请求数 = max(0, failed_requests - 常态失败请求数)。
按服务观测桶累加异常失败请求数，计量单位是服务调用失败次数，不是去重用户数，也不涉及金额。
模拟快照保证同一服务桶不会归属不同根因事件。忽略异常失败请求数为 0 的事件；service_ids 只列异常失败请求数大于 0 的服务。
事件 severity 取符合条件告警中的最高等级。优先级按 excess_failed_requests 降序，再按 P0 优先于 P1，再按 incident_id 字典序。
返回 JSON：snapshot_id；incidents 数组（每项含 incident_id、severity、service_ids、excess_failed_requests）；priority 数组（前 {TOP_K} 个事件 ID）。
请求数必须为非负整数；明细行与 service_ids 的顺序无关，priority 顺序有意义。不能直接访问数据库。
奖励只依据最终分析结果：事件覆盖 25%，三个明细字段正确率 50%，优先级位置正确率 25%；不检查工具调用轨迹。"""


def resolve_task(task):
    if not isinstance(task, str):
        raise ValueError("task must be canonical natural-language text returned by make_task")
    normalized = task.replace("\r\n", "\n").strip()
    match = re.match(r"任务编号：alert-impact-v2-seed-(\d+)\n", normalized)
    if not match:
        raise ValueError("unknown task identifier")
    seed = validate_seed(int(match.group(1)))
    if normalized != make_task(seed):
        raise ValueError("task text does not match registered version")
    return seed
