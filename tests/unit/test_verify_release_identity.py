# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""The payload leak scan looks for the build machine's own identity, not a shared CI account name."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packaging"))
import verify_release  # noqa: E402


class IdentityPatternTests(unittest.TestCase):
    def patterns(self, user: str, profile: str) -> dict:
        with tempfile.TemporaryDirectory(prefix="bio-ce-identity-") as not_a_repo, \
                mock.patch.object(verify_release.getpass, "getuser", return_value=user), \
                mock.patch.dict(os.environ, {"USERPROFILE": profile}):
            return verify_release.identity_patterns(Path(not_a_repo))

    def test_a_personal_profile_is_scanned(self):
        patterns = self.patterns("alice", r"C:\Users\alice")
        self.assertIn("user name", patterns)
        self.assertIn("profile path", patterns)

    def test_a_hosted_runner_profile_is_not_a_leak(self):
        # Third-party wheels built on hosted runners carry C:\Users\runneradmin, so on a runner that
        # path is shared, not the build machine's own identity.
        patterns = self.patterns("runneradmin", r"C:\Users\runneradmin")
        self.assertNotIn("user name", patterns)
        self.assertNotIn("profile path", patterns)


if __name__ == "__main__":
    unittest.main()
