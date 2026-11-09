from __future__ import annotations

import sys
import unittest
from unittest.mock import patch

from gputaskman import autostart


class AutostartTests(unittest.TestCase):
    def setUp(self):
        self.store: dict[str, str] = {}
        for name, fn in (("_read", lambda: self.store.get("v")), ("_write", lambda v: self.store.__setitem__("v", v)),
                         ("_delete", lambda: self.store.pop("v", None))):
            p = patch.object(autostart, name, fn)
            p.start()
            self.addCleanup(p.stop)

    def test_toggle_on_windows(self):
        with patch.object(autostart, "supported", return_value=True):
            self.assertFalse(autostart.is_enabled())
            autostart.set_enabled(True)
            self.assertTrue(autostart.is_enabled())
            self.assertTrue(self.store["v"].endswith("--tray"))
            autostart.set_enabled(False)
            self.assertFalse(autostart.is_enabled())
            autostart.set_enabled(False)  # already off: no error

    def test_frozen_command_runs_the_exe_in_the_tray(self):
        with patch.object(sys, "frozen", True, create=True), \
                patch.object(sys, "executable", r"C:\Apps\GPU Task Manager\gtm-gui.exe"):
            self.assertEqual(autostart.command(), r'"C:\Apps\GPU Task Manager\gtm-gui.exe" --tray')

    def test_source_command_uses_the_module(self):
        self.assertIn("-m gputaskman.gui --tray", autostart.command())

    def test_other_platforms(self):
        with patch.object(autostart, "supported", return_value=False):
            self.assertFalse(autostart.is_enabled())
            with self.assertRaises(OSError):
                autostart.set_enabled(True)


if __name__ == "__main__":
    unittest.main()
