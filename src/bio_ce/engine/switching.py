# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Choosing which engine a BIO CE client talks to, and switching safely.

Switching changes *where* reads and writes go. It never copies, merges, or
migrates memories: each engine keeps its own database. The sequence is::

    ACTIVE(old) -> QUIESCE -> REVOKE_OLD -> NEGOTIATE -> BIND_NEW -> VERIFY -> ACTIVE(new)

* QUIESCE closes the write gate and bumps the binding generation, so every
  request still carrying the old binding is refused from then on, including a
  request that would otherwise reach the new engine.
* REVOKE_OLD must succeed before anything is bound to the new engine.
* Any failure ends in SAFE_DISCONNECTED: no engine is active and nothing falls
  back silently. The user recovers by explicitly choosing an engine again.
* The selection is persisted before and after the switch. A crash in between
  is found on the next start and also ends in SAFE_DISCONNECTED.

Status: client-side state machine, verified with the Community Engine and
synthetic engines. It is not yet wired into the desktop app.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
import os
from pathlib import Path
import threading
from typing import Callable, Mapping
import uuid

from bio_ce.engine.contract import (
    EngineBackend,
    EngineBinding,
    EngineError,
    StaleEngineBinding,
    negotiate,
)
from bio_ce.engine.community import COMMUNITY_ENGINE_ID


_SELECTION_VERSION = 1


class SwitchPhase(StrEnum):
    ACTIVE = "active"
    QUIESCE = "quiesce"
    REVOKE_OLD = "revoke_old"
    NEGOTIATE = "negotiate"
    BIND_NEW = "bind_new"
    VERIFY = "verify"
    SAFE_DISCONNECTED = "safe_disconnected"


class SwitchError(EngineError):
    def __init__(self, phase: SwitchPhase, message: str) -> None:
        super().__init__(message)
        self.phase = phase


@dataclass(frozen=True, slots=True)
class EngineSelection:
    """What is persisted: the active engine (or none) and the binding generation."""

    phase: SwitchPhase
    engine_id: str | None
    generation: int
    target_engine_id: str | None = None
    message: str = ""

    @property
    def binding(self) -> EngineBinding | None:
        if self.phase is not SwitchPhase.ACTIVE or self.engine_id is None:
            return None
        return EngineBinding(self.engine_id, self.generation)


DEFAULT_SELECTION = EngineSelection(SwitchPhase.ACTIVE, COMMUNITY_ENGINE_ID, 0)


