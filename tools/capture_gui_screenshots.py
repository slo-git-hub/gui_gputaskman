"""Render the README screenshots of gtm-gui (docs/screenshots/gui-*.png) from illustrative sample data.

No GPU is needed. Run from the repo root:
  QT_QPA_PLATFORM=offscreen QT_SCALE_FACTOR=2 uv run --extra gui python tools/capture_gui_screenshots.py docs/screenshots
"""
import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPoint
from gputaskman.gui import MainWindow
from gputaskman.telemetry import DeviceTelemetry
from gputaskman.dxgi import Adapter
from gputaskman.collector import ProcRow, Snapshot
from gputaskman.llm import LlmView, ServerInfo, Segment
from gputaskman.pdh import ProcGpu
from gputaskman.procinfo import ProcDetail
GiB = 1 << 30; MiB = 1 << 20
out = sys.argv[1]
app = QApplication([]); app.setStyle("Fusion")
w = MainWindow(start=False); w.resize(1280, 780); w.show()

def proc(pid, name, kind, ded, eng=None, rt=(), shared=0, llm=None, cmd=()):
    g = ProcGpu(dedicated=ded, shared=shared, committed=ded + shared)
    if eng: g.engines.update(eng)
    return ProcRow(pid, name, kind, g, ProcDetail(pid, name, runtimes=list(rt), cmdline=list(cmd)), llm)

llm = LlmView(server=ServerInfo("llama-server", "http://127.0.0.1:8080", n_ctx=16384, slots_total=1, slots_busy=1, gen_tok_s=86.4),
              segments=[Segment("weights", int(8.9 * GiB), "weights"), Segment("KV cache", int(2.0 * GiB), "kv", True),
                        Segment("compute", int(0.6 * GiB), "compute", True), Segment("runtime", int(0.3 * GiB), "runtime")],
              log_source="llama-server.log")
s = Snapshot(taken=1, adapter=Adapter(1, "NVIDIA GeForce RTX 3090", 0x10DE, 24 * GiB, 0, False), adapters=[],
             nv=DeviceTelemetry(0, util_gpu=71, temp=64, power_w=287, power_limit_w=350, sm_clock=1860, mem_clock=9751,
                                driver_model="WDDM"),
             driver="610.62", cuda="13.1", vram_total=24 * GiB, vram_used=int(16.7 * GiB), shared_used=int(0.4 * GiB),
             procs=[
                 proc(8812, "llama-server.exe", "LLM", int(11.8 * GiB), {"compute": 68}, ["CUDA", "ggml"], llm=llm,
                      cmd=["llama-server.exe", "-m", "Qwen3-14B-Q4_K_M.gguf", "-ngl", "99", "-c", "16384"]),
                 proc(3120, "ComfyUI (python.exe)", "diffusion", int(2.6 * GiB), {"compute": 3}, ["CUDA", "PyTorch"]),
                 proc(1456, "dwm.exe", "compositor", int(0.9 * GiB), {"3d": 2}, ["D3D11"]),
                 proc(5524, "msedge.exe", "browser", int(0.7 * GiB), {"3d": 4, "video": 1}, ["D3D11"]),
                 proc(9930, "obs64.exe", "video", int(0.42 * GiB), {"encode": 9, "3d": 2}, ["D3D11"]),
                 proc(6610, "Discord.exe", "app", int(0.18 * GiB), {"3d": 1}, ["D3D11"]),
                 proc(7044, "explorer.exe", "app", int(0.09 * GiB), None, ["D3D11"]),
             ])
s.backend = "wddm"
w.gpu_box.setItemText(0, "NVIDIA GeForce RTX 3090")
w.apply(s); app.processEvents()
w.grab().save(f"{out}/gui-window.png")
from gputaskman import autostart
autostart.supported = lambda: True; autostart.is_enabled = lambda: True  # show the Windows-only item
w.build_tray_menu(); m = w.tray_menu; m.popup(QPoint(0, 0)); app.processEvents()
m.grab().save(f"{out}/gui-tray-menu.png")
print("ok")
