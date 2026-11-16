# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Shared pytest settings: every test runs under a time limit (see tests/time_limit.py), and the app's text
language is English unless a test chooses Korean itself (the developer PC runs Korean Windows; the CI runner
English), so text checks don't depend on the PC (v0.4.4)."""

import os

os.environ.setdefault("BIO_CE_UI_LANGUAGE", "en")

pytest_plugins = ("tests.time_limit", "tests.bundles")
