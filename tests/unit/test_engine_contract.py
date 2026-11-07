# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Engine contract: negotiation, capability gating, typed outcomes, and the external engine client."""

from __future__ import annotations

import unittest

from bio_ce.engine.contract import (
    Capability,
    EngineBinding,
    EngineDescriptor,
    EngineProtocolError,
    EngineState,
    EngineUnavailable,
    MemoryCandidate,
    StaleEngineBinding,
    Support,
    UnsupportedCapability,
    WriteOutcome,
    WriteStatus,
    effective_capabilities,
    negotiate,
    weaker,
)
from bio_ce.engine.external import CLIENT_NEVER_ROUTES, ExternalEngineAdapter, parse_descriptor
from tests.engine_fixtures import SyntheticTransport


CANDIDATE = MemoryCandidate("Prefers tabs", "The user prefers tabs for indentation in Python.", "preference",
                            "high", "user_stated")


def descriptor(low: int, high: int) -> EngineDescriptor:
    return EngineDescriptor("synthetic", "Synthetic", "0", low, high, {}, "db")


def allow_all(_binding: EngineBinding) -> None:
    return None


class NegotiationTests(unittest.TestCase):
    def test_compatible_and_incompatible_ranges(self):
        self.assertEqual(negotiate(descriptor(1, 3)).protocol_version, 1)
        refused = negotiate(descriptor(2, 3))
        self.assertFalse(refused.compatible)
        self.assertIsNone(refused.protocol_version)
        self.assertIn("2-3", refused.reason)

    def test_descriptor_validation_fails_closed(self):
        for bad in (dict(engine_id="Core!"), dict(protocol_min=0), dict(protocol_min=2, protocol_max=1),
                    dict(protocol_min=True)):
            values = dict(engine_id="core", display_name="x", engine_version="0", protocol_min=1, protocol_max=1,
                          capabilities={}, database_label="db")
            values.update(bad)
            with self.subTest(bad=bad), self.assertRaises(EngineProtocolError):
                EngineDescriptor(**values)

    def test_support_is_the_weaker_of_claim_and_verification(self):
        self.assertEqual(weaker(Support.SUPPORTED, Support.LIMITED), Support.LIMITED)
        self.assertEqual(weaker(Support.SUPPORTED, Support.UNVERIFIED), Support.UNVERIFIED)
        self.assertEqual(weaker(Support.UNSUPPORTED, Support.SUPPORTED), Support.UNSUPPORTED)
        effective = effective_capabilities({Capability.MEMORY_SEARCH: Support.SUPPORTED}, {})
        self.assertEqual(effective[Capability.MEMORY_SEARCH], Support.UNVERIFIED)
        self.assertEqual(effective[Capability.MEMORY_GET], Support.UNSUPPORTED)
        self.assertFalse(Support.UNVERIFIED.usable)
        self.assertTrue(Support.LIMITED.usable)

    def test_only_saved_counts_as_persisted(self):
        for status in WriteStatus:
            self.assertEqual(WriteOutcome("x", status).persisted, status is WriteStatus.SAVED)

    def test_unknown_capability_names_are_ignored_and_bad_levels_refused(self):
        parsed = parse_descriptor({"engine_id": "core", "display_name": "x", "engine_version": "1",
                                   "protocol_min": 1, "protocol_max": 1,
                                   "capabilities": {"memory_search": "supported", "telepathy": "supported"}})
        self.assertEqual(set(parsed.capabilities), {Capability.MEMORY_SEARCH})
        with self.assertRaises(EngineProtocolError):
            parse_descriptor({"engine_id": "core", "display_name": "x", "engine_version": "1", "protocol_min": 1,
                              "protocol_max": 1, "capabilities": {"memory_search": "definitely"}})


