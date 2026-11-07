# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Engine view models: Community by default, honest disconnected state, capability gating, honest outcomes."""

from __future__ import annotations

import unittest
from pathlib import Path

from bio_ce.engine.community import COMMUNITY_CAPABILITIES, community_descriptor
from bio_ce.engine.contract import Capability, EngineState, EngineStatus, Support, WriteOutcome, WriteStatus
from bio_ce.engine.external import ExternalEngineAdapter
from bio_ce.engine.presentation import (
    ACTIONS,
    SEPARATE_DATABASES_NOTE,
    action_states,
    banner,
    engine_rows,
    outcome_message,
)
from bio_ce.engine.switching import DEFAULT_SELECTION, EngineSelection, SwitchPhase
from tests.engine_fixtures import SyntheticTransport


COMMUNITY_READY = EngineStatus("community", EngineState.READY, "Ready", community_descriptor(Path("memories.sqlite3")),
                               1)
DISCONNECTED = EngineSelection(SwitchPhase.SAFE_DISCONNECTED, None, 3, "core",
                               "The engine switch stopped at verify.")


class PresentationTests(unittest.TestCase):
    def test_default_is_community_connected_with_every_action_enabled(self):
        shown = banner(DEFAULT_SELECTION, COMMUNITY_READY)
        self.assertTrue(shown.connected)
        self.assertEqual(shown.title, "Using Community Engine")
        self.assertEqual(shown.message, SEPARATE_DATABASES_NOTE)
        states = action_states(DEFAULT_SELECTION, COMMUNITY_READY, COMMUNITY_CAPABILITIES)
        self.assertEqual(set(states), set(ACTIONS))
        self.assertTrue(all(state.enabled for state in states.values()))

    def test_missing_core_does_not_affect_community(self):
        core = ExternalEngineAdapter("core", None).connect()
        rows = engine_rows(DEFAULT_SELECTION, [core, COMMUNITY_READY])
        self.assertEqual([row.engine_id for row in rows], ["community", "core"], "Community is listed first")
        self.assertTrue(rows[0].active)
        self.assertEqual(rows[1].state_text, "Not installed")
        self.assertFalse(rows[1].selectable)
        self.assertIn("works fully without it", rows[1].detail)
        self.assertTrue(banner(DEFAULT_SELECTION, COMMUNITY_READY).connected)

    def test_safe_disconnected_is_never_shown_as_connected(self):
        shown = banner(DISCONNECTED, None)
        self.assertFalse(shown.connected)
        self.assertEqual(shown.tone, "warning")
        self.assertIn("stopped at verify", shown.message)
        states = action_states(DISCONNECTED, None, COMMUNITY_CAPABILITIES)
        self.assertFalse(any(state.enabled for state in states.values()))
        rows = engine_rows(DISCONNECTED, [COMMUNITY_READY])
        self.assertFalse(rows[0].active)
        self.assertTrue(rows[0].selectable, "the user can recover by choosing Community again")

    def test_an_unavailable_active_engine_disables_everything_and_names_no_fallback(self):
        selection = EngineSelection(SwitchPhase.ACTIVE, "core", 2)
        down = ExternalEngineAdapter("core", SyntheticTransport(running=False)).connect()
        shown = banner(selection, down)
        self.assertFalse(shown.connected)
        self.assertIn("does not switch to another engine", shown.message)
        self.assertFalse(any(state.enabled for state in action_states(selection, down, {}).values()))

    def test_capabilities_drive_actions_for_an_external_engine(self):
        selection = EngineSelection(SwitchPhase.ACTIVE, "core", 2)
        adapter = ExternalEngineAdapter("core", SyntheticTransport(),
                                        verified={Capability.MEMORY_SEARCH: Support.SUPPORTED,
                                                  Capability.MEMORY_GET: Support.LIMITED})
        status = adapter.connect()
        support = {capability: adapter.support(capability) for capability in Capability}
        states = action_states(selection, status, support)
        self.assertTrue(states["search"].enabled)
        self.assertTrue(states["open"].enabled)
        self.assertIn("Limited", states["open"].note)
        self.assertFalse(states["browse"].enabled)
        self.assertIn("Not yet verified", states["browse"].note)
        for action in ("create", "edit", "retract", "review", "backup", "restore"):
            self.assertFalse(states[action].enabled, action)
            self.assertIn("does not offer", states[action].note)

    def test_only_saved_is_described_as_stored(self):
        for status in WriteStatus:
            message = outcome_message(WriteOutcome("core", status))
            self.assertEqual(message.stored, status is WriteStatus.SAVED, status)
            if status is not WriteStatus.SAVED:
                self.assertNotIn("saved", message.title.lower())
        pending = outcome_message(WriteOutcome("core", WriteStatus.PENDING_REVIEW))
        self.assertIn("Nothing is stored until you approve", pending.message)


if __name__ == "__main__":
    unittest.main()
