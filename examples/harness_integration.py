"""Minimal trusted training-controller integration, independent of a vendor SDK."""
from alert_rlvr.config import DEFAULT_SEED
from alert_rlvr.environment import API_SCHEMAS, AlertEnvironment
from alert_rlvr.verifier import evaluate
from .reference_agent import solve


def run_episode(agent, seed=DEFAULT_SEED):
    """agent(task_text, tool_schemas, call_tool) returns a final dict/JSON answer.

    Register only call_tool with the model; keep evaluate on the controller side.
    Invalid final answers yield a zero reward. Agent/runtime crashes are surfaced
    separately as episode errors, not silently counted as task failure.
    """
    with AlertEnvironment(seed) as env:
        answer = agent(env.task, API_SCHEMAS, env.call)
        return {"answer": answer, "evaluation": evaluate(env.task, answer)}


def reference_policy(task_text, tool_schemas, call_tool):
    """Demonstration adapter. Replace this callback with a real model tool loop."""
    from alert_rlvr.config import resolve_task, snapshot_id
    task_snapshot_id = snapshot_id(resolve_task(task_text))
    class ToolClient:
        task = task_text
        snapshot_id = task_snapshot_id
        call = staticmethod(call_tool)
    return solve(ToolClient())


if __name__ == "__main__":
    import json
    print(json.dumps(run_episode(reference_policy), ensure_ascii=False, indent=2))
