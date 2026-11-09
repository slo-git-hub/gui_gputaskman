from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication
    from gputaskman.gui import COLUMNS, NA, MainWindow, tray_pixmap
except ImportError:  # the optional `gui` extra is not installed
    QApplication = None

from gputaskman.collector import ProcRow, Snapshot
from gputaskman.llm import LlmView, ServerInfo
from gputaskman.pdh import ProcGpu
from gputaskman.procinfo import ProcDetail

GiB = 1 << 30


def snapshot() -> Snapshot:
    llm = ProcGpu(dedicated=8 * GiB, shared=GiB, committed=9 * GiB)
    llm.engines["compute"] = 42.0
    return Snapshot(
        taken=1, adapter=None, adapters=[], nv=None, driver="", cuda="",
        vram_total=16 * GiB, vram_used=10 * GiB, shared_used=GiB,
        procs=[
            ProcRow(10, "llama-server.exe", "LLM", llm,
                    ProcDetail(10, "llama-server.exe", runtimes=["CUDA", "ggml"]),
                    LlmView(server=ServerInfo("llama-server", "http://127.0.0.1:8080"))),
            ProcRow(20, "dwm.exe", "compositor", ProcGpu(dedicated=2 * GiB, committed=3 * GiB), ProcDetail(20, "dwm.exe")),
            ProcRow(30, "protected.exe", "app", ProcGpu(available=set()), ProcDetail(30, "protected.exe", access_denied=True)),
        ],
    )


@unittest.skipIf(QApplication is None, "GUI extra (PySide6) not installed")
class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MainWindow(start=False)
        self.window.show()
        self.window.all_btn.setChecked(True)
        self.window.apply(snapshot())

    def tearDown(self):
        self.window.quit()

    def cell(self, row: int, column: str) -> str:
        return self.window.table.item(row, COLUMNS.index(column)).text()

    def names(self) -> list[str]:
        return [self.cell(i, "Process") for i in range(self.window.table.rowCount())]

    def test_rows_sorted_by_vram_and_llm_autoselected(self):
        self.assertEqual(self.names()[:2], ["llama-server.exe", "dwm.exe"])
        self.assertEqual(self.window.selected_key, "10")
        self.assertIn("llama-server", self.window.inspector.toPlainText())

    def test_unknown_is_not_zero(self):
        row = self.names().index("protected.exe")
        self.assertEqual(self.cell(row, "Spill"), NA)
        self.assertEqual(self.cell(row, "GPU"), NA)
        self.assertEqual(self.window.cards["Temperature"].value.text(), NA)  # no device telemetry
        self.assertEqual(self.window.cards["GPU load"].value.text(), NA)

    def test_device_summary(self):
        self.assertEqual(self.window.cards["VRAM"].value.text(), "10.00 GB")
        self.assertIn("16.00 GB", self.window.cards["VRAM"].sub.text())
        self.assertIn(NA, self.window.vram_text.text())  # one row has no measured VRAM, so no total

    def test_top_filter_and_search(self):
        self.window.all_btn.setChecked(False)
        self.assertNotIn("protected.exe", self.names())  # no VRAM, no engine use: hidden, as in the TUI
        self.window.search.setText("dwm")
        self.assertEqual(self.names(), ["dwm.exe"])

    def test_tray_menu_lists_gpu_processes(self):
        self.window.build_tray_menu()
        texts = [a.text() for a in self.window.tray_menu.actions()]
        self.assertTrue(any(t.startswith("VRAM 10.00 GB / 16.00 GB") for t in texts))
        llm = next(t for t in texts if t.startswith("llama-server.exe"))
        self.assertIn("8.00 GB", llm)
        self.assertIn("42%", llm)
        self.assertFalse(any(t.startswith("protected.exe") for t in texts))  # nothing measured, nothing listed
        self.assertIn("Quit", texts)

    def test_tray_menu_opens_process(self):
        self.window.hide()
        self.window.build_tray_menu()
        next(a for a in self.window.tray_menu.actions() if a.text().startswith("dwm.exe")).trigger()
        self.assertTrue(self.window.isVisible())
        self.assertEqual(self.window.selected_key, "20")
        self.assertIn("dwm.exe", self.window.inspector.toPlainText())

    def test_tray_icon_renders(self):
        for fraction in (None, 0.0, 0.5, 0.95):
            self.assertFalse(tray_pixmap(fraction).isNull())


if __name__ == "__main__":
    unittest.main()
