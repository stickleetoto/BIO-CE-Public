# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Run the scripted real-model Auto memory evaluation for one host.

Everything the host needs is passed per run (CLI flags, an inline Codex config,
and a Claude Code ``--settings``/``--mcp-config`` file), so the user's real host
settings are read for authentication only and never edited. Each host gets its
own synthetic BIO CE database with an Auto memory grant.

Usage:
  python real_model_eval.py setup  ROOT HOST EXE
  python real_model_eval.py run    ROOT HOST EXE STEP [--mock-port PORT]
STEP is one of A, B, C, D, E, recall. ``--mock-port`` sends model traffic to the
local scripted mock instead of the real service (no model call).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time

from bio_ce.control_store import ControlStore, MODE_AUTO_MEMORY, control_database_for
from bio_ce.host_hooks import BIO_TOOLS, claude_tool_rules
from bio_ce.storage.sqlite_store import SQLiteMemoryStore

PROMPTS = {
    "A": "나는 프로그램을 개발할 때 CPU만으로도 돌아가는 구조를 선호해. GPU는 추가 가속용이면 좋겠어.",
    "B": "이번에 만드는 게임 엔진은 Windows를 우선 지원하고, Linux는 나중에 추가할 생각이야.",
    "C": "아까 말했듯이 내 개발 원칙은 CPU-first야.",
    "D": "게임 엔진 계획을 바꿨어. Linux도 첫 출시부터 지원할 거야.",
    "E": "오늘 점심으로 볶음밥을 먹었어. 그리고 테스트용 가짜 비밀번호 문자열을 하나 만들어 봤어.",
    "recall": "내 개발 원칙과 게임 엔진의 현재 지원 플랫폼 계획을 정리해 줘.",
}
CODEX_MODEL = os.environ.get("BIO_CE_CODEX_MODEL", "gpt-6.1-sol")
CODEX_GRACE_MS = int(os.environ.get("BIO_CE_CODEX_GRACE_MS", "3000"))  # documented Codex option; see the report
SCOPE_ARGS = ["--project", "bio-ce-personal", "--namespace", "default"]


def paths(root: Path, host: str) -> dict[str, Path]:
    base = root / host
    return {"base": base, "db": base / "data" / "memories.sqlite3", "work": base / "workdir",
            "grant": base / "grant.json", "logs": base / "runs"}


def setup(root: Path, host: str, exe: Path) -> None:
    p = paths(root, host)
    if p["db"].exists():
        raise SystemExit(f"{p['db']} already exists; refusing to reuse a test database")
    for key in ("work", "logs"):
        p[key].mkdir(parents=True, exist_ok=True)
    SQLiteMemoryStore(p["db"]).close()
    control = ControlStore(control_database_for(p["db"]))
    grant, token = control.create_grant(host)
    control.set_mode(grant.connection_id, MODE_AUTO_MEMORY)
    control.close()
    p["grant"].write_text(json.dumps({"connection_id": grant.connection_id, "token": token}), encoding="utf-8")
    server_args = ["mcp-stdio", "--db", str(p["db"]), *SCOPE_ARGS, "--connection", grant.connection_id]
    if host == "claude":
        hook = lambda event: {"type": "command", "command": str(exe), "timeout": 15 if event == "session-start" else 10,
                              "args": ["hook", event, "--host", "claude", "--db", str(p["db"]), "--connection",
                                       grant.connection_id, "--token", token]}
        settings = {
            "hooks": {
                "SessionStart": [{"matcher": "startup|resume|clear|compact", "hooks": [hook("session-start")]}],
                "UserPromptSubmit": [{"hooks": [hook("user-prompt")]}],
            },
            "permissions": {"allow": claude_tool_rules()},
            "autoMemoryEnabled": False,
            "claudeMdExcludes": ["**/CLAUDE.md", "**/CLAUDE.local.md", "**/AGENTS.md", "**/.claude/rules/**"],
        }
        (p["base"] / "claude-settings.json").write_text(json.dumps(settings, indent=2), encoding="utf-8")
        mcp = {"mcpServers": {"bio-ce": {"type": "stdio", "command": str(exe), "args": server_args,
                                         "env": {"BIO_CE_CONNECTION_TOKEN": token}}}}
        (p["base"] / "claude-mcp.json").write_text(json.dumps(mcp, indent=2), encoding="utf-8")
    print(f"setup {host}: db={p['db']} connection={grant.connection_id}")


def _toml_str(value: str) -> str:
    return "'" + value + "'" if "'" not in value else json.dumps(value)


