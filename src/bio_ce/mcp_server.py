# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0
# BIO CE-7 candidate modification: licensing/provenance header added.
# BIO CE v0.3: per-connection grants and policy-checked memory writes.

"""Stdio MCP adapter for one explicitly configured BIO CE scope.

A connection created by the desktop app starts this server with
``--connection <id>`` and the matching token in ``BIO_CE_CONNECTION_TOKEN``.
The grant is authenticated once at startup and re-read on every tool call, so
switching a host to Read only, Paused, or disconnecting it in the app takes
effect on servers that are already running. Writes are allowed only in Auto
memory mode and always pass :mod:`bio_ce.memory_policy`.

A server started without a connection (a v0.2 host entry) serves reads only.

Scope: every server serves exactly one project and namespace. For a managed
connection that scope comes from the authenticated grant; ``--project`` and
``--namespace`` are optional and, when given, must match the grant. Tool calls
may omit ``project`` and ``namespace``; when a host passes them they must match
the bound scope exactly. A scope string never grants access by itself.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import sqlite3
from typing import Annotated, Any, Callable, TypeVar

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from bio_ce.auto_memory import AutoMemoryWriter
from bio_ce.control_store import AccessDenied, ControlStore, ControlStoreError, control_database_for
from bio_ce.core.models import (
    MemoryNotFoundError,
    MemoryScope,
    MemoryRevision,
    RevisionKind,
    SearchHit,
    SnapshotChangedError,
    ValidationError,
)
from bio_ce.memory_policy import CATEGORIES, CHANGE_TYPES, EVIDENCE, POLICY_TEXT
from bio_ce.storage.sqlite_store import SQLiteMemoryStore


TOKEN_ENVIRONMENT_VARIABLE = "BIO_CE_CONNECTION_TOKEN"
_SCOPE_HELP = "Optional. Omit it to use the scope this server is bound to; if given it must match exactly."
OptionalProject = Annotated[str | None, Field(description="Project. " + _SCOPE_HELP)]
OptionalNamespace = Annotated[str | None, Field(description="Namespace. " + _SCOPE_HELP)]
TOOL_NAMES = (
    "bio_memory_search",
    "bio_memory_read",
    "bio_memory_history",
    "bio_memory_create",
    "bio_memory_update",
    "bio_memory_retract",
)
_logger = logging.getLogger("bio_ce.mcp")
_T = TypeVar("_T")


class _Access:
    """Per-call authorization against the grant stored in the control database."""

    def __init__(self, control: ControlStore | None, connection_id: str | None, scope: MemoryScope) -> None:
        self.control = control
        self.connection_id = connection_id
        self.scope = scope

    def require_read(self) -> None:
        if self.control is None:
            return  # legacy v0.2 entry: read-only by construction
        try:
            grant = self.control.grant(self.connection_id)
        except (AccessDenied, ControlStoreError, sqlite3.Error):
            raise ToolError("BIO CE access for this connection is unavailable.") from None
        if (grant.project, grant.namespace) != (self.scope.project, self.scope.namespace):
            raise ToolError("BIO CE access for this connection is unavailable.")
        if not grant.active:
            raise ToolError("Access for this connection was revoked in BIO CE.")
        if not grant.can_read:
            raise ToolError("BIO CE access is paused for this connection. The user can resume it in BIO CE.")

    def writer(self, database: Path, scope: MemoryScope) -> AutoMemoryWriter:
        if self.control is None:
            raise ToolError("This is a read-only v0.2 connection. Reconnect the host in BIO CE to use Auto memory.")
        return AutoMemoryWriter(database, self.control, scope=scope, connection_id=self.connection_id)


def create_mcp_server(
    database: str | Path,
    *,
    project: str | None = None,
    namespace: str | None = None,
    connection_id: str | None = None,
    token: str | None = None,
) -> tuple[MCPServer, Callable[[], None]]:
    """Build a server bound to exactly one existing database scope; also return its close function.

    A managed connection takes its scope from the authenticated grant and refuses a
    different ``project``/``namespace``. A legacy (connection-less) server needs both.
    Reads use a long-lived SQLite ``mode=ro`` connection. Each permitted write
    opens a short-lived writable connection inside one atomic transaction.
    """
    database_path = Path(database).expanduser().resolve()
    control: ControlStore | None = None
    if connection_id is not None:
        control = ControlStore(control_database_for(database_path))
        try:
            grant = control.authenticate(connection_id, token or "")
            if (project is not None and project != grant.project) or (
                namespace is not None and namespace != grant.namespace
            ):
                raise AccessDenied("The configured project or namespace does not match this BIO CE connection.")
        except AccessDenied:
            control.close()
            raise
        scope = MemoryScope(grant.project, grant.namespace)
        mode_note = f"Current mode for this connection: {grant.mode.replace('_', ' ')}."
    else:
        if project is None or namespace is None:
            raise ValueError("a server without a BIO CE connection needs an explicit project and namespace")
        scope = MemoryScope(project, namespace)
        mode_note = "This connection is read-only."
    access = _Access(control, connection_id, scope)
    store = SQLiteMemoryStore(database_path, read_only=True)
    server = MCPServer(
        "BIO CE Memory",
        instructions=(
            "Long-term memory for the user, stored locally by BIO CE. This server is bound to project "
            f"{scope.project!r}, namespace {scope.namespace!r}. You can omit project and namespace on every "
            "call; if you pass them they must match exactly. Search before answering questions that may "
            "depend on the user's earlier preferences, decisions, or project context. "
            f"{mode_note} Writes work only when the user turned on Auto memory for this host.\n\n{POLICY_TEXT}"
        ),
    )

    def guarded_read(name: str, action: Callable[[], _T]) -> _T:
        access.require_read()
        try:
            return action()
        except SnapshotChangedError:
            raise ToolError("Memory changed during the request; retry.") from None
        except MemoryNotFoundError:
            raise ToolError("Memory is unavailable in the requested scope.") from None
        except ValidationError:
            raise ToolError("The request is invalid.") from None
        except sqlite3.Error:
            _logger.error("%s storage error", name)
            raise ToolError("Memory storage is unavailable.") from None

    def guarded_write(name: str, action: Callable[[AutoMemoryWriter], dict[str, Any]]) -> dict[str, Any]:
        writer = access.writer(database_path, scope)
        try:
            return action(writer)
        except AccessDenied as exc:
            raise ToolError(str(exc)) from None
        except MemoryNotFoundError:
            raise ToolError("Memory is unavailable in the requested scope.") from None
        except ValidationError as exc:
            raise ToolError(f"The request is invalid: {exc}") from None
        except (sqlite3.Error, ControlStoreError):
            _logger.error("%s storage error", name)
            raise ToolError("Memory storage is unavailable; nothing was changed.") from None

    @server.tool()
    def bio_memory_search(
        query: str,
        limit: Annotated[int, Field(ge=1, le=50)] = 10,
        project: OptionalProject = None,
        namespace: OptionalNamespace = None,
    ) -> dict[str, Any]:
        """Search the user's current memories by keywords. Use before creating a memory to avoid duplicates."""
        _require_exact_scope(scope, project, namespace)
        hits = guarded_read("bio_memory_search", lambda: store.search(scope, query, limit=limit))
        return {
            "project": scope.project,
            "namespace": scope.namespace,
            "results": [_search_hit_dict(hit) for hit in hits],
        }

    @server.tool()
    def bio_memory_read(
        memory_id: str,
        revision_id: str | None = None,
        project: OptionalProject = None,
        namespace: OptionalNamespace = None,
    ) -> dict[str, Any]:
        """Read one memory (its current revision unless revision_id is given)."""
        _require_exact_scope(scope, project, namespace)
        revision = guarded_read(
            "bio_memory_read", lambda: store.read(scope, memory_id, revision_id=revision_id)
        )
        return _revision_dict(revision)

    @server.tool()
    def bio_memory_history(
        memory_id: str,
        project: OptionalProject = None,
        namespace: OptionalNamespace = None,
    ) -> dict[str, Any]:
        """List every revision of a current memory, oldest first, with its source."""
        _require_exact_scope(scope, project, namespace)
        revisions = guarded_read("bio_memory_history", lambda: store.history(scope, memory_id))
        return {"memory_id": memory_id, "revisions": [_revision_dict(revision) for revision in revisions]}

    @server.tool()
    def bio_memory_create(
        title: Annotated[str, Field(max_length=512, description="Short label, e.g. 'Prefers tabs in Python'")],
        content: Annotated[str, Field(max_length=4000, description="The lasting fact in one or two sentences")],
        category: Annotated[str, Field(description="One of: " + ", ".join(CATEGORIES))],
        confidence: Annotated[str, Field(description="high, medium, or low")],
        evidence: Annotated[str, Field(description="One of: " + ", ".join(EVIDENCE))],
        reason: Annotated[str, Field(max_length=500, description="Why this is worth remembering")] = "",
        project: OptionalProject = None,
        namespace: OptionalNamespace = None,
    ) -> dict[str, Any]:
        """Store a new lasting memory about the user or project (Auto memory mode only).

        Search first. BIO CE refuses secrets and content from documents or tools, returns
        status "duplicate" for an equivalent memory, and queues uncertain items for the user.
        """
        _require_exact_scope(scope, project, namespace)
        return guarded_write("bio_memory_create", lambda writer: writer.create(
            title=title, content=content, category=category, confidence=confidence, evidence=evidence,
            reason=reason,
        ))

    @server.tool()
    def bio_memory_update(
        memory_id: str,
        expected_revision_id: Annotated[str, Field(description="revision_id from the latest read or search")],
        title: Annotated[str, Field(max_length=512)],
        content: Annotated[str, Field(max_length=4000)],
        change_type: Annotated[str, Field(description="One of: " + ", ".join(CHANGE_TYPES))],
        confidence: Annotated[str, Field(description="high, medium, or low")],
        evidence: Annotated[str, Field(description="One of: " + ", ".join(EVIDENCE))],
        reason: Annotated[str, Field(max_length=500)] = "",
        project: OptionalProject = None,
        namespace: OptionalNamespace = None,
    ) -> dict[str, Any]:
        """Replace a memory with a new revision (Auto memory mode only).

        Use change_type "correction" only when the user clearly corrected the stored fact. Use
        "conflict" when facts disagree and it is unclear which is right; BIO CE then asks the user.
        """
        _require_exact_scope(scope, project, namespace)
        return guarded_write("bio_memory_update", lambda writer: writer.update(
            memory_id=memory_id, expected_revision_id=expected_revision_id, title=title, content=content,
            change_type=change_type, confidence=confidence, evidence=evidence, reason=reason,
        ))

    @server.tool()
    def bio_memory_retract(
        memory_id: str,
        expected_revision_id: str,
        reason: Annotated[str, Field(max_length=500)] = "",
        project: OptionalProject = None,
        namespace: OptionalNamespace = None,
    ) -> dict[str, Any]:
        """Ask the user to retract a memory. Nothing is retracted until the user approves it in BIO CE.

        Retraction hides a memory from BIO CE and AI hosts; earlier revisions stay in the database file.
        """
        _require_exact_scope(scope, project, namespace)
        return guarded_write("bio_memory_retract", lambda writer: writer.request_retract(
            memory_id=memory_id, expected_revision_id=expected_revision_id, reason=reason,
        ))

    def close() -> None:
        store.close()
        if control is not None:
            control.close()

    return server, close


