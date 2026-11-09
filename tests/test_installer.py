from __future__ import annotations

import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from tools import build_installer


class InstallerTests(unittest.TestCase):
    def test_script_matches_autostart_value(self):
        from gputaskman import autostart
        script = build_installer.SCRIPT.read_text(encoding="utf-8")
        self.assertIn(f'#define AppName "{autostart.VALUE}"', script)
        self.assertIn(autostart.RUN_KEY, script)
        self.assertIn("uninsdeletevalue", script)
        self.assertIn("PrivilegesRequired=lowest", script)

    def test_iscc_found_in_user_install(self):
        with tempfile.TemporaryDirectory() as home:
            iscc = Path(home) / "Programs" / "Inno Setup 6" / "ISCC.exe"
            iscc.parent.mkdir(parents=True)
            iscc.write_bytes(b"")
            env = {"LOCALAPPDATA": home}
            with patch("shutil.which", return_value=None), patch.dict(os.environ, env, clear=True):
                self.assertEqual(build_installer.find_iscc(), iscc)

    def test_missing_iscc_says_how_to_install(self):
        with patch("shutil.which", return_value=None), patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(FileNotFoundError, "JRSoftware.InnoSetup"):
                build_installer.find_iscc()

    def test_build_passes_version_and_extracted_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "portable.zip"
            version = build_installer.tomllib.loads(
                (build_installer.ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
            name = f"gputaskman-{version}-windows-x64"
            with zipfile.ZipFile(archive, "w") as zipped:
                for exe in ("gtm-gui.exe", "gputaskman.exe", "LICENSE"):
                    zipped.writestr(f"{name}/{exe}", "")
            calls = []
            with patch.object(build_installer, "find_iscc", return_value=Path("ISCC.exe")), \
                    patch("subprocess.run", side_effect=lambda args, check: calls.append(args)):
                out = build_installer.build("x64", Path(tmp) / "out", archive)
            self.assertEqual(out.name, f"GPUTaskManager-{version}-Setup-x64.exe")
            args = calls[0]
            self.assertIn(f"/DAppVersion={version}", args)
            self.assertTrue(any(a.startswith("/DSourceDir=") and a.endswith(name) for a in args))
            self.assertEqual(args[-1], str(build_installer.SCRIPT))

    def test_zip_without_gui_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "portable.zip"
            version = build_installer.tomllib.loads(
                (build_installer.ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr(f"gputaskman-{version}-windows-x64/gputaskman.exe", "")
            with patch.object(build_installer, "find_iscc", return_value=Path("ISCC.exe")):
                with self.assertRaisesRegex(ValueError, "gtm-gui.exe"):
                    build_installer.build("x64", Path(tmp) / "out", archive)


if __name__ == "__main__":
    unittest.main()