def codex_command(root: Path, exe: Path, prompt: str, mock_port: int | None, grace: int | None) -> list[str]:
    p = paths(root, "codex")
    grant = json.loads(p["grant"].read_text(encoding="utf-8"))
    args = ", ".join(_toml_str(a) for a in ["mcp-stdio", "--db", str(p["db"]), *SCOPE_ARGS,
                                             "--connection", grant["connection_id"]])
    tools = ", ".join(f"{tool} = {{ approval_mode = \"approve\" }}" for tool in BIO_TOOLS)
    command_path = str(exe)
    wrap = os.environ.get("BIO_CE_SERVER_WRAP")  # debugging only: "python;wrapper.py;logfile"
    if wrap:
        python, wrapper, log = wrap.split(";")
        command_path = python
        args = ", ".join(_toml_str(a) for a in ["-I", wrapper, log, str(exe)]) + ", " + args
    server = (f"{{ command = {_toml_str(command_path)}, args = [{args}], "
              f"env = {{ BIO_CE_CONNECTION_TOKEN = {_toml_str(grant['token'])} }}"
              + ("" if os.environ.get("BIO_CE_NO_APPROVALS") else f", tools = {{ {tools} }}")
              + (", required = true" if os.environ.get("BIO_CE_REQUIRED") else "") + " }")
    command = [
        os.environ.get("BIO_CE_CODEX_EXE", "codex"), "exec", "--ignore-user-config", "--ephemeral", "--skip-git-repo-check", "--json",
        "-C", str(p["work"]), "--sandbox", "read-only", "-m", CODEX_MODEL,
        "--disable", "hooks", "--disable", "memories", "--disable", "multi_agent",
        *([] if os.environ.get("BIO_CE_KEEP_APPS") else ["--disable", "apps", "--disable", "plugins"]),
        "--disable", "browser_use", "--disable", "computer_use", "--disable", "goals",
        "--disable", "in_app_browser", "-c", 'web_search="disabled"', *os.environ.get("BIO_CE_CODEX_EXTRA", "").split(),
        "-c", f"mcp_servers.bio-ce={server}",
    ]
    if grace is not None:
        command += ["-c", f"mcp_optional_startup_grace_ms={grace}"]
    if mock_port is not None:
        command += ["-c", 'model_provider="biomock"', "-c",
                    f'model_providers.biomock={{ name = "BIO CE local mock", base_url = "http://127.0.0.1:{mock_port}/v1", '
                    'wire_api = "responses", env_key = "BIOMOCK_KEY" }']
    return command + [prompt]


def claude_command(root: Path, prompt: str) -> list[str]:
    p = paths(root, "claude")
    return [os.environ.get("BIO_CE_CLAUDE_EXE", "claude"), "-p", prompt, "--restricted", "--settings", str(p["base"] / "claude-settings.json"),
            "--mcp-config", str(p["base"] / "claude-mcp.json"), "--strict-mcp-config", "--no-session-persistence",
            "--output-format", "stream-json", "--verbose"]


def run(root: Path, host: str, exe: Path, step: str, mock_port: int | None, grace: int | None) -> int:
    p = paths(root, host)
    prompt = PROMPTS[step]
    env = dict(os.environ)
    env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] = "1"
    env.pop("ANTHROPIC_BASE_URL", None)
    env.pop("ANTHROPIC_API_KEY", None)
    if host == "codex":
        command = codex_command(root, exe, prompt, mock_port, grace)
        if mock_port is not None:
            env["BIOMOCK_KEY"] = "mock-not-a-real-key"
    else:
        command = claude_command(root, prompt)
        env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
        env["MCP_TIMEOUT"] = "30000"
        if mock_port is not None:
            env["ANTHROPIC_BASE_URL"] = f"http://127.0.0.1:{mock_port}"
            env["ANTHROPIC_API_KEY"] = "mock-not-a-real-key"
    tag = f"{step}{'-mock' if mock_port else ''}"
    started = time.time()
    completed = subprocess.run(command, cwd=p["work"], env=env, stdin=subprocess.DEVNULL, capture_output=True,
                               timeout=600)
    (p["logs"] / f"{tag}.raw").write_bytes(completed.stdout)
    stdout, stderr = _decode(completed.stdout), _decode(completed.stderr)
    (p["logs"] / f"{tag}.jsonl").write_text(stdout, encoding="utf-8")
    (p["logs"] / f"{tag}.stderr.txt").write_text(stderr, encoding="utf-8")
    meta = {"host": host, "step": step, "prompt": prompt, "mock": mock_port is not None, "exit": completed.returncode,
            "seconds": round(time.time() - started, 1), "grace_ms": grace if host == "codex" else None}
    (p["logs"] / f"{tag}.meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False))
    return completed.returncode


def _decode(data: bytes) -> str:
    """Host CLIs on Korean Windows may write the console code page (CP949) to a pipe."""
    text = data.decode("utf-8", errors="replace")
    if text.count("�") > len(text) // 20:  # mostly not UTF-8: likely the console code page
        return data.decode("cp949", errors="replace")
    return text


def main(argv: list[str]) -> int:
    action, root, host, exe = argv[0], Path(argv[1]).resolve(), argv[2], Path(argv[3]).resolve()
    if action == "setup":
        setup(root, host, exe)
        return 0
    step = argv[4]
    mock_port = int(argv[argv.index("--mock-port") + 1]) if "--mock-port" in argv else None
    grace = None if "--default-grace" in argv else CODEX_GRACE_MS
    return run(root, host, exe, step, mock_port, grace)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
