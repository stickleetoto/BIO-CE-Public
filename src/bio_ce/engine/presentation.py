# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""What the desktop app should show about engines, computed without Tk.

These view models turn the engine router's selection, engine statuses, and
negotiated capabilities into plain data a page can render: which engine is
active, whether it is connected, which actions are enabled (and why not), and
how to describe a write outcome. Pages stay thin and the rules stay testable.

Rules:

* With no selection the Community Engine is active; that is the normal state.
* SAFE_DISCONNECTED is shown as such, with no engine marked active and every
  memory action disabled. It is never presented as a working connection.
* An action is enabled only if its capability is usable on the active engine.
* Only a ``saved`` outcome is described as saved; ``pending_review`` says that
  nothing is stored until the user approves it.
* The user is told that each engine keeps its own memories.

Status: candidate, not yet used by the desktop pages.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from bio_ce.engine.community import COMMUNITY_ENGINE_ID
from bio_ce.engine.contract import (
    Capability,
    EngineState,
    EngineStatus,
    Support,
    WriteOutcome,
    WriteStatus,
)
from bio_ce.engine.switching import EngineSelection, SwitchPhase


SEPARATE_DATABASES_NOTE = (
    "Each memory engine keeps its own memories. Switching engines does not copy, move, or merge them; "
    "memories saved in one engine stay there."
)

# User actions in the desktop app and the capability each one needs.
ACTIONS: Mapping[str, Capability] = {
    "browse": Capability.MEMORY_LIST,
    "search": Capability.MEMORY_SEARCH,
    "open": Capability.MEMORY_GET,
    "history": Capability.MEMORY_HISTORY,
    "create": Capability.DIRECT_USER_EDIT,
    "edit": Capability.DIRECT_USER_EDIT,
    "retract": Capability.DIRECT_USER_EDIT,
    "review": Capability.REVIEW_QUEUE,
    "backup": Capability.BACKUP_RESTORE,
    "restore": Capability.BACKUP_RESTORE,
    "connect_host": Capability.HOST_AUTH,
}

_STATE_TEXT = {
    EngineState.READY: ("Connected", "success"),
    EngineState.NOT_INSTALLED: ("Not installed", "neutral"),
    EngineState.NOT_RUNNING: ("Not running", "warning"),
    EngineState.INCOMPATIBLE: ("Incompatible version", "error"),
    EngineState.UNAUTHORIZED: ("Access refused", "error"),
    EngineState.ERROR: ("Error", "error"),
}


@dataclass(frozen=True, slots=True)
class ActionState:
    action: str
    enabled: bool
    note: str = ""  # why it is disabled, or the limitation when enabled with "limited" support


@dataclass(frozen=True, slots=True)
class EngineRow:
    """One engine in the engine list (Settings or Connections)."""

    engine_id: str
    name: str
    state_text: str
    tone: str  # success | neutral | warning | error
    active: bool
    selectable: bool
    detail: str


@dataclass(frozen=True, slots=True)
class EngineBanner:
    """The always-visible line saying which engine the app is using."""

    title: str
    message: str
    tone: str
    connected: bool


@dataclass(frozen=True, slots=True)
class OutcomeMessage:
    title: str
    message: str
    tone: str
    stored: bool


def engine_name(engine_id: str, status: EngineStatus | None = None) -> str:
    if status is not None and status.descriptor is not None:
        return status.descriptor.display_name
    return {COMMUNITY_ENGINE_ID: "Community Engine", "core": "BIO Core"}.get(engine_id, engine_id)


