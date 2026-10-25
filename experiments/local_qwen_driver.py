"""Offline Qwen JSONL driver. Model files and dependencies are supplied locally.

Run with --model-path or QWEN_MODEL_PATH and the Python environment containing
PyTorch/Transformers. No model weights are downloaded and no CPU fallback occurs
after a CUDA load or generation failure. Standard output is protocol JSON only.
"""

import argparse
from contextlib import redirect_stdout
import json
import math
import os
from pathlib import Path
import sys
import time
import traceback


MODEL_NAME = "Qwen2.5-1.5B-Instruct"
MAX_CONTEXT_TOKENS = 32768
MAX_REQUEST_BYTES = 2_000_000


def _emit(payload, stream=sys.stdout):
    # ASCII escaping also handles malformed Unicode supplied through JSON.
    stream.write(json.dumps(payload, ensure_ascii=True, allow_nan=False) + "\n")
    stream.flush()


def _error(error):
    # Do not echo input messages, environment variables, or authentication data.
    messages = {
        "OutOfMemoryError": "CUDA out of memory; no CPU retry was attempted",
        "UnicodeEncodeError": "Input contains invalid Unicode text",
        "JSONDecodeError": "Input is not a valid JSON request",
    }
    message = messages.get(type(error).__name__)
    if message is None:
        message = str(error) if isinstance(error, ValueError) else "Local model operation failed; see diagnostic traceback on stderr"
    return {"error": {"type": type(error).__name__, "message": message}}


def _validate_request(request):
    if type(request) is not dict or set(request) - {"messages", "max_tokens", "temperature", "sampling_seed"}:
        raise ValueError("Request must contain only messages, max_tokens, temperature, and sampling_seed")
    messages = request.get("messages")
    if type(messages) is not list or not messages:
        raise ValueError("messages must be a nonempty list")
    for message in messages:
        if type(message) is not dict or set(message) != {"role", "content"}:
            raise ValueError("Each message must contain exactly role and content")
        if message["role"] not in ("system", "user", "assistant", "tool") or type(message["content"]) is not str:
            raise ValueError("Messages require a supported role and string content")
    max_tokens = request.get("max_tokens", 1024)
    if type(max_tokens) is not int or not 1 <= max_tokens <= MAX_CONTEXT_TOKENS:
        raise ValueError("max_tokens must be an integer from 1 through 32768")
    temperature = request.get("temperature", 0.0)
    if type(temperature) not in (int, float) or not math.isfinite(temperature) or not 0 <= temperature <= 2:
        raise ValueError("temperature must be finite and in [0, 2]")
    sampling_seed = request.get("sampling_seed")
    if sampling_seed is not None and (type(sampling_seed) is not int or not 0 <= sampling_seed < 2**63):
        raise ValueError("sampling_seed must be null or an integer in [0, 2**63)")
    return messages, max_tokens, float(temperature), sampling_seed


def _load(model_path, requested_device):
    path = Path(model_path).expanduser().resolve()
    if not path.is_dir():
        raise ValueError("model-path must identify an existing local snapshot directory")
    # Process-local network denial for HF loaders, in addition to local_files_only.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    with redirect_stdout(sys.stderr):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        device = "cuda" if requested_device == "auto" and torch.cuda.is_available() else requested_device
        if device == "auto":
            device = "cpu"
        if device == "cuda" and not torch.cuda.is_available():
            raise ValueError("CUDA requested but unavailable; select CPU explicitly if intended")
        dtype = torch.bfloat16 if device == "cuda" and torch.cuda.is_bf16_supported() else torch.float16 if device == "cuda" else torch.float32
        started = time.perf_counter()
        tokenizer = AutoTokenizer.from_pretrained(str(path), local_files_only=True, trust_remote_code=False)
        model = AutoModelForCausalLM.from_pretrained(
            str(path), local_files_only=True, trust_remote_code=False,
            dtype=dtype, attn_implementation="sdpa",
        ).to(device).eval()
        context_limit = min(MAX_CONTEXT_TOKENS, int(model.config.max_position_embeddings))
        if model.config.model_type != "qwen2" or model.config.hidden_size != 1536 or model.config.num_hidden_layers != 28:
            raise ValueError("Snapshot configuration does not match Qwen2.5-1.5B-Instruct")
        _emit({
            "event": "model_loaded", "model": MODEL_NAME,
            "device": str(model.device), "dtype": str(model.dtype),
            "context_limit": context_limit, "load_seconds": time.perf_counter() - started,
            "torch": torch.__version__, "cuda_runtime": torch.version.cuda,
        }, sys.stderr)
    return torch, tokenizer, model, context_limit


