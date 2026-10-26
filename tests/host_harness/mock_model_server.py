# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Local scripted stand-in for a model API, used to test host plumbing offline.

Codex CLI (OpenAI Responses API) and Claude Code (Anthropic Messages API) can
be pointed at a custom endpoint. This server answers both with a fixed script:
the first turn asks the host to call one BIO CE tool, the next turn ends with a
short text. Every request body is appended to a JSON-lines log so a test can
check what the host sent (for example, that BIO CE's hook context arrived).

No real model is involved and nothing leaves the machine. This verifies that a
host loads BIO CE's MCP server and hooks and executes its tools; it says
nothing about whether a real model would decide to call them.

Usage: python mock_model_server.py PORT LOG_FILE SCRIPT_JSON
SCRIPT_JSON: {"tool": "bio_memory_create", "arguments": {...}, "code_mode_js": "..."}
``code_mode_js`` (optional) is sent through Codex code mode's ``exec`` tool when
the named tool is not declared to the model directly.
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
import uuid


class Script:
    def __init__(self, path: Path, tool: str, arguments: dict, code_mode_js: str | None = None) -> None:
        self.log = path
        self.tool = tool
        self.arguments = arguments
        self.code_mode_js = code_mode_js
        self.lock = threading.Lock()

    def record(self, route: str, body: dict) -> None:
        with self.lock, self.log.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"route": route, "body": body}, ensure_ascii=False) + "\n")


def _tool_name(names: list[str], wanted: str) -> str | None:
    for name in names:
        if name == wanted or name.endswith(f"__{wanted}") or name.endswith(f".{wanted}"):
            return name
    return None