def banner(selection: EngineSelection, active_status: EngineStatus | None) -> EngineBanner:
    if selection.phase is SwitchPhase.SAFE_DISCONNECTED or selection.binding is None:
        return EngineBanner(
            "No memory engine connected",
            (selection.message or "BIO CE stopped using the previous engine.")
            + " AI hosts cannot read or change memories until you choose an engine in Settings.",
            "warning", False,
        )
    name = engine_name(selection.engine_id or "", active_status)
    if active_status is None or not active_status.ready:
        reason = _STATE_TEXT.get(active_status.state if active_status else EngineState.ERROR, ("Error", "error"))[0]
        return EngineBanner(f"{name}: {reason.lower()}",
                            "Memories are unavailable right now. BIO CE does not switch to another engine on its own.",
                            "error", False)
    return EngineBanner(f"Using {name}", SEPARATE_DATABASES_NOTE, "success" if
                        selection.engine_id == COMMUNITY_ENGINE_ID else "neutral", True)


def engine_rows(selection: EngineSelection, statuses: Iterable[EngineStatus]) -> tuple[EngineRow, ...]:
    rows = []
    active_id = selection.binding.engine_id if selection.binding is not None else None
    for status in statuses:
        text, tone = _STATE_TEXT.get(status.state, ("Error", "error"))
        active = status.engine_id == active_id
        if status.state is EngineState.NOT_INSTALLED:
            detail = "Install it separately to use it from BIO CE. BIO CE works fully without it."
        elif status.ready:
            detail = status.descriptor.database_label if status.descriptor is not None else ""
        else:
            detail = status.message
        rows.append(EngineRow(status.engine_id, engine_name(status.engine_id, status), text, tone, active,
                              selectable=status.ready and not active, detail=detail))
    return tuple(sorted(rows, key=lambda row: (row.engine_id != COMMUNITY_ENGINE_ID, row.engine_id)))


def action_states(selection: EngineSelection, active_status: EngineStatus | None,
                  support: Mapping[Capability, Support]) -> dict[str, ActionState]:
    """Enabled/disabled state of every desktop action for the active engine."""
    if selection.binding is None:
        return {action: ActionState(action, False, "No memory engine is connected.") for action in ACTIONS}
    if active_status is None or not active_status.ready:
        return {action: ActionState(action, False, "The memory engine is unavailable.") for action in ACTIONS}
    name = engine_name(selection.binding.engine_id, active_status)
    states = {}
    for action, capability in ACTIONS.items():
        level = support.get(capability, Support.UNSUPPORTED)
        if level is Support.SUPPORTED:
            states[action] = ActionState(action, True)
        elif level is Support.LIMITED:
            states[action] = ActionState(action, True, f"Limited in {name}.")
        elif level is Support.UNVERIFIED:
            states[action] = ActionState(action, False, f"Not yet verified with {name} in this BIO CE version.")
        else:
            states[action] = ActionState(action, False, f"{name} does not offer this through BIO CE.")
    return states


def outcome_message(outcome: WriteOutcome) -> OutcomeMessage:
    status = outcome.status
    if status is WriteStatus.SAVED:
        return OutcomeMessage("Saved", "The memory was stored.", "success", True)
    if status is WriteStatus.PENDING_REVIEW:
        return OutcomeMessage("Waiting for your review",
                              "Nothing is stored until you approve it.", "info", False)
    if status is WriteStatus.DUPLICATE:
        return OutcomeMessage("Already remembered", "An equivalent memory exists; nothing new was stored.",
                              "info", False)
    if status is WriteStatus.CONFLICT:
        return OutcomeMessage("Changed meanwhile", "The memory changed before saving. Open it again and retry.",
                              "warning", False)
    if status is WriteStatus.REJECTED:
        return OutcomeMessage("Not stored", "; ".join(outcome.reasons) or "The engine's policy refused it.",
                              "warning", False)
    return OutcomeMessage("Not available", "This engine does not offer that change through BIO CE.", "warning",
                          False)


__all__ = [
    "ACTIONS", "ActionState", "EngineBanner", "EngineRow", "OutcomeMessage", "SEPARATE_DATABASES_NOTE",
    "action_states", "banner", "engine_name", "engine_rows", "outcome_message",
]
