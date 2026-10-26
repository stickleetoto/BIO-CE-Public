# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Measure Codex CLI's handling of BIO CE's MCP server in four separate stages.

1. server start   - Codex launched the server and it answered ``initialize``
2. tools/list     - the server returned BIO CE's six tools to Codex
3. model exposure - BIO CE's tools appear in the first request Codex sends to the model
4. tool call      - a scripted model call reached the server and succeeded

The model is the local scripted mock (``mock_model_server.py``); no model service
is contacted. Codex runs with ``--ignore-user-config``, an isolated ``CODEX_HOME``,
hooks disabled, and no hook-trust or sandbox bypass. Each variant gets a fresh
synthetic database with an Auto memory grant.

Usage: python codex_stage_probe.py OUT_DIR SERVER_EXE [VARIANT ...]
SERVER_EXE is BIO-CE-MCP.exe (or a Python interpreter, which then runs ``-m bio_ce``).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time

from bio_ce.control_store import ControlStore, MODE_AUTO_MEMORY, control_database_for
from bio_ce.core.models import MemoryScope, SourceProvenance
from bio_ce.host_hooks import BIO_TOOLS
from bio_ce.storage.sqlite_store import SQLiteMemoryStore

HERE = Path(__file__).resolve().parent
SCOPE = MemoryScope("bio-ce-personal", "default")
CATALOG_MODEL = os.environ.get("BIO_CE_CODEX_MODEL", "gpt-6.1-sol")
CODE_MODE_JS = (
    "const r = await tools.mcp__bio_ce__bio_memory_search({query: 'dark terminal theme'});"
    " text(JSON.stringify(r));"
)
# name -> (model, extra Codex arguments, description)
VARIANTS = {
    "fallback-default": ("mock-model", [], "Model unknown to Codex (function-tool mode), default startup grace"),
    "fallback-grace5000": ("mock-model", ["-c", "mcp_optional_startup_grace_ms=5000"],
                           "Model unknown to Codex, documented mcp_optional_startup_grace_ms=5000"),
    "catalog-default": (CATALOG_MODEL, [], f"Catalog model {CATALOG_MODEL} (code mode), default settings"),
    "catalog-grace5000": (CATALOG_MODEL, ["-c", "mcp_optional_startup_grace_ms=5000"],
                          f"Catalog model {CATALOG_MODEL}, startup grace 5000 ms"),
    "catalog-tool-search": (CATALOG_MODEL, ["--enable", "code_mode_tool_search"],
                            f"Catalog model {CATALOG_MODEL}, experimental code_mode_tool_search (diagnostic only)"),
}


def toml_str(value: str) -> str:
    return "'" + value + "'" if "'" not in value else json.dumps(value)


def codex_launcher() -> list[str]:
    """Run the npm-installed Codex CLI through node directly (no cmd.exe argument re-parsing)."""
    script = os.environ.get("BIO_CE_CODEX_JS")
    if not script:
        wrapper = shutil.which("codex")
        if wrapper is None:
            raise SystemExit("codex is not on PATH")
        script = str(Path(wrapper).parent / "node_modules" / "@openai" / "codex" / "bin" / "codex.js")
    node = shutil.which("node")
    if node is None or not Path(script).is_file():
        raise SystemExit("node or the Codex CLI script was not found")
    return [node, script]


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def prepare(root: Path) -> tuple[Path, str, str]:
    database = root / "data" / "memories.sqlite3"
    store = SQLiteMemoryStore(database)
    store.add(SCOPE, title="Prefers dark terminal theme", content="Synthetic: the user prefers a dark terminal theme.",
              source=SourceProvenance("user-entered", "user-input"))
    store.close()
    with ControlStore(control_database_for(database)) as control:
        grant, token = control.create_grant("codex", project=SCOPE.project, namespace=SCOPE.namespace)
        control.set_mode(grant.connection_id, MODE_AUTO_MEMORY)
    return database, grant.connection_id, token