def run_mcp_stdio(
    database: str | Path,
    *,
    project: str | None = None,
    namespace: str | None = None,
    connection_id: str | None = None,
) -> int:
    """Run the local stdio server; stdout is reserved for MCP protocol frames."""
    token = os.environ.get(TOKEN_ENVIRONMENT_VARIABLE) if connection_id else None
    try:
        server, close = create_mcp_server(
            database, project=project, namespace=namespace, connection_id=connection_id, token=token
        )
    except AccessDenied as exc:
        _logger.error("%s", exc)
        return 3
    except ValueError as exc:
        _logger.error("%s", exc)
        return 2
    try:
        server.run("stdio")
    finally:
        close()
    return 0


def _require_exact_scope(configured: MemoryScope, project: str | None, namespace: str | None) -> None:
    """Accept an omitted scope (the bound one) or an exact match; refuse anything else."""
    if (project is not None and project != configured.project) or (
        namespace is not None and namespace != configured.namespace
    ):
        raise ToolError(
            "Requested project and namespace are unavailable to this server. It only serves project "
            f"{configured.project!r}, namespace {configured.namespace!r}. Omit project and namespace, or pass "
            "exactly these values."
        )


def _source_dict(source) -> dict[str, Any]:
    return {
        "source_type": source.source_type,
        "source_ref": source.source_ref,
        "metadata": dict(source.metadata),
    }


def _search_hit_dict(hit: SearchHit) -> dict[str, Any]:
    return {
        "memory_id": hit.memory_id,
        "revision_id": hit.revision_id,
        "rank": hit.rank,
        "score": hit.score,
        "title": hit.title,
        "preview": hit.preview,
        "source": _source_dict(hit.source),
        "recorded_at": hit.recorded_at,
        "valid_from": hit.valid_from,
        "valid_until": hit.valid_until,
    }


def _revision_dict(revision: MemoryRevision) -> dict[str, Any]:
    return {
        "memory_id": revision.memory_id,
        "revision_id": revision.revision_id,
        "revision_number": revision.revision_number,
        "kind": revision.kind.value,
        "project": revision.scope.project,
        "namespace": revision.scope.namespace,
        "title": revision.title,
        "content": revision.content if revision.kind is not RevisionKind.RETRACTION else None,
        "source": _source_dict(revision.source),
        "recorded_at": revision.recorded_at,
        "valid_from": revision.valid_from,
        "valid_until": revision.valid_until,
        "previous_revision_id": revision.previous_revision_id,
    }


__all__ = ["TOKEN_ENVIRONMENT_VARIABLE", "TOOL_NAMES", "create_mcp_server", "run_mcp_stdio"]
