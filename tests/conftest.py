# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Shared pytest settings: every test runs under a time limit (see tests/time_limit.py)."""

pytest_plugins = ("tests.time_limit",)
