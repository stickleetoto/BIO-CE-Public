# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import tkinter as tk
import unittest
from unittest.mock import patch

from tests import tk_support


class NewTkRootTests(unittest.TestCase):
    def test_retries_only_tcl_library_load_failures(self):
        sentinel = object()
        library_error = tk.TclError('couldn\'t read file "C:/Python/tcl/tcl8.6/auto.tcl": no such file or directory')
        with patch.object(tk_support.tk, "Tk", side_effect=[library_error, sentinel]) as create, \
                patch.object(tk_support.time, "sleep"):
            self.assertIs(tk_support.new_tk_root(), sentinel)
        self.assertEqual(create.call_count, 2)

    def test_other_tk_errors_are_not_hidden(self):
        with patch.object(tk_support.tk, "Tk", side_effect=tk.TclError("no display name and no $DISPLAY")) as create:
            with self.assertRaises(tk.TclError):
                tk_support.new_tk_root()
        self.assertEqual(create.call_count, 1)

    def test_gives_up_after_the_last_attempt(self):
        error = tk.TclError("Can't find a usable init.tcl in the following directories")
        with patch.object(tk_support.tk, "Tk", side_effect=error) as create, patch.object(tk_support.time, "sleep"):
            with self.assertRaises(tk.TclError):
                tk_support.new_tk_root(attempts=3)
        self.assertEqual(create.call_count, 3)


if __name__ == "__main__":
    unittest.main()
