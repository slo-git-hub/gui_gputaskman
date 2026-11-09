import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, copy_metadata

root = Path(SPECPATH).parent
analysis = Analysis(
    [str(root / "tools" / "portable_entry.py")],
    pathex=[str(root / "src")],
    datas=collect_data_files("textual") + copy_metadata("gputaskman", recursive=True),
)

# These belong to the operating system or the installed NVIDIA driver, not the portable app.
driver_libs = ("nvml.dll", "nvcuda.dll", "atiadlxx.dll", "amd_smi.dll", "libamd_smi.so", "dxgi.dll", "pdh.dll", "libnvidia-ml.so", "libcuda.so", "libdxcore.so")


def is_driver_lib(name):
    name = name.lower()
    return any(name == lib or name.startswith(lib + ".") for lib in driver_libs)


analysis.binaries = [entry for entry in analysis.binaries if not is_driver_lib(Path(entry[0]).name)]

pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="gputaskman",
    console=True,
)
parts = [exe, analysis.binaries, analysis.datas]

# Windows: the desktop GUI and tray icon (gtm-gui.exe) ship beside the console app and share _internal.
if sys.platform == "win32":
    gui = Analysis(
        [str(root / "tools" / "gui_entry.py")],
        pathex=[str(root / "src")],
        datas=collect_data_files("textual") + copy_metadata("gputaskman", recursive=True)
        + copy_metadata("PySide6-Essentials", recursive=True),
    )
    gui.binaries = [entry for entry in gui.binaries if not is_driver_lib(Path(entry[0]).name)]
    gui_exe = EXE(
        PYZ(gui.pure),
        gui.scripts,
        [],
        exclude_binaries=True,
        name="gtm-gui",
        console=False,
        icon=str(root / "tools" / "gtm-gui.ico"),
    )
    parts += [gui_exe, gui.binaries, gui.datas]

bundle = COLLECT(*parts, name="gputaskman")