def run_variant(out: Path, server_exe: Path, name: str) -> dict:
    model, extra, description = VARIANTS[name]
    root = out / name
    (root / "codex-home").mkdir(parents=True)
    (root / "work").mkdir()
    database, connection_id, token = prepare(root)
    traffic = root / "mcp-traffic.jsonl"
    requests = root / "model-requests.jsonl"
    script = root / "script.json"
    script.write_text(json.dumps({"tool": "bio_memory_search", "arguments": {"query": "dark terminal theme"},
                                  "code_mode_js": CODE_MODE_JS}), encoding="utf-8")
    port = free_port()
    mock = subprocess.Popen([sys.executable, "-I", str(HERE / "mock_model_server.py"), str(port), str(requests),
                             str(script)], stdout=subprocess.PIPE, text=True)
    mock.stdout.readline()
    launcher = [] if server_exe.name.lower() == "bio-ce-mcp.exe" else ["-m", "bio_ce"]
    server_args = ["-I", str(HERE / "mcp_traffic_log.py"), str(traffic), str(server_exe), *launcher, "mcp-stdio",
                   "--db", str(database), "--connection", connection_id]
    approvals = ", ".join(f'{tool} = {{ approval_mode = "approve" }}' for tool in BIO_TOOLS)
    server = (f"{{ command = {toml_str(sys.executable)}, args = [{', '.join(toml_str(a) for a in server_args)}], "
              f"env = {{ BIO_CE_CONNECTION_TOKEN = {toml_str(token)} }}, tools = {{ {approvals} }} }}")
    command = [
        *codex_launcher(), "exec", "--ignore-user-config", "--ephemeral", "--skip-git-repo-check", "--json",
        "-C", str(root / "work"), "--sandbox", "read-only", "-m", model,
        "--disable", "hooks", "--disable", "memories", "--disable", "multi_agent", "--disable", "apps",
        "--disable", "plugins", "--disable", "browser_use", "--disable", "computer_use",
        "-c", 'web_search="disabled"', *extra,
        "-c", f"mcp_servers.bio-ce={server}",
        "-c", 'model_provider="biomock"',
        "-c", f'model_providers.biomock={{ name = "BIO CE local mock", base_url = "http://127.0.0.1:{port}/v1", '
              'wire_api = "responses", env_key = "BIOMOCK_KEY" }',
        "Which terminal theme do I prefer?",
    ]
    env = dict(os.environ, CODEX_HOME=str(root / "codex-home"), BIOMOCK_KEY="mock-not-a-real-key")
    started = time.monotonic()
    try:
        completed = subprocess.run(command, cwd=root / "work", env=env, stdin=subprocess.DEVNULL,
                                   capture_output=True, timeout=300)
    finally:
        mock.terminate()
        mock.wait(10)
    (root / "codex.jsonl").write_bytes(completed.stdout)
    (root / "codex.stderr.txt").write_bytes(completed.stderr)
    return analyze(name, description, model, extra, completed.returncode, time.monotonic() - started,
                   traffic, requests, completed.stdout.decode("utf-8", "replace"))


def analyze(name, description, model, extra, exit_code, seconds, traffic: Path, requests: Path, codex_out: str) -> dict:
    frames = [json.loads(line) for line in traffic.read_text(encoding="utf-8").splitlines()] if traffic.exists() else []
    init = next((f for f in frames if f["dir"] == "server->host" and "serverInfo" in f.get("result_keys", [])), None)
    listed = next((f for f in frames if f["dir"] == "server->host" and "tools" in f), None)
    calls = [f for f in frames if f.get("method") == "tools/call"]
    call_results = [f for f in frames if f["dir"] == "server->host" and "is_error" in f
                    and any(c["id"] == f["id"] for c in calls)]
    bodies = [json.loads(line)["body"] for line in requests.read_text(encoding="utf-8").splitlines()
              if '"/v1/responses"' in line or '/responses' in line] if requests.exists() else []
    first = bodies[0] if bodies else {}
    exposure = "no model request"
    if first:
        tools = list(first.get("tools") or [])
        for item in first.get("input") or []:  # catalog models receive tools in an "additional_tools" item
            if isinstance(item, dict) and item.get("type") == "additional_tools":
                tools += item.get("tools") or []
        names = [tool.get("name") for tool in tools if isinstance(tool, dict)]
        nested = [inner.get("name") for tool in tools if isinstance(tool, dict) and tool.get("type") == "namespace"
                  for inner in tool.get("tools") or [] if isinstance(inner, dict)]
        text = json.dumps(tools)
        if any(n and n.endswith("bio_memory_search") for n in names + nested):
            exposure = "declared as model tools"
        elif "bio_memory_search" in text:
            exposure = "named only inside another tool's description"
        elif "tool_search" in names:
            exposure = "not declared; tool_search offered"
        else:
            exposure = "not declared"
    tool_mode = "code mode (exec)" if first and '"name": "exec"' in json.dumps(first) else "function tools"
    request_times = [f["t"] for f in frames if f.get("method") == "tools/list"]
    return {
        "variant": name,
        "description": description,
        "model": model,
        "extra_args": extra,
        "codex_exit": exit_code,
        "seconds": round(seconds, 1),
        "tool_mode": tool_mode,
        "stage1_server_start": bool(init),
        "stage1_initialize_seconds": init["t"] if init else None,
        "stage2_tools_list": sorted(listed["tools"]) if listed else None,
        "stage2_ok": bool(listed) and set(listed["tools"]) == set(BIO_TOOLS),
        "stage2_tools_list_seconds": request_times[0] if request_times else None,
        "stage3_model_exposure": exposure,
        "stage3_ok": exposure == "declared as model tools",
        "stage4_tool_calls": [{"tool": c.get("tool"), "argument_names": c.get("argument_names")} for c in calls],
        "stage4_ok": any(r.get("is_error") is False for r in call_results),
        "stage4_route": ("direct function call" if exposure == "declared as model tools" else "code-mode exec")
        if calls else None,
        "model_requests": len(bodies),
        "codex_reported_mcp_call": '"type":"mcp_tool_call"' in codex_out.replace(" ", ""),
    }


def main(argv: list[str]) -> int:
    out, server_exe = Path(argv[0]).resolve(), Path(argv[1]).resolve()
    names = argv[2:] or list(VARIANTS)
    out.mkdir(parents=True, exist_ok=True)
    results = []
    for name in names:
        result = run_variant(out, server_exe, name)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        results.append(result)
    (out / "summary.json").write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
