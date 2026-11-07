# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Release stabilization: Korean/space paths end to end, and duplicate review requests.

Every path here is synthetic and temporary. The MCP server and the hook run as
real subprocesses, the way Codex and Claude Code start them.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from mcp import Client, StdioServerParameters, stdio_client

from bio_ce.auto_memory import AutoMemoryWriter, ReviewService
from bio_ce.control_store import ControlStore, MODE_AUTO_MEMORY, control_database_for
from bio_ce.core.models import MemoryScope
from bio_ce.desktop import AppDataPaths, DesktopMemoryService
from bio_ce.mcp_server import TOKEN_ENVIRONMENT_VARIABLE
from bio_ce.storage.backup import validate_database


SCOPE = MemoryScope("bio-ce-personal", "default")
REPO = Path(__file__).resolve().parents[2]


class KoreanAndSpacePathTests(unittest.TestCase):
    """A Windows user name or folder with Korean letters, spaces, and '#' must work everywhere."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="bio-ce-경로-")
        self.paths = AppDataPaths.under(Path(self.temp.name) / "사용자 데이터 #1" / "BIO CE")
        self.service = DesktopMemoryService(self.paths.user_database)
        self.korean = self.service.add(title="배포 일정", content="배포는 매주 금요일 오후에 진행한다.",
                                       source_ref="회의록 2026-11")
        self.english = self.service.add(title="Editor", content="The user edits release notes in Markdown.",
                                        source_ref="user-input")
        control = ControlStore(control_database_for(self.paths.user_database))
        self.grant, self.token = control.create_grant("claude", mode=MODE_AUTO_MEMORY)
        control.close()

    def tearDown(self) -> None:
        self.service.close()
        self.temp.cleanup()

    def test_desktop_store_search_backup_and_restore(self):
        self.assertEqual([hit.memory_id for hit in self.service.search("금요일")], [self.korean.memory_id])
        self.assertEqual([hit.memory_id for hit in self.service.search("markdown")], [self.english.memory_id])
        backup = self.service.create_backup(self.paths.root / "백업 폴더" / "bio ce 백업 #1.sqlite3")
        validate_database(backup, standalone=True)
        self.service.retract(self.service.read(self.english.memory_id))
        self.assertEqual(self.service.count(), 1)
        self.service.restore_backup(backup)
        self.assertEqual(self.service.count(), 2)
        self.assertEqual(self.service.read(self.korean.memory_id).source.source_ref, "회의록 2026-11")

    def test_mcp_server_subprocess_reads_and_writes_korean_text(self):
        self.service.close()  # like a closed desktop window; the server opens the files itself
        arguments = ["-m", "bio_ce", "mcp-stdio", "--db", str(self.paths.user_database),
                     "--connection", self.grant.connection_id]
        parameters = StdioServerParameters(command=sys.executable, args=arguments, cwd=str(REPO),
                                           env={**os.environ, TOKEN_ENVIRONMENT_VARIABLE: self.token})

        async def exercise():
            errlog = tempfile.TemporaryFile(mode="w+t", encoding="utf-8")
            try:
                async with Client(stdio_client(parameters, errlog=errlog)) as client:
                    found = await client.call_tool("bio_memory_search", {"query": "배포 금요일"})
                    created = await client.call_tool("bio_memory_create", {
                        "title": "선호 언어", "content": "사용자는 답변을 한국어로 받는 것을 선호한다.",
                        "category": "preference", "confidence": "high", "evidence": "user_stated"})
                    return found, created
            finally:
                errlog.close()

        found, created = asyncio.run(asyncio.wait_for(exercise(), timeout=60))
        self.assertFalse(found.is_error, found)
        self.assertEqual(found.structured_content["results"][0]["title"], "배포 일정")
        self.assertEqual(created.structured_content["status"], "created", created)
        self.service = DesktopMemoryService(self.paths.user_database)
        self.assertIn("선호 언어", {revision.title for revision in self.service.list()})

    def test_hook_subprocess_prints_utf8_context_for_a_korean_prompt(self):
        payload = json.dumps({"prompt": "배포 일정이 언제였지?", "cwd": str(self.paths.root)}, ensure_ascii=False)
        completed = subprocess.run(
            [sys.executable, "-m", "bio_ce", "hook", "user-prompt", "--host", "claude",
             "--db", str(self.paths.user_database), "--connection", self.grant.connection_id,
             f"--token={self.token}"],
            input=payload.encode("utf-8"), capture_output=True, cwd=REPO, timeout=60)
        self.assertEqual(completed.returncode, 0, completed.stderr.decode("utf-8", "replace"))
        context = json.loads(completed.stdout.decode("utf-8"))["hookSpecificOutput"]["additionalContext"]
        self.assertIn("배포는 매주 금요일", context)


class DuplicateReviewRequestTests(unittest.TestCase):
    """A host that repeats the same uncertain proposal must not fill the queue with copies."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="bio-ce-dup-review-")
        self.database = Path(self.temp.name) / "data" / "memories.sqlite3"
        self.service = DesktopMemoryService(self.database)
        self.control = ControlStore(control_database_for(self.database))
        grant, _token = self.control.create_grant("codex", mode=MODE_AUTO_MEMORY)
        self.writer = AutoMemoryWriter(self.database, self.control, scope=SCOPE, connection_id=grant.connection_id)

    def tearDown(self) -> None:
        self.control.close()
        self.service.close()
        self.temp.cleanup()

    def propose(self, content="The user might prefer a standing desk in the afternoon."):
        return self.writer.create(title="Standing desk", content=content, category="preference",
                                  confidence="medium", evidence="inferred")

    def test_the_same_uncertain_proposal_is_queued_once(self):
        first, second = self.propose(), self.propose()
        self.assertEqual(first["status"], "queued_for_review")
        self.assertEqual(second["status"], "queued_for_review")
        self.assertEqual(second["review_id"], first["review_id"], "the repeat points at the pending item")
        self.assertEqual(self.control.pending_review_count(), 1)
        ReviewService(self.service._store, self.control, SCOPE).approve(first["review_id"])
        self.assertEqual(self.service.count(), 1)

    def test_a_different_proposal_is_queued_separately(self):
        self.propose()
        self.propose(content="The user might prefer a quiet room for long calls.")
        self.assertEqual(self.control.pending_review_count(), 2)

    def test_a_repeated_retraction_request_is_queued_once(self):
        memory = self.service.add(title="Lab server", content="The lab server is build-07.", source_ref="user-input")
        first = self.writer.request_retract(memory_id=memory.memory_id, expected_revision_id=memory.revision_id)
        second = self.writer.request_retract(memory_id=memory.memory_id, expected_revision_id=memory.revision_id)
        self.assertEqual(second["review_id"], first["review_id"])
        self.assertEqual(self.control.pending_review_count(), 1)

    def test_a_handled_proposal_can_be_proposed_again(self):
        first = self.propose()
        ReviewService(self.service._store, self.control, SCOPE).reject(first["review_id"])
        again = self.propose()
        self.assertNotEqual(again["review_id"], first["review_id"], "a rejected item is not reused")
        self.assertEqual(self.control.pending_review_count(), 1)


if __name__ == "__main__":
    unittest.main()
