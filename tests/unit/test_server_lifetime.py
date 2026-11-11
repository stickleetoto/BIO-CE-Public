# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Idle-limit parsing, and an exit never interrupting a request in progress."""

from __future__ import annotations

import threading
import time
import unittest

from bio_ce.server_lifetime import (
    DEFAULT_IDLE_SECONDS,
    DEFAULT_RELEASE_SECONDS,
    IDLE_ENVIRONMENT_VARIABLE,
    RELEASE_ENVIRONMENT_VARIABLE,
    ServerLifetime,
    idle_seconds_from,
    release_seconds_from,
)


class IdleLimitTests(unittest.TestCase):
    def test_values(self):
        for raw, value in (("", None), ("0", 0.0), ("90", 90.0), ("2.5", 2.5), ("-1", None), ("soon", None)):
            with self.subTest(raw=raw):  # None: invalid or empty, so the default applies
                self.assertEqual(idle_seconds_from({IDLE_ENVIRONMENT_VARIABLE: raw}),
                                 DEFAULT_IDLE_SECONDS if value is None else value)
                self.assertEqual(release_seconds_from({RELEASE_ENVIRONMENT_VARIABLE: raw}),
                                 DEFAULT_RELEASE_SECONDS if value is None else value)
        # Codex does not restart a server that ended, so an idle server is never ended by default (0).
        self.assertEqual(idle_seconds_from({}), 0.0)
        self.assertEqual(release_seconds_from({}), 60.0)


class ExitTimingTests(unittest.TestCase):
    def test_exit_waits_for_the_request_in_progress_and_happens_once(self):
        ended: list[tuple[str, float]] = []
        lifetime = ServerLifetime(lambda reason: ended.append((reason, time.monotonic())),
                                  idle_seconds=0.3, parent_pid=None)
        request_done = threading.Event()
        finished_at: list[float] = []

        def long_request() -> None:
            with lifetime.activity():
                time.sleep(1.0)  # longer than the idle limit
                finished_at.append(time.monotonic())
            request_done.set()

        worker = threading.Thread(target=long_request)
        worker.start()
        time.sleep(0.05)
        lifetime.start()
        worker.join(5)
        self.assertTrue(request_done.is_set())
        deadline = time.monotonic() + 5
        while not ended and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual(len(ended), 1)
        self.assertIn("no request", ended[0][0])
        self.assertGreaterEqual(ended[0][1], finished_at[0], "the server ended during a request")
        time.sleep(0.8)
        self.assertEqual(len(ended), 1, "the exit callback ran twice")

    def test_release_happens_once_per_idle_period_and_never_during_a_request(self):
        released: list[float] = []
        lifetime = ServerLifetime(lambda _reason: None, idle_seconds=0, parent_pid=None, release_seconds=0.3,
                                  on_release=lambda: released.append(time.monotonic()))
        finished: list[float] = []

        def long_request() -> None:
            with lifetime.activity():
                time.sleep(0.8)
                finished.append(time.monotonic())

        worker = threading.Thread(target=long_request)
        worker.start()
        time.sleep(0.05)
        lifetime.start()
        worker.join(5)
        time.sleep(1.0)
        self.assertEqual(len(released), 1, "released once for one idle period")
        self.assertGreaterEqual(released[0], finished[0], "released during a request")
        with lifetime.activity():  # a new request starts a new idle period
            pass
        time.sleep(1.0)
        self.assertEqual(len(released), 2)

    def test_activity_resets_the_idle_timer(self):
        now = [100.0]
        lifetime = ServerLifetime(lambda _reason: None, idle_seconds=10, parent_pid=None, clock=lambda: now[0])
        now[0] = 108.0
        self.assertEqual(lifetime.idle_for(), 8.0)
        with lifetime.activity():
            pass
        self.assertEqual(lifetime.idle_for(), 0.0)


if __name__ == "__main__":
    unittest.main()
