# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Shared pytest settings.

- First of all, the test sandbox (tests/sandbox.py): the user's folders point into a temporary folder and a guard
  stops the run before a test touches a real user location, also when pytest is run directly (owner, 2026-11-17).
- Every test runs under a time limit (tests/time_limit.py).
- The app's text language is English unless a test chooses Korean itself (the developer PC runs Korean Windows;
  the CI runner English), so text checks don't depend on the PC (v0.4.4).
"""

from tests import sandbox

sandbox.install()  # before anything else, and before any BIO CE module is imported

import os  # noqa: E402

import pytest  # noqa: E402

os.environ.setdefault("BIO_CE_UI_LANGUAGE", "en")

pytest_plugins = ("tests.time_limit", "tests.bundles", "tests.offscreen")


@pytest.fixture(scope="session", autouse=True)
def _sandbox_is_in_place():
    sandbox.verify()  # stops the run if BIO CE's data folder would resolve to a real one
    yield


def pytest_unconfigure(config) -> None:
    sandbox.remove()