class SelectionStore:
    """A small JSON file; a missing file means the default (Community Engine)."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> EngineSelection:
        if not self.path.is_file():
            return DEFAULT_SELECTION
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("version") != _SELECTION_VERSION:
                raise ValueError
            selection = EngineSelection(SwitchPhase(data["phase"]), data.get("engine_id"), int(data["generation"]),
                                        data.get("target_engine_id"), str(data.get("message") or ""))
        except (OSError, ValueError, KeyError, TypeError):
            # An unreadable selection never picks an engine by itself.
            return EngineSelection(SwitchPhase.SAFE_DISCONNECTED, None, 0,
                                   message="The engine selection could not be read. Choose an engine.")
        if selection.phase not in (SwitchPhase.ACTIVE, SwitchPhase.SAFE_DISCONNECTED):
            # A switch was interrupted (crash or power loss): stay disconnected until the user decides.
            return EngineSelection(SwitchPhase.SAFE_DISCONNECTED, None, selection.generation + 1,
                                   message="A previous engine switch did not finish. Choose an engine again.")
        return selection

    def save(self, selection: EngineSelection) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({
            "version": _SELECTION_VERSION, "phase": selection.phase.value, "engine_id": selection.engine_id,
            "generation": selection.generation, "target_engine_id": selection.target_engine_id,
            "message": selection.message,
        }, sort_keys=True)
        temporary = self.path.with_name(f"{self.path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(payload + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)


@dataclass(frozen=True, slots=True)
class SwitchHooks:
    """Side effects the switch needs; each must raise to stop the switch.

    ``revoke_old(engine_id)`` revokes every host grant/session of the old engine.
    ``bind_new(engine_id, generation)`` creates or verifies host bindings for the new engine.
    ``verify(backend)`` runs a read-only smoke check against the new engine.
    """

    revoke_old: Callable[[str], None]
    bind_new: Callable[[str, int], None]
    verify: Callable[[EngineBackend], None]


class EngineRouter:
    """Holds the active engine and refuses requests made for any other binding."""

    def __init__(
        self,
        backends: Mapping[str, EngineBackend],
        store: SelectionStore,
        hooks: SwitchHooks,
    ) -> None:
        self._backends = dict(backends)
        self._store = store
        self._hooks = hooks
        self._lock = threading.RLock()
        self._selection = store.load()
        if self._selection.engine_id is not None and self._selection.engine_id not in self._backends:
            self._selection = EngineSelection(SwitchPhase.SAFE_DISCONNECTED, None, self._selection.generation + 1,
                                              message="The selected engine is not available. Choose an engine.")

    @property
    def selection(self) -> EngineSelection:
        with self._lock:
            return self._selection

    def current_binding(self) -> EngineBinding | None:
        return self.selection.binding

    def guard(self, binding: EngineBinding) -> None:
        """Raise unless ``binding`` is the current, active binding."""
        with self._lock:
            if self._selection.binding != binding:
                raise StaleEngineBinding(
                    "This request belongs to an engine connection that is no longer active. Nothing was changed."
                )

    def backend_for(self, binding: EngineBinding) -> EngineBackend:
        """The backend a request made under ``binding`` may use, or :class:`StaleEngineBinding`."""
        with self._lock:
            self.guard(binding)
            return self._backends[binding.engine_id]

    def active_backend(self) -> EngineBackend | None:
        binding = self.current_binding()
        return None if binding is None else self._backends[binding.engine_id]

    def switch_to(self, engine_id: str) -> EngineSelection:
        """Run the full switch. Returns the new selection or raises :class:`SwitchError` (then disconnected)."""
        with self._lock:
            if engine_id not in self._backends:
                raise SwitchError(SwitchPhase.NEGOTIATE, "That engine is not available in this BIO CE client.")
            old = self._selection
            if old.phase is SwitchPhase.ACTIVE and old.engine_id == engine_id:
                return old
            generation = old.generation + 1
            # QUIESCE: from here on, no request with the old binding is accepted anywhere.
            self._set(EngineSelection(SwitchPhase.QUIESCE, old.engine_id, generation, engine_id))
            try:
                if old.engine_id is not None:
                    self._set(EngineSelection(SwitchPhase.REVOKE_OLD, old.engine_id, generation, engine_id))
                    self._step(SwitchPhase.REVOKE_OLD, lambda: self._hooks.revoke_old(old.engine_id))
                self._set(EngineSelection(SwitchPhase.NEGOTIATE, None, generation, engine_id))
                backend = self._backends[engine_id]
                status = self._step(SwitchPhase.NEGOTIATE, backend.status)
                if not status.ready or status.descriptor is None:
                    raise SwitchError(SwitchPhase.NEGOTIATE, status.message or "The engine is not ready.")
                if status.descriptor.engine_id != engine_id or not negotiate(status.descriptor).compatible:
                    raise SwitchError(SwitchPhase.NEGOTIATE, "The engine is not compatible with this client.")
                self._set(EngineSelection(SwitchPhase.BIND_NEW, None, generation, engine_id))
                self._step(SwitchPhase.BIND_NEW, lambda: self._hooks.bind_new(engine_id, generation))
                self._set(EngineSelection(SwitchPhase.VERIFY, None, generation, engine_id))
                self._step(SwitchPhase.VERIFY, lambda: self._hooks.verify(backend))
            except SwitchError as exc:
                self._set(EngineSelection(SwitchPhase.SAFE_DISCONNECTED, None, generation, engine_id, str(exc)))
                raise
            self._set(EngineSelection(SwitchPhase.ACTIVE, engine_id, generation))
            return self._selection

    def _step(self, phase: SwitchPhase, action):
        try:
            return action()
        except SwitchError:
            raise
        except Exception as exc:
            raise SwitchError(phase, f"The engine switch stopped at {phase.value.replace('_', ' ')}.") from exc

    def _set(self, selection: EngineSelection) -> None:
        # Persist first: if saving fails the in-memory state is not advanced either.
        self._store.save(selection)
        self._selection = selection


__all__ = [
    "DEFAULT_SELECTION", "EngineRouter", "EngineSelection", "SelectionStore", "SwitchError", "SwitchHooks",
    "SwitchPhase",
]
