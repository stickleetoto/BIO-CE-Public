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
import threading
from contextlib import AbstractContextManager, nullcontext
from typing import Annotated, Any, Callable, TypeVar

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from bio_ce import display_version
from bio_ce.auto_memory import AutoMemoryWriter
from bio_ce.server_lifetime import ServerLifetime, idle_seconds_from, parent_process_id, release_seconds_from
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
from bio_ce.spaces import (
    CURATED_NAMESPACE,
    GENERAL_PROJECT,
    RESOLVED_EXACT,
    RESOLVED_FALLBACK,
    Resolution,
    Space,
    resolve_space,
)
from bio_ce.storage.sqlite_store import INBOX_SUFFIX, SQLiteMemoryStore


TOKEN_ENVIRONMENT_VARIABLE = "BIO_CE_CONNECTION_TOKEN"
_SCOPE_HELP = "Optional. Omit it to use the scope this server is bound to; if given it must match exactly."
OptionalProject = Annotated[str | None, Field(description="Project. " + _SCOPE_HELP)]
OptionalNamespace = Annotated[str | None, Field(description="Namespace. " + _SCOPE_HELP)]
OptionalSpace = Annotated[str | None, Field(description=(
    "Optional BIO CE space: General or a project space, by name. Omit it for General. A name BIO CE can't match "
    "to exactly one space also uses General, and the result says so."))]
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


class _Connections:
    """The server's long-lived SQLite connections: opened on demand and closed while the server is idle.

    Releasing closes both connections and checkpoints the write-ahead logs, so an idle server holds no
    database file open (a restore in the desktop app, or an upgrade, is then not blocked). The next
    request opens them again.
    """

    def __init__(self, database: Path, control: ControlStore | None) -> None:
        self.database = database
        self.managed = control is not None
        self._control = control
        self._store: SQLiteMemoryStore | None = None
        self._lock = threading.RLock()

    def store(self) -> SQLiteMemoryStore:
        with self._lock:
            if self._store is None:
                self._store = SQLiteMemoryStore(self.database, read_only=True)
            return self._store

    def control(self) -> ControlStore | None:
        with self._lock:
            if self.managed and self._control is None:
                self._control = ControlStore(control_database_for(self.database))
            return self._control

    def release(self) -> None:
        with self._lock:
            self.close()
            for path in (self.database, control_database_for(self.database)):
                _checkpoint(path)

    def close(self) -> None:
        with self._lock:
            if self._store is not None:
                self._store.close()
                self._store = None
            if self._control is not None:
                self._control.close()
                self._control = None


def _checkpoint(path: Path) -> None:
    """Fold a leftover write-ahead log back into the database file. Best effort: busy is fine."""
    if not path.with_name(path.name + "-wal").exists():
        return
    try:
        connection = sqlite3.connect(f"{path.as_uri()}?mode=rw", uri=True, timeout=1)
    except sqlite3.Error:
        return
    try:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.Error:
        pass
    finally:
        connection.close()


class _StoreProxy:
    """Lets tool code use ``store`` while the connection behind it is opened on demand."""

    def __init__(self, connections: _Connections) -> None:
        self._connections = connections

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connections.store(), name)


class _Access:
    """Per-call authorization against the grant stored in the control database."""

    def __init__(self, connections: _Connections, connection_id: str | None, scope: MemoryScope) -> None:
        self._connections = connections
        self.connection_id = connection_id
        self.scope = scope

    @property
    def control(self) -> ControlStore | None:
        return self._connections.control()

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
        control = self.control
        if control is None:
            raise ToolError("This is a read-only v0.2 connection. Reconnect the host in BIO CE to use Auto memory.")
        return AutoMemoryWriter(database, control, scope=scope, connection_id=self.connection_id)