def make_handler(script: Script):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args) -> None:
            pass

        def do_GET(self) -> None:  # model listings and health checks
            self._json({"data": [{"id": "mock-model", "object": "model"}], "object": "list"})

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            try:
                body = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                body = {"_raw": raw.decode("utf-8", "replace")}
            path = self.path.split("?")[0]
            script.record(path, body)
            if path.endswith("/responses"):
                self._openai(body)
            elif path.endswith("/messages/count_tokens"):
                self._json({"input_tokens": 100})
            elif path.endswith("/messages"):
                self._anthropic(body)
            else:
                self._json({})

        # OpenAI Responses API (Codex CLI) ------------------------------------

        def _openai(self, body: dict) -> None:
            items = body.get("input") or []
            answered = any(isinstance(item, dict) and item.get("type") == "function_call_output" for item in items)
            tools = [tool for tool in body.get("tools") or [] if isinstance(tool, dict)]
            for item in items:  # Codex 0.162 sends catalog models their tools as an "additional_tools" input item
                if isinstance(item, dict) and item.get("type") == "additional_tools":
                    for group in item.get("tools") or []:
                        if isinstance(group, dict):
                            tools += [group] + [inner for inner in group.get("tools") or [] if isinstance(inner, dict)
                                                and group.get("type") == "namespace" and group.get("name") == "functions"]
            name = _tool_name([tool.get("name") or "" for tool in tools], script.tool)
            namespace = None
            for tool in tools:  # Codex groups each MCP server's tools in a "namespace" tool
                if tool.get("type") == "namespace" and any(
                        isinstance(inner, dict) and inner.get("name") == script.tool for inner in tool.get("tools") or []):
                    name, namespace = script.tool, tool.get("name")
            events = [{"type": "response.created", "response": {"id": f"resp_{uuid.uuid4().hex[:8]}"}}]
            code_mode = any(isinstance(item, dict) and item.get("type") == "custom_tool_call_output" for item in items)
            if script.tool == "__codemode_probe__" and not code_mode:
                # Ask Codex's code mode which nested tools exist at run time.
                events.append({"type": "response.output_item.done", "item": {
                    "type": "custom_tool_call", "name": "exec", "namespace": "functions",
                    "call_id": f"call_{uuid.uuid4().hex[:8]}",
                    "input": script.arguments.get("js", "text(JSON.stringify(Object.keys(tools)));")}})
                name, answered = None, True
            elif (not name and not code_mode and script.code_mode_js
                  and any(tool.get("name") == "exec" for tool in tools)):
                events.append({"type": "response.output_item.done", "item": {
                    "type": "custom_tool_call", "name": "exec", "namespace": "functions",
                    "call_id": f"call_{uuid.uuid4().hex[:8]}", "input": script.code_mode_js}})
                name, answered = None, True
            elif name and not answered:
                call = {"type": "function_call", "name": name, "arguments": json.dumps(script.arguments),
                        "call_id": f"call_{uuid.uuid4().hex[:8]}"}
                if namespace:
                    call["namespace"] = namespace
                events.append({"type": "response.output_item.done", "item": call})
            else:
                text = "Mock model: done." if answered else f"Mock model: tool {script.tool} was not offered."
                events.append({"type": "response.output_item.done", "item": {
                    "type": "message", "role": "assistant", "id": f"msg_{uuid.uuid4().hex[:8]}",
                    "content": [{"type": "output_text", "text": text}]}})
            events.append({"type": "response.completed", "response": {
                "id": events[0]["response"]["id"],
                "usage": {"input_tokens": 1, "input_tokens_details": None, "output_tokens": 1,
                          "output_tokens_details": None, "total_tokens": 2}}})
            self._sse([(event["type"], event) for event in events])

        # Anthropic Messages API (Claude Code) --------------------------------

        def _anthropic(self, body: dict) -> None:
            messages = body.get("messages") or []
            used = {block.get("name") for message in messages if message.get("role") == "assistant"
                    and isinstance(message.get("content"), list) for block in message["content"]
                    if isinstance(block, dict) and block.get("type") == "tool_use"}
            names = [tool.get("name") or "" for tool in body.get("tools") or [] if isinstance(tool, dict)]
            name = _tool_name(names, script.tool)
            answered = name in used
            arguments = script.arguments
            if not name and "ToolSearch" in names and "ToolSearch" not in used:
                # Claude Code defers MCP tools: load the tool first, as a model would.
                name, arguments = "ToolSearch", {"query": f"select:mcp__bio-ce__{script.tool}", "max_results": 1}
            message_id = f"msg_{uuid.uuid4().hex[:12]}"
            start = {"type": "message_start", "message": {
                "id": message_id, "type": "message", "role": "assistant", "model": body.get("model", "mock"),
                "content": [], "stop_reason": None, "stop_sequence": None,
                "usage": {"input_tokens": 1, "output_tokens": 1}}}
            events = [("message_start", start)]
            if name and not answered:
                events += [
                    ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {
                        "type": "tool_use", "id": f"toolu_{uuid.uuid4().hex[:12]}", "name": name, "input": {}}}),
                    ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {
                        "type": "input_json_delta", "partial_json": json.dumps(arguments)}}),
                    ("content_block_stop", {"type": "content_block_stop", "index": 0}),
                    ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "tool_use",
                                                                          "stop_sequence": None},
                                       "usage": {"output_tokens": 1}}),
                ]
            else:
                text = "Mock model: done." if used else "Mock model reply."
                events += [
                    ("content_block_start", {"type": "content_block_start", "index": 0,
                                             "content_block": {"type": "text", "text": ""}}),
                    ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                             "delta": {"type": "text_delta", "text": text}}),
                    ("content_block_stop", {"type": "content_block_stop", "index": 0}),
                    ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn",
                                                                          "stop_sequence": None},
                                       "usage": {"output_tokens": 1}}),
                ]
            events.append(("message_stop", {"type": "message_stop"}))
            if body.get("stream"):
                self._sse(events)
            else:
                content = []
                for _name, event in events:
                    if event["type"] == "content_block_start":
                        content.append(dict(event["content_block"]))
                    elif event["type"] == "content_block_delta":
                        delta = event["delta"]
                        if delta["type"] == "text_delta":
                            content[-1]["text"] += delta["text"]
                        else:
                            content[-1]["input"] = json.loads(delta["partial_json"])
                stop = next(e["delta"]["stop_reason"] for n, e in events if n == "message_delta")
                self._json({**start["message"], "content": content, "stop_reason": stop})

        # Transport -------------------------------------------------------------

        def _json(self, payload: dict) -> None:
            data = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _sse(self, events: list[tuple[str, dict]]) -> None:
            data = "".join(f"event: {name}\ndata: {json.dumps(event)}\n\n" for name, event in events).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return Handler


def main(argv: list[str]) -> int:
    port, log, script_file = int(argv[0]), Path(argv[1]), Path(argv[2])
    spec = json.loads(script_file.read_text(encoding="utf-8"))
    script = Script(log, spec["tool"], spec["arguments"], spec.get("code_mode_js"))
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(script))
    print(f"listening {server.server_address[1]}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
