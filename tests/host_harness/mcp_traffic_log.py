# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Transparent stdio relay that records MCP JSON-RPC traffic metadata.

A host is configured to start this relay instead of the BIO CE server; the relay
starts the real server and forwards bytes both ways unchanged. For every frame it
appends one JSON line with the direction, elapsed time, method, id, and (for
responses) the result's top-level keys plus the tool names of ``tools/list``.
Arguments, memory text, and tokens are never written.

Usage: python -I mcp_traffic_log.py LOG_FILE SERVER_COMMAND [SERVER_ARGS...]
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import threading
import time


def main(argv: list[str]) -> int:
    log_path = Path(argv[0])
    started = time.monotonic()
    lock = threading.Lock()

    def record(direction: str, line: bytes) -> None:
        entry: dict = {"t": round(time.monotonic() - started, 3), "dir": direction}
        try:
            frame = json.loads(line)
        except ValueError:
            entry["unparsed_bytes"] = len(line)
        else:
            entry["id"] = frame.get("id")
            if "method" in frame:
                entry["method"] = frame["method"]
                if frame["method"] == "tools/call":
                    entry["tool"] = (frame.get("params") or {}).get("name")
                    entry["argument_names"] = sorted(((frame.get("params") or {}).get("arguments") or {}).keys())
            result = frame.get("result")
            if isinstance(result, dict):
                entry["result_keys"] = sorted(result.keys())
                if "tools" in result:
                    entry["tools"] = [tool.get("name") for tool in result["tools"]]
                if "isError" in result:
                    entry["is_error"] = result["isError"]
            if "error" in frame:
                entry["error_code"] = (frame["error"] or {}).get("code")
        with lock, log_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry) + "\n")

    record("relay", b'{"method": "relay/start"}')
    server = subprocess.Popen(argv[1:], stdin=subprocess.PIPE, stdout=subprocess.PIPE)

    def pump_in() -> None:
        for line in sys.stdin.buffer:
            record("host->server", line)
            server.stdin.write(line)
            server.stdin.flush()
        server.stdin.close()

    threading.Thread(target=pump_in, daemon=True).start()
    for line in server.stdout:
        record("server->host", line)
        sys.stdout.buffer.write(line)
        sys.stdout.buffer.flush()
    code = server.wait()
    record("relay", json.dumps({"method": "relay/exit", "id": code}).encode())
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
