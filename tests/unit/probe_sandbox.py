# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Run only by tests/unit/test_test_sandbox.py, in a separate pytest started directly (not collected on its own,
the name does not start with test_). It only computes paths and writes them to BIO_CE_PROBE_OUT; it opens no
BIO CE data."""

import json
import os
from pathlib import Path


def test_where_bio_ce_data_would_be():
    from bio_ce.desktop import AppDataPaths

    found = {"bio_ce_root": str(AppDataPaths.from_local_app_data().root),
             "localappdata": os.environ.get("LOCALAPPDATA"), "home": str(Path.home())}
    with open(os.environ["BIO_CE_PROBE_OUT"], "w", encoding="utf-8") as stream:
        json.dump(found, stream)
