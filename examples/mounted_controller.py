"""Run this file via a read-only bind mount; import the image's installed path."""
import json
from alert_rlvr.config import make_task
from alert_rlvr.environment import AlertEnvironment
from alert_rlvr.verifier import compute_reward
from examples.reference_agent import solve


def main():
    with AlertEnvironment(seed=42) as environment:
        answer = solve(environment)
        reward = compute_reward(make_task(42), answer)
        assert reward == 1.0
        print(json.dumps({"mounted_controller": "passed", "snapshot_id": environment.snapshot_id,
                          "reward": reward, "priority": answer["priority"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