def create_mcp_server(
    database: str | Path,
    *,
    project: str | None = None,
    namespace: str | None = None,
    connection_id: str | None = None,
    token: str | None = None,
    activity: Callable[[], AbstractContextManager[Any]] | None = None,
    release_hook: list[Callable[[], None]] | None = None,
) -> tuple[MCPServer, Callable[[], None]]:
    """Build a server bound to exactly one existing database scope; also return its close function.

    A managed connection takes its scope from the authenticated grant and refuses a
    different ``project``/``namespace``. A legacy (connection-less) server needs both.
    Reads use a long-lived SQLite ``mode=ro`` connection. Each permitted write
    opens a short-lived writable connection inside one atomic transaction.
    ``activity`` (optional) wraps every tool request, for example to reset an idle timer.
    ``release_hook`` (optional) receives a function that closes the database connections while idle.
    """
    request_activity = activity or nullcontext
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
    connections = _Connections(database_path, control)
    if release_hook is not None:
        release_hook.append(connections.release)
    access = _Access(connections, connection_id, scope)
    store = _StoreProxy(connections)
    connections.store()  # fail at startup, not on the first call, if the database cannot be opened
    legacy_space = Space("bound", "general", scope.project, f"{scope.project}/{scope.namespace}")

    def resolve(space: str | None, project: str | None, namespace: str | None, *, write: bool) -> Resolution:
        """Pick the space for one call. Unknown or ambiguous names use General; a denial is never redirected."""
        control_store = access.control
        if control_store is None or (scope.project, scope.namespace) != (GENERAL_PROJECT, CURATED_NAMESPACE):
            # A v0.2 entry, or a grant bound to another scope: exactly that scope, no spaces.
            _require_exact_scope(scope, project, namespace)
            if space is not None:
                raise ToolError("This connection serves one fixed scope; omit space.")
            return Resolution(legacy_space, "default")
        if namespace is not None and namespace.endswith(INBOX_SUFFIX):
            raise ToolError("The inbox can't be addressed through project and namespace.")
        try:
            spaces = control_store.spaces()
        except (ControlStoreError, sqlite3.Error):
            raise ToolError("BIO CE access for this connection is unavailable.") from None
        if project is not None or namespace is not None:
            wanted = project if project is not None else scope.project
            match = next((item for item in spaces if item.project == wanted), None)
            if match is None or namespace not in (None, CURATED_NAMESPACE):
                _require_exact_scope(scope, project, namespace)  # raises with the bound-scope message
                match = next(item for item in spaces if item.is_general)
            resolution = Resolution(match, RESOLVED_EXACT)
            if space is not None and resolve_space(spaces, space).space.space_id != match.space_id:
                raise ToolError("space and project/namespace point to different BIO CE spaces; pass only one.")
        else:
            resolution = resolve_space(spaces, space)
        can_read, can_write = control_store.space_access(connection_id, resolution.space)
        grant_can_write = control_store.grant(connection_id).can_write
        if (write and grant_can_write and not can_write) or (not write and not can_read and _readable(access)):
            name = resolution.space.display_name
            if resolution.how == RESOLVED_FALLBACK:
                raise ToolError(f"BIO CE couldn't match the space {space!r} ({resolution.reason}), so it used "
                                f"General, but this connection has no {'write' if write else 'read'} access to "
                                "General.")
            raise ToolError(f"This connection has no {'write' if write else 'read'} access to the BIO CE space "
                            f"{name!r}. The user can change this in BIO CE → Connections.")
        return resolution

    def readable_spaces() -> list[str]:
        control_store = access.control
        if control_store is None or (scope.project, scope.namespace) != (GENERAL_PROJECT, CURATED_NAMESPACE):
            return []
        try:
            return [item.display_name for item in control_store.spaces()
                    if control_store.space_access(connection_id, item)[0]]
        except (ControlStoreError, sqlite3.Error):
            return []

    names = readable_spaces()
    saving_note = ""
    if access.control is not None and (scope.project, scope.namespace) == (GENERAL_PROJECT, CURATED_NAMESPACE):
        try:
            collecting = access.control.connection_settings(connection_id)["save_mode"] == "collect"
        except (ControlStoreError, sqlite3.Error):
            collecting = False
        saving_note = (" Saving mode: collect. bio_memory_create saves to the user's inbox, which the user sorts in "
                       "BIO CE; search leaves the inbox out unless you pass include_inbox." if collecting else
                       " Saving mode: curated. Only what the user stated or confirmed is stored; the rest waits for "
                       "the user's review.")
    spaces_note = (
        " Spaces this connection can use: " + ", ".join(repr(name) for name in names) + ". Pass space to use a "
        "project space; without it, or when the name doesn't match exactly one space, BIO CE uses General."
        if len(names) > 1 else ""
    )
    server = MCPServer(
        "BIO CE Memory",
        version=display_version(),
        instructions=(
            "Long-term memory for the user, stored locally by BIO CE. This server is bound to project "
            f"{scope.project!r}, namespace {scope.namespace!r}. You can omit project and namespace on every "
            "call; if you pass them they must match exactly. Search before answering questions that may "
            "depend on the user's earlier preferences, decisions, or project context. "
            f"{mode_note} Writes work only when the user turned on Auto memory for this host.{saving_note}{spaces_note}"
            f"\n\n{POLICY_TEXT}"
        ),
    )

    def guarded_read(name: str, action: Callable[[], _T]) -> _T:
        with request_activity():
            return _guarded_read(name, action)

    def _guarded_read(name: str, action: Callable[[], _T]) -> _T:
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

    def guarded_write(name: str, action: Callable[[AutoMemoryWriter], dict[str, Any]], *, space: str | None,
                      project: str | None, namespace: str | None) -> dict[str, Any]:
        with request_activity():
            return _guarded_write(name, action, space, project, namespace)

    def _guarded_write(name: str, action: Callable[[AutoMemoryWriter], dict[str, Any]], space: str | None,
                       project: str | None, namespace: str | None) -> dict[str, Any]:
        try:
            resolution = resolve(space, project, namespace, write=True)
            writer = access.writer(database_path, _curated(resolution, scope))
            result = action(writer)
            return {**_space_fields(resolution, access), **result}
        except AccessDenied as exc:
            raise ToolError(str(exc)) from None
        except MemoryNotFoundError:
            raise ToolError("Memory is unavailable in the requested scope.") from None
        except ValidationError as exc:
            raise ToolError(f"The request is invalid: {exc}") from None
        except (sqlite3.Error, ControlStoreError):
            _logger.error("%s storage error", name)
            raise ToolError("Memory storage is unavailable; nothing was changed.") from None

    def touch(memory_ids: list[str]) -> None:
        """Record that inbox items were used; a failure here never blocks the answer."""
        control_store = access.control
        if control_store is None or not memory_ids:
            return
        try:
            control_store.touch_inbox(memory_ids)
        except Exception:  # noqa: BLE001
            _logger.warning("inbox usage not recorded")

    def find(target: MemoryScope, resolution: Resolution, action: Callable[[MemoryScope], _T]) -> tuple[_T, str]:
        """Run a read in the curated scope, then in the space's inbox; returns the result and its stage."""
        try:
            return action(target), "curated"
        except MemoryNotFoundError:
            if resolution.space.space_id == "bound":
                raise
            return action(resolution.space.inbox), "inbox"

    @server.tool()
    def bio_memory_search(
        query: str,
        limit: Annotated[int, Field(ge=1, le=50)] = 10,
        space: OptionalSpace = None,
        include_inbox: Annotated[bool, Field(description=(
            "Also search the inbox (collected, not yet sorted by the user). Inbox results come after curated "
            "ones and are marked stage 'inbox'."))] = False,
        project: OptionalProject = None,
        namespace: OptionalNamespace = None,
    ) -> dict[str, Any]:
        """Search the user's current memories by keywords. Use before creating a memory to avoid duplicates."""
        resolution = guarded_read("bio_memory_search", lambda: resolve(space, project, namespace, write=False))
        target = _curated(resolution, scope)
        hits = guarded_read("bio_memory_search", lambda: store.search(target, query, limit=limit))
        results = [{**_search_hit_dict(hit), "stage": "curated"} for hit in hits]
        if include_inbox and resolution.space.space_id != "bound" and len(results) < limit:
            inbox_hits = guarded_read("bio_memory_search", lambda: store.search(
                resolution.space.inbox, query, limit=limit - len(results)))
            results += [{**_search_hit_dict(hit), "stage": "inbox"} for hit in inbox_hits]
            touch([hit.memory_id for hit in inbox_hits])
        return {
            "project": target.project,
            "namespace": target.namespace,
            **_space_fields(resolution, access),
            "results": results,
        }

    @server.tool()
    def bio_memory_read(
        memory_id: str,
        revision_id: str | None = None,
        space: OptionalSpace = None,
        project: OptionalProject = None,
        namespace: OptionalNamespace = None,
    ) -> dict[str, Any]:
        """Read one memory (its current revision unless revision_id is given)."""
        resolution = guarded_read("bio_memory_read", lambda: resolve(space, project, namespace, write=False))
        target = _curated(resolution, scope)
        revision, stage = guarded_read("bio_memory_read", lambda: find(
            target, resolution, lambda where: store.read(where, memory_id, revision_id=revision_id)))
        if stage == "inbox":
            touch([memory_id])
        return {**_revision_dict(revision), **_space_fields(resolution, access), **_stage(stage, access)}

    @server.tool()
    def bio_memory_history(
        memory_id: str,
        space: OptionalSpace = None,
        project: OptionalProject = None,
        namespace: OptionalNamespace = None,
    ) -> dict[str, Any]:
        """List every revision of a current memory, oldest first, with its source."""
        resolution = guarded_read("bio_memory_history", lambda: resolve(space, project, namespace, write=False))
        target = _curated(resolution, scope)
        revisions, stage = guarded_read("bio_memory_history", lambda: find(
            target, resolution, lambda where: store.history(where, memory_id)))
        return {"memory_id": memory_id, **_space_fields(resolution, access), **_stage(stage, access),
                "revisions": [_revision_dict(revision) for revision in revisions]}

    @server.tool()
    def bio_memory_create(
        title: Annotated[str, Field(max_length=512, description="Short label, e.g. 'Prefers tabs in Python'")],
        content: Annotated[str, Field(max_length=4000, description="The lasting fact in one or two sentences")],
        category: Annotated[str, Field(description="One of: " + ", ".join(CATEGORIES))],
        confidence: Annotated[str, Field(description="high, medium, or low")],
        evidence: Annotated[str, Field(description="One of: " + ", ".join(EVIDENCE))],
        reason: Annotated[str, Field(max_length=500, description="Why this is worth remembering")] = "",
        space: OptionalSpace = None,
        project: OptionalProject = None,
        namespace: OptionalNamespace = None,
    ) -> dict[str, Any]:
        """Store a new lasting memory about the user or project (Auto memory mode only).

        Search first. BIO CE refuses secrets and content from documents or tools, returns
        status "duplicate" for an equivalent memory, and queues uncertain items for the user.
        """
        return guarded_write("bio_memory_create", lambda writer: writer.create(
            title=title, content=content, category=category, confidence=confidence, evidence=evidence,
            reason=reason,
        ), space=space, project=project, namespace=namespace)

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
        space: OptionalSpace = None,
        project: OptionalProject = None,
        namespace: OptionalNamespace = None,
    ) -> dict[str, Any]:
        """Replace a memory with a new revision (Auto memory mode only).

        Use change_type "correction" only when the user clearly corrected the stored fact. Use
        "conflict" when facts disagree and it is unclear which is right; BIO CE then asks the user.
        """
        return guarded_write("bio_memory_update", lambda writer: writer.update(
            memory_id=memory_id, expected_revision_id=expected_revision_id, title=title, content=content,
            change_type=change_type, confidence=confidence, evidence=evidence, reason=reason,
        ), space=space, project=project, namespace=namespace)

    @server.tool()
    def bio_memory_retract(
        memory_id: str,
        expected_revision_id: str,
        reason: Annotated[str, Field(max_length=500)] = "",
        space: OptionalSpace = None,
        project: OptionalProject = None,
        namespace: OptionalNamespace = None,
    ) -> dict[str, Any]:
        """Ask the user to retract a memory. Nothing is retracted until the user approves it in BIO CE.

        Retraction hides a memory from BIO CE and AI hosts; earlier revisions stay in the database file.
        """
        return guarded_write("bio_memory_retract", lambda writer: writer.request_retract(
            memory_id=memory_id, expected_revision_id=expected_revision_id, reason=reason,
        ), space=space, project=project, namespace=namespace)

    def close() -> None:
        connections.close()

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
    release: list[Callable[[], None]] = []
    lifetime = ServerLifetime(
        lambda _reason: _end_process(close),
        idle_seconds=idle_seconds_from(os.environ),
        parent_pid=parent_process_id(),
        release_seconds=release_seconds_from(os.environ),
        on_release=lambda: release[0]() if release else None,
    )
    try:
        server, close = create_mcp_server(
            database, project=project, namespace=namespace, connection_id=connection_id, token=token,
            activity=lifetime.activity, release_hook=release,
        )
    except AccessDenied as exc:
        _logger.error("%s", exc)
        return 3
    except ValueError as exc:
        _logger.error("%s", exc)
        return 2
    lifetime.start()
    try:
        server.run("stdio")  # returns when the host closes stdin
    finally:
        close()
    return 0


def _end_process(close: Callable[[], None]) -> None:
    """End a server whose host is gone or idle. The stdin reader cannot be interrupted, so exit directly."""
    try:
        close()
    finally:
        os._exit(0)


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


def _readable(access: "_Access") -> bool:
    """Whether the grant itself allows reading; a paused or revoked grant gets require_read's message instead."""
    control = access.control
    if control is None:
        return True
    try:
        return control.grant(access.connection_id).can_read
    except (ControlStoreError, sqlite3.Error):
        return False


def _stage(stage: str, access: "_Access") -> dict[str, Any]:
    return {} if access.control is None else {"stage": stage}


def _curated(resolution: Resolution, bound: MemoryScope) -> MemoryScope:
    return bound if resolution.space.space_id == "bound" else resolution.space.curated


def _space_fields(resolution: Resolution, access: "_Access") -> dict[str, Any]:
    if access.control is None or resolution.space.space_id == "bound":
        return {}
    return {**resolution.as_result(), "stage": "curated"}


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
