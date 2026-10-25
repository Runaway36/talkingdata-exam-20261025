"""Optional JSON Lines business-tool transport; no HTTP service required.

Only business tools are registered. The process never exposes grading or SQL.
"""
import argparse
import json
import sys

from .config import DEFAULT_SEED
from .environment import API_SCHEMAS, AlertEnvironment

MAX_REQUEST_BYTES = 100_000


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def serve(seed=DEFAULT_SEED, input_stream=None, output_stream=None):
    source = input_stream if input_stream is not None else sys.stdin
    sink = output_stream if output_stream is not None else sys.stdout
    with AlertEnvironment(seed) as env:
        for line in source:
            request_id = None
            try:
                if len(line.encode("utf-8")) > MAX_REQUEST_BYTES:
                    raise ValueError("request too large")
                request = json.loads(line, object_pairs_hook=_pairs)
                if not isinstance(request, dict) or set(request) - {"id", "tool", "arguments"}:
                    raise ValueError("request must contain only id, tool, arguments")
                request_id = request.get("id")
                if request_id is not None and (type(request_id) not in (str, int) or len(str(request_id)) > 100):
                    request_id = None
                    raise ValueError("id must be a short string or integer")
                result = env.call(request.get("tool"), request.get("arguments", {}))
            except (ValueError, TypeError, RecursionError, UnicodeError):
                result = {"ok": False, "snapshot_id": env.snapshot_id,
                          "error": {"code": "invalid_request", "message": "Invalid JSON tool request"}}
            # Escaping also keeps lone surrogate IDs from crashing UTF-8 stdout.
            sink.write(json.dumps({"id": request_id, **result}, ensure_ascii=True, allow_nan=False) + "\n")
            sink.flush()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--catalog", action="store_true")
    args = parser.parse_args()
    if args.catalog:
        print(json.dumps(API_SCHEMAS, ensure_ascii=False, indent=2))
    else:
        try:
            serve(args.seed)
        except ValueError as error:
            parser.exit(2, f"Invalid seed: {error}\n")


if __name__ == "__main__":
    main()