class ExternalEngineTests(unittest.TestCase):
    def test_not_installed_sends_nothing(self):
        adapter = ExternalEngineAdapter("core", None)
        status = adapter.connect()
        self.assertEqual(status.state, EngineState.NOT_INSTALLED)
        self.assertTrue(all(not adapter.support(capability).usable for capability in Capability))
        with self.assertRaises(UnsupportedCapability):
            adapter.search("anything")

    def test_not_running_and_incompatible_are_reported_not_raised(self):
        self.assertEqual(ExternalEngineAdapter("core", SyntheticTransport(running=False)).connect().state,
                         EngineState.NOT_RUNNING)
        self.assertEqual(ExternalEngineAdapter("core", SyntheticTransport(protocol=(2, 2))).connect().state,
                         EngineState.INCOMPATIBLE)
        self.assertEqual(ExternalEngineAdapter("core", SyntheticTransport(engine_id="other")).connect().state,
                         EngineState.INCOMPATIBLE)

    def test_an_unverified_engine_offers_nothing_even_if_it_claims_everything(self):
        transport = SyntheticTransport()
        adapter = ExternalEngineAdapter("core", transport)  # default: this client verified nothing
        self.assertTrue(adapter.connect().ready)
        for capability in Capability:
            self.assertFalse(adapter.support(capability).usable, capability)
        with self.assertRaises(UnsupportedCapability):
            adapter.search("synthetic")
        self.assertEqual([op for op, _ in transport.requests], ["engine.describe"])

    def test_verified_reads_return_engine_scoped_views(self):
        transport = SyntheticTransport()
        verified = {capability: Support.SUPPORTED for capability in Capability}
        adapter = ExternalEngineAdapter("core", transport, verified=verified)
        adapter.connect()
        hits = adapter.search("synthetic content")
        self.assertEqual(len(hits), 3)
        self.assertTrue(all(hit.engine_id == "core" for hit in hits))
        self.assertEqual(adapter.get("syn-1").title, "Synthetic engine note 1")
        self.assertEqual(len(adapter.list()), 3)

    def test_user_edits_review_and_backup_are_never_routed_to_an_external_engine(self):
        transport = SyntheticTransport()
        adapter = ExternalEngineAdapter("core", transport,
                                        verified={capability: Support.SUPPORTED for capability in Capability})
        adapter.connect()
        for capability in CLIENT_NEVER_ROUTES:
            self.assertEqual(adapter.support(capability), Support.UNSUPPORTED)
        before = len(transport.requests)
        with self.assertRaises(UnsupportedCapability):
            adapter.create(title="t", content="c", source_ref="user-input")
        with self.assertRaises(UnsupportedCapability):
            adapter.revise("syn-1", expected_revision_id="syn-rev-1", title="t", content="c", source_ref="u")
        with self.assertRaises(UnsupportedCapability):
            adapter.retract("syn-1", expected_revision_id="syn-rev-1")
        self.assertEqual(len(transport.requests), before)

    def test_a_pending_proposal_is_not_reported_as_saved(self):
        verified = {capability: Support.SUPPORTED for capability in Capability}
        for answer, expected in (("pending_review", WriteStatus.PENDING_REVIEW), ("rejected", WriteStatus.REJECTED),
                                 ("saved", WriteStatus.SAVED)):
            with self.subTest(answer=answer):
                adapter = ExternalEngineAdapter("core", SyntheticTransport(proposal_status=answer), verified=verified)
                adapter.connect()
                session = adapter.open_host_session("conn", "synthetic-token", binding=EngineBinding("core", 1),
                                                    binding_guard=allow_all)
                outcome = session.propose(CANDIDATE, request_id="req-1")
                self.assertEqual(outcome.status, expected)
                self.assertEqual(outcome.persisted, answer == "saved")
                if answer != "saved":
                    self.assertIsNone(outcome.revision_id)

    def test_unknown_proposal_answers_are_protocol_errors(self):
        verified = {capability: Support.SUPPORTED for capability in Capability}
        for answer in ("approved_probably", "", None):
            with self.subTest(answer=answer):
                adapter = ExternalEngineAdapter("core", SyntheticTransport(proposal_status=answer), verified=verified)
                adapter.connect()
                session = adapter.open_host_session("conn", "synthetic-token", binding=EngineBinding("core", 1),
                                                    binding_guard=allow_all)
                with self.assertRaises(EngineProtocolError):
                    session.propose(CANDIDATE, request_id="req-1")

    def test_host_evidence_is_sent_only_as_a_claim(self):
        transport = SyntheticTransport()
        adapter = ExternalEngineAdapter("core", transport,
                                        verified={capability: Support.SUPPORTED for capability in Capability})
        adapter.connect()
        session = adapter.open_host_session("conn", "synthetic-token", binding=EngineBinding("core", 1),
                                            binding_guard=allow_all)
        session.propose(CANDIDATE, request_id="req-7")
        _op, payload = transport.requests[-1]
        self.assertEqual(payload["claimed_evidence"], "user_stated")
        self.assertNotIn("evidence", payload)
        self.assertEqual(payload["request_id"], "req-7")

    def test_bad_credentials_and_stale_bindings_send_nothing_further(self):
        transport = SyntheticTransport()
        adapter = ExternalEngineAdapter("core", transport,
                                        verified={capability: Support.SUPPORTED for capability in Capability})
        adapter.connect()
        with self.assertRaises(EngineUnavailable):
            adapter.open_host_session("conn", "wrong", binding=EngineBinding("core", 1), binding_guard=allow_all)
        current = {"binding": EngineBinding("core", 1)}

        def guard(binding):
            if binding != current["binding"]:
                raise StaleEngineBinding("stale")

        session = adapter.open_host_session("conn", "synthetic-token", binding=EngineBinding("core", 1),
                                            binding_guard=guard)
        current["binding"] = EngineBinding("core", 2)
        before = len(transport.requests)
        with self.assertRaises(StaleEngineBinding):
            session.propose(CANDIDATE, request_id="req-1")
        with self.assertRaises(StaleEngineBinding):
            session.search("synthetic")
        self.assertEqual(len(transport.requests), before)


if __name__ == "__main__":
    unittest.main()