def _generate(request, torch, tokenizer, model, context_limit):
    messages, max_tokens, temperature, sampling_seed = _validate_request(request)
    started = time.perf_counter()
    with redirect_stdout(sys.stderr):
        encoded = tokenizer.apply_chat_template(
            messages, tokenize=True, add_generation_prompt=True,
            return_tensors="pt", return_dict=True,
        )
        input_tokens = encoded["input_ids"].shape[-1]
        if input_tokens + max_tokens > context_limit:
            raise ValueError(f"Context budget exceeded: input_tokens={input_tokens}, max_tokens={max_tokens}, limit={context_limit}; input was not truncated")
        encoded = {key: value.to(model.device) for key, value in encoded.items()}
        pad_token_id = tokenizer.pad_token_id
        if pad_token_id is None:
            pad_token_id = tokenizer.eos_token_id
        if sampling_seed is not None:
            torch.manual_seed(sampling_seed)
            if model.device.type == "cuda":
                torch.cuda.manual_seed_all(sampling_seed)
        do_sample = temperature > 0
        generation_options = {"do_sample": do_sample}
        if do_sample:
            generation_options.update(temperature=temperature, top_p=1.0, top_k=0)
        with torch.inference_mode():
            generated = model.generate(
                **encoded, **generation_options, max_new_tokens=max_tokens,
                use_cache=True, pad_token_id=pad_token_id,
            )
        output_ids = generated[0, input_tokens:].tolist()
        content = tokenizer.decode(output_ids, skip_special_tokens=True)
    eos_ids = model.generation_config.eos_token_id
    if type(eos_ids) is int:
        eos_ids = [eos_ids]
    eos_ids = eos_ids or []
    stopped_at_eos = bool(output_ids) and output_ids[-1] in eos_ids
    return {
        "content": content, "model": MODEL_NAME,
        "input_tokens": input_tokens, "output_tokens": len(output_ids),
        "finish_reason": "stop" if stopped_at_eos or len(output_ids) < max_tokens else "length",
        "seconds": time.perf_counter() - started,
        "sampling": {"temperature": temperature, "do_sample": do_sample,
                     "top_p": 1.0 if do_sample else None,
                     "top_k": 0 if do_sample else None,
                     "sampling_seed": sampling_seed,
                     "seed_control": "torch_manual_seed_and_cuda_manual_seed_all" if sampling_seed is not None else "local_rng_unseeded"},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-path", default=os.environ.get("QWEN_MODEL_PATH"))
    parser.add_argument("--device", choices=("auto", "cuda", "cpu"), default="cuda")
    args = parser.parse_args()
    if not args.model_path:
        parser.error("Supply --model-path or QWEN_MODEL_PATH; automatic downloading is disabled")
    try:
        runtime = _load(args.model_path, args.device)
    except Exception as error:
        result = _error(error)
        _emit(result)
        _emit({"event": "load_failed", **result}, sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.stderr.flush()
        return 1
    while True:
        line = sys.stdin.readline(MAX_REQUEST_BYTES + 1)
        if not line:
            return 0
        try:
            if len(line.encode("utf-8")) > MAX_REQUEST_BYTES:
                # Drain this oversized request without treating its tail as another request.
                while not line.endswith("\n"):
                    line = sys.stdin.readline(MAX_REQUEST_BYTES + 1)
                    if not line:
                        break
                raise ValueError("JSON request exceeds the byte limit")
            request = json.loads(line)
            result = _generate(request, *runtime)
        except Exception as error:
            result = _error(error)
            _emit({"event": "request_failed", **result}, sys.stderr)
            traceback.print_exc(file=sys.stderr)
            sys.stderr.flush()
        _emit(result)


if __name__ == "__main__":
    raise SystemExit(main())
