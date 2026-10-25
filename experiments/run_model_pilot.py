"""Bounded real-model pilot with the same text tool protocol for both backends.

Optional experiment only. Production environment/reward have no model dependency.
Credentials are read from the environment and never included in saved requests.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from alert_rlvr.environment import AlertEnvironment, API_SCHEMAS
from alert_rlvr.verifier import evaluate


SYSTEM = """你是执行告警业务分析任务的 Agent。你只能通过下面列出的业务工具查询数据，不能访问文件、数据库、评分器或参考答案。
每轮只能输出一个 JSON 对象，不要 Markdown 或其他正文。
调用工具：{"action":"call","name":"业务工具名","arguments":{参数}}
提交最终结果：{"action":"final","answer":{任务要求的最终JSON}}
工具调用与最终结果不能放在同一轮。你会收到工具返回的数据。你可以自主选择查询顺序、参数和计算方法。
请依据完整业务规则计算，不要猜测缺少的数据。工具错误可以修正后重新调用。
"""


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=True, indent=2, allow_nan=False), encoding="utf-8")


def parse_object(content):
    text = content.strip()
    # Accept only a whole fenced object, not arbitrary substring salvage.
    if text.startswith("```json\n") and text.endswith("\n```"):
        text = text[8:-4]
    elif text.startswith("```\n") and text.endswith("\n```"):
        text = text[4:-4]
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result
    result = json.loads(text, object_pairs_hook=pairs)
    if type(result) is not dict:
        raise ValueError("action must be a JSON object")
    return result


class DeepSeek:
    def __init__(self, args, out):
        self.args = args
        self.key = os.environ.get("DEEPSEEK_API_KEY")
        if not self.key:
            raise RuntimeError("DEEPSEEK_API_KEY is not configured")

    def complete(self, request):
        body = {"model": self.args.model, "messages": request["messages"],
                "max_tokens": request["max_tokens"], "temperature": request["temperature"],
                "top_p": 1.0, "stream": False, "thinking": {"type": self.args.thinking}}
        req = urllib.request.Request("https://api.deepseek.com/chat/completions",
                                     data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json", "Authorization": "Bearer " + self.key})
        last_error = None
        for attempt in range(2):
            started = time.monotonic()
            try:
                with urllib.request.urlopen(req, timeout=self.args.timeout) as response:
                    raw = json.load(response)
                choice = raw["choices"][0]
                return {"content": choice["message"].get("content") or "", "model": raw.get("model"),
                        "finish_reason": choice.get("finish_reason"), "usage": raw.get("usage"),
                        "seconds": time.monotonic() - started, "raw_response": raw,
                        "network_attempts": attempt + 1,
                        "sampling": {"temperature": request["temperature"],
                                     "requested_sampling_seed": request.get("sampling_seed"),
                                     "sampling_seed": None,
                                     "seed_control": "unsupported_api_seed; server_sampling_seed_uncontrolled",
                                     "top_p": 1.0, "top_k": "provider_default"}}
            except urllib.error.HTTPError as error:
                # Never print credentials or request headers. Auth/format errors are not retried.
                raise RuntimeError(f"DeepSeek HTTP {error.code}") from None
            except (urllib.error.URLError, TimeoutError) as error:
                reason = getattr(error, "reason", error)
                last_error = (f"{type(error).__name__}; reason={type(reason).__name__}; "
                              f"errno={getattr(reason, 'errno', None)}; winerror={getattr(reason, 'winerror', None)}")
                if attempt == 0:
                    time.sleep(1)
                else:
                    # Traceback contains the transport exception, not request headers.
                    traceback.print_exc(file=sys.stderr)
        raise RuntimeError(f"DeepSeek transport failed after two attempts: {last_error}")

    def close(self):
        pass


class LocalQwen:
    def __init__(self, args, out):
        if not args.local_python or not args.model_path:
            raise ValueError("Qwen requires --local-python and --model-path")
        self.timeout = args.timeout
        self.stderr = (out / "local-runtime.stderr.txt").open("w", encoding="utf-8")
        self.process = subprocess.Popen(
            [args.local_python, "-X", "utf8", str(ROOT / "experiments/local_qwen_driver.py"),
             "--model-path", args.model_path, "--device", args.device],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.stderr,
            text=True, encoding="utf-8", bufsize=1)
        self.responses = queue.Queue()
        def pump():
            for line in self.process.stdout:
                self.responses.put(line)
            self.responses.put(None)
        threading.Thread(target=pump, daemon=True).start()

    def complete(self, request):
        self.process.stdin.write(json.dumps(request, ensure_ascii=True) + "\n")
        self.process.stdin.flush()
        try:
            line = self.responses.get(timeout=self.timeout)
        except queue.Empty:
            raise TimeoutError("local model request timed out") from None
        if line is None:
            raise RuntimeError("local model process stopped; inspect runtime stderr")
        result = json.loads(line)
        if "error" in result:
            raise RuntimeError("local inference failed: " + str(result["error"]))
        return result

    def close(self):
        if self.process.poll() is None:
            self.process.stdin.close()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                self.process.wait(timeout=10)
        self.stderr.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("deepseek", "qwen"), required=True)
    parser.add_argument("--model", default="deepseek-flash")
    parser.add_argument("--thinking", choices=("disabled", "enabled"), default="disabled")
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--temperature", type=float, default=0.0,
                        help="Generation temperature in [0, 2]; 0 uses local greedy decoding")
    parser.add_argument("--sampling-seed", type=int,
                        help="Optional local RNG base seed, separate from --seed task instance; unsupported by DeepSeek API")
    parser.add_argument("--max-turns", type=int, default=12)
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--local-python")
    parser.add_argument("--model-path")
    parser.add_argument("--device", default="cuda", choices=("cuda", "cpu", "auto"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not math.isfinite(args.temperature) or not 0 <= args.temperature <= 2:
        parser.error("--temperature must be finite and in [0, 2]")
    if args.sampling_seed is not None and not 0 <= args.sampling_seed < 2**63:
        parser.error("--sampling-seed must be an integer in [0, 2**63)")
    args.output.mkdir(parents=True, exist_ok=False)
    task_hashes = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                   for path in sorted((ROOT / "alert_rlvr").glob("*.py"))}
    metadata = {"started_at": datetime.now(timezone.utc).isoformat(), "backend": args.backend,
                "requested_model": args.model if args.backend == "deepseek" else "Qwen2.5-1.5B-Instruct",
                "thinking": args.thinking if args.backend == "deepseek" else "not_applicable",
                "seed": args.seed, "task_instance_seed": args.seed,
                "sampling_seed": args.sampling_seed,
                "sampling_seed_note": "Task instance seed controls synthetic data; sampling seed controls only local generation RNG.",
                "sampling": {"temperature": args.temperature,
                             "do_sample": args.temperature > 0 if args.backend == "qwen" else "provider_controlled",
                             "top_p": 1.0 if args.backend == "deepseek" or args.temperature > 0 else "not_applied",
                             "top_k": 0 if args.backend == "qwen" and args.temperature > 0 else "not_applied" if args.backend == "qwen" else "provider_default",
                             "seed_control": "per_turn_local_torch_rng" if args.backend == "qwen" and args.sampling_seed is not None else "local_rng_unseeded" if args.backend == "qwen" else "unsupported_api_seed; server_sampling_seed_uncontrolled",
                             "turn_seed_derivation": "(sampling_seed + turn - 1) modulo 2**63; turn is one-based" if args.sampling_seed is not None else None,
                             "server_sampling_seed_controllable": False if args.backend == "deepseek" else "not_applicable"},
                "max_turns": args.max_turns, "max_output_tokens_per_turn": args.max_tokens,
                "temperature": args.temperature, "request_timeout_seconds": args.timeout,
                "protocol": "text-json-single-action-v1", "task_code_sha256": task_hashes,
                "scope": "Single-seed pilot, no claim of pass-rate or intrinsic model difficulty."}
    save(args.output / "metadata.json", metadata)
    result = {"status": "not_attempted", "reward": None, "tool_calls": 0, "protocol_errors": 0,
              "turns": 0, "truncated_responses": 0}
    backend = None
    start = time.monotonic()
    try:
        backend = DeepSeek(args, args.output) if args.backend == "deepseek" else LocalQwen(args, args.output)
        with AlertEnvironment(args.seed) as env:
            messages = [{"role": "system", "content": SYSTEM + "\n工具定义：\n" + json.dumps(API_SCHEMAS, ensure_ascii=False)},
                        {"role": "user", "content": env.task}]
            save(args.output / "initial_input.json", messages)
            for turn in range(1, args.max_turns + 1):
                turn_seed = None if args.sampling_seed is None else (args.sampling_seed + turn - 1) % (2**63)
                request = {"messages": messages, "max_tokens": args.max_tokens,
                           "temperature": args.temperature, "sampling_seed": turn_seed}
                save(args.output / f"turn-{turn:02d}-request.json", request)
                response = backend.complete(request)
                save(args.output / f"turn-{turn:02d}-response.json", response)
                result["turns"] = turn
                result["reported_model"] = response.get("model")
                result["truncated_responses"] += int(response.get("finish_reason") == "length")
                content = response.get("content", "")
                messages.append({"role": "assistant", "content": content})
                try:
                    action = parse_object(content)
                    if action.get("action") == "final" and set(action) == {"action", "answer"}:
                        answer = action["answer"]
                        evaluation = evaluate(env.task, answer)
                        save(args.output / "final_answer.json", answer)
                        save(args.output / "evaluation.json", evaluation)
                        result.update(status="completed" if evaluation["valid"] else "invalid_final_answer",
                                      reward=evaluation["reward"], evaluation=evaluation)
                        print(json.dumps({"turn": turn, "action": "final", "reward": result["reward"]}), flush=True)
                        break
                    if action.get("action") != "call" or set(action) != {"action", "name", "arguments"}:
                        raise ValueError("invalid action envelope")
                    tool_result = env.call(action["name"], action["arguments"])
                    result["tool_calls"] += 1
                    save(args.output / f"turn-{turn:02d}-tool.json", {"name": action["name"], "arguments": action["arguments"], "result": tool_result})
                    messages.append({"role": "user", "content": "工具返回：" + json.dumps(tool_result, ensure_ascii=False)})
                    print(json.dumps({"turn": turn, "action": "call", "name": action["name"], "ok": tool_result["ok"]}), flush=True)
                except (ValueError, TypeError, RecursionError):
                    result["protocol_errors"] += 1
                    messages.append({"role": "user", "content": "协议错误。请只输出一个完整 JSON：action=call 时包含 name 和 arguments；action=final 时包含 answer。"})
                    print(json.dumps({"turn": turn, "action": "protocol_error"}), flush=True)
            else:
                result["status"] = "budget_exhausted_without_final_answer"
    except Exception as error:
        result.update(status="execution_error", error={"type": type(error).__name__, "message": str(error)})
    finally:
        if backend is not None:
            backend.close()
        result["elapsed_seconds"] = round(time.monotonic() - start, 3)
        result["finished_at"] = datetime.now(timezone.utc).isoformat()
        save(args.output / "result.json", result)
        print(json.dumps(result, ensure_ascii=True), flush=True)
    return 0 if result["status"] in ("completed", "invalid_final_answer", "budget_exhausted_without_final_answer") else 1


if __name__ == "__main__":
    raise SystemExit(main())
