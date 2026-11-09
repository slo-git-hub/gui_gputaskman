"""Build the Windows installer (Inno Setup 6) from the portable ZIP made by build_portable.py."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_portable import MACHINES, ROOT, validate_version  # noqa: E402

SCRIPT = ROOT / "installer" / "gtm-gui.iss"


def find_iscc() -> Path:
    """ISCC.exe from PATH, or the usual machine-wide or per-user (winget --scope user) install folders."""
    found = shutil.which("ISCC") or shutil.which("iscc")
    if found:
        return Path(found)
    candidates = [Path(os.environ[var]) / "Inno Setup 6" / "ISCC.exe"
                  for var in ("ProgramFiles(x86)", "ProgramFiles") if os.environ.get(var)]
    if os.environ.get("LOCALAPPDATA"):
        candidates.append(Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Inno Setup 6" / "ISCC.exe")
    for path in candidates:
        if path.is_file():
            return path
    raise FileNotFoundError("Inno Setup 6 (ISCC.exe) was not found. Install it with: "
                            "winget install --id JRSoftware.InnoSetup --exact")


def iscc_args(iscc: Path, version: str, arch: str, source: Path, output: Path) -> list[str]:
    return [str(iscc), "/Q", f"/DAppVersion={version}", f"/DArch={arch}", f"/DSourceDir={source}",
            f"/DOutputDir={output}", f"/DRoot={ROOT}", str(SCRIPT)]


def build(arch: str, output: Path, archive: Path | None = None) -> Path:
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    validate_version(version)
    name = f"gputaskman-{version}-windows-{arch}"
    archive = archive or ROOT / "dist" / f"{name}.zip"
    if not archive.is_file():
        raise FileNotFoundError(f"{archive} not found; run tools/build_portable.py --arch {arch} first")
    iscc = find_iscc()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="gputaskman-installer-") as temporary:
        with zipfile.ZipFile(archive) as zipped:
            zipped.extractall(temporary)
        source = Path(temporary) / name
        for exe in ("gtm-gui.exe", "gputaskman.exe"):
            if not (source / exe).is_file():
                raise ValueError(f"{exe} is missing from {archive}")
        subprocess.run(iscc_args(iscc, version, arch, source, output), check=True)
    return output / f"GPUTaskManager-{version}-Setup-{arch}.exe"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arch", choices=MACHINES, required=True)
    parser.add_argument("--zip", type=Path, help="portable ZIP (default: dist/gputaskman-VERSION-windows-ARCH.zip)")
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    print(build(args.arch, args.output.resolve(), args.zip))


if __name__ == "__main__":
    main()
