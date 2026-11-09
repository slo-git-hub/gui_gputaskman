"""Windows desktop GUI (PySide6) over the same Collector the TUI uses, plus a system tray icon.

Run with `gtm-gui` (or `python -m gputaskman.gui`). Needs the optional `gui` extra:
`uv sync --extra gui` or `pip install .[gui]`.

The provenance rules in AGENTS.md apply here exactly as in app.py: unknown is shown as "n/a",
never 0, and inferred VRAM is labelled by `vram_label` and never summed.
"""

from __future__ import annotations

import argparse
import html
import math
import os
import sys
import threading

from PySide6.QtCore import QFileInfo, QObject, QRectF, QSize, Qt, QThread, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QFileIconProvider, QFrame, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMainWindow, QMenu, QPushButton, QSplitter,
                               QSystemTrayIcon, QTableWidget, QTableWidgetItem, QTextBrowser, QVBoxLayout, QWidget)

from . import autostart
from .collector import BACKEND, Collector, ProcRow, Snapshot, enumerate_adapters, ordered_adapters
from .llm import gb
from .report import has_engine_counters, has_spill_counters, has_wddm_counters, inferred_note, vram_label

NA = "n/a"
COLUMNS = ["Process", "PID", "Kind", "VRAM", "GPU", "Spill", "Runtime", "What's inside"]
TRAY_PROCS = 10  # processes listed in the tray menu

# ------------------------------------------------------------------ theme

BG, SURFACE, SURFACE2, BORDER = "#0e1014", "#161920", "#1d212a", "#272c37"
TEXT, MUTED, FAINT, ACCENT = "#e7e9ee", "#8a92a6", "#5b6375", "#8b5cf6"
GOOD, WARN, BAD = "#34d399", "#fbbf24", "#f87171"

# Same categories as the TUI (app.py KIND_STYLE), tuned for a dark background.
KIND_COLOR = {
    "LLM": "#c084fc", "decision": "#e879f9", "decision?": "#e879f9", "embedding": "#f0abfc",
    "speech": "#7dd3fc", "diffusion": "#f472b6", "AI": "#a78bfa", "compute": "#fb923c",
    "3D/game": "#4ade80", "video": "#facc15", "browser": "#60a5fa", "app": "#22d3ee",
    "wsl-vm": "#34d399", "compositor": "#64748b", "kernel": "#64748b", "system": "#64748b", "external": "#64748b",
}
OTHER_COLOR = "#3a4150"

STYLE = f"""
* {{ font-family: "Segoe UI Variable Text", "Segoe UI", "Inter", sans-serif; font-size: 10pt; color: {TEXT}; }}
QMainWindow, #root {{ background: {BG}; }}
QToolTip {{ background: {SURFACE2}; color: {TEXT}; border: 1px solid {BORDER}; padding: 6px; border-radius: 6px; }}
#card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px; }}
#title {{ font-size: 16pt; font-weight: 600; }}
#subtitle, #muted {{ color: {MUTED}; }}
#statLabel {{ color: {MUTED}; font-size: 8pt; font-weight: 600; letter-spacing: 1px; }}
#statValue {{ font-size: 17pt; font-weight: 600; }}
#statSub {{ color: {FAINT}; font-size: 8.5pt; }}
#sectionLabel {{ color: {MUTED}; font-size: 8pt; font-weight: 600; letter-spacing: 1px; }}
#warning {{ color: {WARN}; }}
QPushButton {{ background: {SURFACE2}; border: 1px solid {BORDER}; border-radius: 8px; padding: 6px 14px; }}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:checked {{ background: {ACCENT}; border-color: {ACCENT}; color: white; }}
QComboBox, QLineEdit {{ background: {SURFACE2}; border: 1px solid {BORDER}; border-radius: 8px; padding: 6px 10px; }}
QComboBox:hover, QLineEdit:focus {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {SURFACE2}; border: 1px solid {BORDER}; selection-background-color: {ACCENT}; }}
QTableWidget {{ background: {SURFACE}; border: none; gridline-color: transparent; outline: 0;
               selection-background-color: #2a2340; selection-color: {TEXT}; }}
QTableWidget::item {{ padding: 0 10px; border-bottom: 1px solid {SURFACE2}; }}
QTableWidget::item:hover {{ background: {SURFACE2}; }}
QHeaderView::section {{ background: {SURFACE}; color: {MUTED}; border: none; border-bottom: 1px solid {BORDER};
                        padding: 8px 10px; font-size: 8pt; font-weight: 600; }}
QTextBrowser {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {FAINT}; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ height: 0; background: none; }}
QScrollBar:horizontal {{ height: 0; }}
QSplitter::handle {{ background: transparent; }}
QMenu {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; padding: 6px; }}
QMenu::item {{ padding: 6px 28px 6px 12px; border-radius: 6px; }}
QMenu::item:selected {{ background: {SURFACE2}; }}
QMenu::item:disabled {{ color: {MUTED}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 5px 8px; }}
"""


def _explain(kind: str) -> str:
    try:  # Reuse the TUI's per-kind explanations; app.py needs textual, which is a core dependency.
        from .app import EXPLAIN
        return EXPLAIN.get(kind, "")
    except Exception:
        return ""


def tray_pixmap(fraction: float | None, size: int = 64) -> QPixmap:
    """App/tray icon: a rounded chip whose fill rises with VRAM use (hollow when unknown)."""
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = size / 64
    body = QRectF(10 * s, 10 * s, 44 * s, 44 * s)
    p.setPen(QPen(QColor("#c4b5fd"), 3 * s))
    for i in range(3):  # chip pins
        x = (20 + 12 * i) * s
        p.drawLine(int(x), int(3 * s), int(x), int(10 * s))
        p.drawLine(int(x), int(54 * s), int(x), int(61 * s))
    path = QPainterPath()
    path.addRoundedRect(body, 9 * s, 9 * s)
    p.fillPath(path, QColor("#1e1b2e"))
    if fraction is not None:
        f = min(max(fraction, 0.0), 1.0)
        color = QColor(BAD if f >= 0.9 else WARN if f >= 0.75 else ACCENT)
        p.save()
        p.setClipPath(path)
        p.fillRect(QRectF(body.left(), body.bottom() - body.height() * f, body.width(), body.height() * f), color)
        p.restore()
    p.setPen(QPen(QColor("#c4b5fd"), 3 * s))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)
    p.end()
    return pix


def _dark_title_bar(widget: QWidget) -> None:
    """Windows 10 1809+/11: ask DWM for a dark caption so the frame matches the theme."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        value = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(int(widget.winId()), 20, ctypes.byref(value), ctypes.sizeof(value))
    except Exception:
        pass


# ------------------------------------------------------------------ widgets

class SortItem(QTableWidgetItem):
    """Table cell that sorts by its key (numbers sort numerically), not by its display text."""

    def __init__(self, text: str, key=None) -> None:
        super().__init__(text)
        self.key = key

    def __lt__(self, other: QTableWidgetItem) -> bool:
        a, b = self.key, getattr(other, "key", None)
        if a is None or b is None:  # unknown ranks below every measured value (bottom when sorted descending)
            return a is None and b is not None
        return a < b


def card() -> QFrame:
    frame = QFrame()
    frame.setObjectName("card")
    return frame


def label(text: str = "", name: str = "") -> QLabel:
    lab = QLabel(text)
    if name:
        lab.setObjectName(name)
    return lab


class StatCard(QFrame):
    def __init__(self, title: str) -> None:
        super().__init__()
        self.setObjectName("card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(2)
        lay.addWidget(label(title.upper(), "statLabel"))
        self.value = label(NA, "statValue")
        self.sub = label("", "statSub")
        lay.addWidget(self.value)
        lay.addWidget(self.sub)

    def set(self, value: str, sub: str = "", color: str | None = None) -> None:
        self.value.setText(value)
        self.value.setStyleSheet(f"color: {color};" if color else "")
        self.sub.setText(sub)


class VramBar(QWidget):
    """Rounded stacked bar of measured VRAM by process kind, scaled to the adapter total (like the TUI)."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(14)
        self.setMaximumHeight(14)
        self.parts: list[tuple[float, str]] = []
        self.total = 0.0

    def set_parts(self, parts: list[tuple[float, str]], total: float) -> None:
        self.parts, self.total = parts, total
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(r, r.height() / 2, r.height() / 2)
        p.fillPath(path, QColor(SURFACE2))
        p.setClipPath(path)
        x = r.left()
        for value, color in self.parts:
            w = r.width() * value / self.total if self.total else 0
            if w > 0:
                p.fillRect(QRectF(x, r.top(), w, r.height()), QColor(color))
                x += w
        p.end()


class Sampler(QObject):
    """Runs Collector.sample() off the UI thread, like app.py's poll worker."""

    sampled = Signal(object)
    failed = Signal(str)

    def __init__(self, gpu_index: int, interval: float, host: bool) -> None:
        super().__init__()
        self.gpu_index, self.interval, self.host = gpu_index, interval, host
        self.paused = False
        self._stop = threading.Event()

    def run(self) -> None:
        try:
            collector = Collector(self.gpu_index, scan_budget=Collector.SCAN_BUDGET, host=self.host)
        except Exception as error:  # Degrade with a reason (AGENTS.md rule 9).
            self.failed.emit(f"Could not start GPU collector: {error}")
            return
        try:
            self._stop.wait(0.5)  # engine utilization is a rate; needs two samples
            while not self._stop.is_set():
                if not self.paused:
                    try:
                        self.sampled.emit(collector.sample())
                    except Exception as error:
                        self.failed.emit(f"Sampling failed: {error}")
                self._stop.wait(self.interval)
        finally:
            collector.close()

    def stop(self) -> None:
        self._stop.set()


# ------------------------------------------------------------------ main window

def breakdown(s: Snapshot) -> tuple[list[tuple[str, float]], float]:
    """Measured VRAM per kind, scaled to the adapter total, plus the unattributed rest (as in app.py)."""
    by_kind: dict[str, float] = {}
    for r in s.procs:
        if r.gpu.attributed and "dedicated" in r.gpu.available:
            by_kind[r.kind] = by_kind.get(r.kind, 0) + r.gpu.dedicated
    attributed = sum(by_kind.values())
    scale = min(1.0, s.vram_used / attributed) if attributed and s.vram_used is not None else 1.0
    kinds = sorted(((k, v * scale) for k, v in by_kind.items() if v > 0), key=lambda kv: -kv[1])
    other = max(s.vram_used - attributed * scale, 0) if s.vram_used is not None else 0
    return kinds, other


def gpu_pct(s: Snapshot, r: ProcRow) -> float | None:
    return r.gpu.gpu_pct if has_engine_counters(s, r) else None


class MainWindow(QMainWindow):
    def __init__(self, gpu_index: int = 0, interval: float = 1.0, host: bool = True, start: bool = True) -> None:
        super().__init__()
        self.setWindowTitle("GPU Task Manager")
        self.resize(1280, 800)
        self.setMinimumSize(900, 560)
        self.interval, self.host = interval, host
        self.snap: Snapshot | None = None
        self.selected_key: str | None = None
        self.show_all = False
        self._thread: QThread | None = None
        self._sampler: Sampler | None = None
        self._icons: dict[str, QIcon] = {}
        self._icon_provider = QFileIconProvider()
        self._quitting = False
        self._tray_hint_shown = False
        self.setStyleSheet(STYLE)
        self.setWindowIcon(QIcon(tray_pixmap(0.6)))
        self._build_ui()
        self._build_tray()
        if start:
            self.start_sampler(gpu_index)

    # -------------------------------------------------------------- layout

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(14)

        # Header: GPU name + controls
        head = QHBoxLayout()
        names = QVBoxLayout()
        names.setSpacing(0)
        self.name_label = label("Sampling GPU counters…", "title")
        self.sub_label = label(f"backend {BACKEND}", "subtitle")
        names.addWidget(self.name_label)
        names.addWidget(self.sub_label)
        head.addLayout(names, 1)
        self.gpu_box = QComboBox()
        self.gpu_box.setMinimumWidth(220)
        try:
            adapters = ordered_adapters(enumerate_adapters())
        except Exception:
            adapters = []
        for i, a in enumerate(adapters):
            self.gpu_box.addItem(a.name, i)
        if not adapters:
            self.gpu_box.addItem("Default GPU", 0)
        self.gpu_box.currentIndexChanged.connect(lambda _: self.start_sampler(self.gpu_box.currentData()))
        head.addWidget(self.gpu_box)
        self.pause_btn = QPushButton("Pause")
        self.pause_btn.setCheckable(True)
        self.pause_btn.toggled.connect(self.set_paused)
        head.addWidget(self.pause_btn)
        outer.addLayout(head)

        # Stat cards
        stats = QHBoxLayout()
        stats.setSpacing(12)
        self.cards = {key: StatCard(key) for key in ("GPU load", "VRAM", "Temperature", "Power", "Clock", "Shared RAM")}
        for c in self.cards.values():
            stats.addWidget(c)
        outer.addLayout(stats)

        # VRAM breakdown
        mem = card()
        mem_lay = QVBoxLayout(mem)
        mem_lay.setContentsMargins(16, 12, 16, 12)
        mem_lay.setSpacing(8)
        top = QHBoxLayout()
        top.addWidget(label("VRAM BY WORKLOAD", "sectionLabel"))
        top.addStretch()
        self.vram_text = label("", "muted")
        top.addWidget(self.vram_text)
        mem_lay.addLayout(top)
        self.vram_bar = VramBar()
        mem_lay.addWidget(self.vram_bar)
        self.legend = label("", "muted")
        self.legend.setTextFormat(Qt.TextFormat.RichText)
        mem_lay.addWidget(self.legend)
        self.note_label = label("", "warning")
        self.note_label.setWordWrap(True)
        self.note_label.hide()
        mem_lay.addWidget(self.note_label)
        outer.addWidget(mem)

        # Processes (left) + details (right)
        procs = card()
        procs_lay = QVBoxLayout(procs)
        procs_lay.setContentsMargins(0, 12, 0, 0)
        bar = QHBoxLayout()
        bar.setContentsMargins(16, 0, 16, 4)
        bar.addWidget(label("PROCESSES", "sectionLabel"))
        self.count_label = label("", "muted")
        bar.addWidget(self.count_label)
        bar.addStretch()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter processes")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(220)
        self.search.textChanged.connect(lambda _: self.snap and self.render_table(self.snap))
        bar.addWidget(self.search)
        self.all_btn = QPushButton("All processes")
        self.all_btn.setCheckable(True)
        self.all_btn.toggled.connect(self.set_show_all)
        bar.addWidget(self.all_btn)
        procs_lay.addLayout(bar)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels([c.upper() for c in COLUMNS])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setIconSize(QSize(18, 18))
        self.table.setWordWrap(False)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.table.horizontalHeader().setHighlightSections(False)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(COLUMNS.index("VRAM"), Qt.SortOrder.DescendingOrder)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        for col, width in zip(COLUMNS, (190, 60, 100, 95, 60, 85, 110)):
            self.table.setColumnWidth(COLUMNS.index(col), width)
        self.table.itemSelectionChanged.connect(self._on_select)
        procs_lay.addWidget(self.table)

        details = card()
        det_lay = QVBoxLayout(details)
        det_lay.setContentsMargins(16, 12, 12, 12)
        det_lay.addWidget(label("DETAILS", "sectionLabel"))
        self.inspector = QTextBrowser()
        self.inspector.setHtml(self._placeholder())
        det_lay.addWidget(self.inspector)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setHandleWidth(12)
        split.addWidget(procs)
        split.addWidget(details)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        split.setSizes([800, 420])
        outer.addWidget(split, 1)

        self.status = label("", "muted")
        outer.addWidget(self.status)
        self.setCentralWidget(root)

    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(QIcon(tray_pixmap(None)), self)
        self.tray.setToolTip("GPU Task Manager")
        self.tray_menu = QMenu(self)
        self.tray_menu.setStyleSheet(STYLE)
        self.tray_menu.aboutToShow.connect(self.build_tray_menu)
        self.tray.setContextMenu(self.tray_menu)
        self.tray.activated.connect(self._tray_activated)
        self.build_tray_menu()
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        _dark_title_bar(self)

    # -------------------------------------------------------------- tray

    def build_tray_menu(self) -> None:
        """Rebuilt each time it opens, from the latest snapshot: GPU summary and the top processes."""
        m = self.tray_menu
        m.clear()
        s = self.snap
        if s is None:
            m.addAction("Waiting for the first sample…").setEnabled(False)
        else:
            name = s.adapter.name if s.adapter else (s.nv.name if s.nv else "GPU")
            m.addAction(name).setEnabled(False)
            util = s.nv.util_gpu if s.nv else None
            used = gb(s.vram_used) if s.vram_used is not None else NA
            m.addAction(f"VRAM {used} / {gb(s.vram_total)}\tGPU {NA if util is None else f'{util:.0f}%'}").setEnabled(False)
            m.addSeparator()
            rows = sorted((r for r in s.procs if (r.gpu.shown_vram or 0) >= 1 << 20 or (gpu_pct(s, r) or 0) >= 1),
                          key=lambda r: (-(r.gpu.shown_vram or 0), -(gpu_pct(s, r) or 0)))[:TRAY_PROCS]
            if not rows:
                m.addAction("No processes using the GPU").setEnabled(False)
            for r in rows:
                pct = gpu_pct(s, r)
                gpu = NA if pct is None else f"{pct:.0f}%"
                action = m.addAction(self.process_icon(r), f"{r.name}\t{vram_label(r.gpu)}  ·  {gpu}")
                action.triggered.connect(lambda _=False, key=r.key: self.show_process(key))
        m.addSeparator()
        m.addAction("Open GPU Task Manager", self.bring_to_front)
        if autostart.supported():
            start = m.addAction("Start with Windows")
            start.setCheckable(True)
            try:
                start.setChecked(autostart.is_enabled())
            except OSError:
                start.setEnabled(False)
            start.toggled.connect(self.set_autostart)
        pause = m.addAction("Resume" if self.pause_btn.isChecked() else "Pause")
        pause.triggered.connect(lambda: self.pause_btn.toggle())
        m.addAction("Quit", self.quit)

    def set_autostart(self, enabled: bool) -> None:
        try:
            autostart.set_enabled(enabled)
        except OSError as error:  # Degrade with a reason: say why, never crash the tray.
            self.status.setText(f"Could not change Start with Windows: {error}")
            self.tray.showMessage("GPU Task Manager", f"Could not change Start with Windows: {error}")

    def update_tray(self, s: Snapshot) -> None:
        frac = s.vram_used / s.vram_total if s.vram_total and s.vram_used is not None else None
        self.tray.setIcon(QIcon(tray_pixmap(frac)))
        util = s.nv.util_gpu if s.nv else None
        used = gb(s.vram_used) if s.vram_used is not None else NA
        self.tray.setToolTip(f"GPU Task Manager\nVRAM {used} / {gb(s.vram_total)}\n"
                             f"GPU {NA if util is None else f'{util:.0f}%'}")

    def _tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            if self.isVisible() and not self.isMinimized():
                self.hide()
            else:
                self.bring_to_front()

    def bring_to_front(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def show_process(self, key: str) -> None:
        self.selected_key = key
        self.bring_to_front()
        if self.snap is not None:
            if not any(r.key == key for r in self.visible_rows(self.snap)):
                self.all_btn.setChecked(True)
            self.render_table(self.snap)
            self.render_inspector()

    def quit(self) -> None:
        self._quitting = True
        self.close()

    def closeEvent(self, event) -> None:
        if not self._quitting and self.tray.isVisible():  # Close hides to the tray; Quit is in its menu.
            event.ignore()
            self.hide()
            if not self._tray_hint_shown:
                self._tray_hint_shown = True
                self.tray.showMessage("GPU Task Manager", "Still running in the tray. Right-click the icon to quit.",
                                      QIcon(tray_pixmap(0.6)), 3000)
            return
        self.stop_sampler()
        self.tray.hide()
        super().closeEvent(event)
        QApplication.quit()

    # -------------------------------------------------------------- sampling

    def start_sampler(self, gpu_index: int) -> None:
        self.stop_sampler()
        self._thread = QThread(self)
        self._sampler = Sampler(gpu_index or 0, self.interval, self.host)
        self._sampler.paused = self.pause_btn.isChecked()
        self._sampler.moveToThread(self._thread)
        self._thread.started.connect(self._sampler.run)
        self._sampler.sampled.connect(self.apply)
        self._sampler.failed.connect(self.status.setText)
        self._thread.start()

    def stop_sampler(self) -> None:
        if self._sampler is not None:
            self._sampler.stop()
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(5000)
        self._thread = self._sampler = None

    def set_paused(self, paused: bool) -> None:
        if self._sampler is not None:
            self._sampler.paused = paused
        self.pause_btn.setText("Resume" if paused else "Pause")

    def set_show_all(self, show: bool) -> None:
        self.show_all = show
        if self.snap is not None:
            self.render_table(self.snap)

    # -------------------------------------------------------------- rendering

    def process_icon(self, r: ProcRow) -> QIcon:
        """The executable's own icon (Windows shell), cached per path; a kind-coloured dot otherwise."""
        path = r.detail.exe
        if path and path not in self._icons:
            icon = self._icon_provider.icon(QFileInfo(path)) if os.path.isfile(path) else QIcon()
            self._icons[path] = icon
        icon = self._icons.get(path) if path else None
        if icon is not None and not icon.isNull():
            return icon
        key = "kind:" + r.kind
        if key not in self._icons:
            pix = QPixmap(18, 18)
            pix.fill(Qt.GlobalColor.transparent)
            p = QPainter(pix)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setBrush(QBrush(QColor(KIND_COLOR.get(r.kind, MUTED))))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(QRectF(3, 3, 12, 12), 4, 4)
            p.end()
            self._icons[key] = QIcon(pix)
        return self._icons[key]

    def apply(self, snap: Snapshot) -> None:
        self.snap = snap
        if self.selected_key is None:  # Auto-select the biggest LLM, like the TUI does.
            llm = max((r for r in snap.procs if r.llm), key=lambda r: r.gpu.shown_vram or 0, default=None)
            if llm:
                self.selected_key = llm.key
        self.update_tray(snap)
        if not self.isVisible():
            return  # Hidden in the tray: only the icon and its menu need fresh data.
        self.render_device(snap)
        self.render_table(snap)
        self.render_inspector()

    def render_device(self, s: Snapshot) -> None:
        nv = s.nv
        self.name_label.setText(s.adapter.name if s.adapter else (nv.name if nv else "GPU"))
        bits = [f"driver {s.driver}" if s.driver else "", f"CUDA {s.cuda}" if s.cuda else "",
                nv.driver_model if nv and nv.driver_model else "", f"backend {s.backend}"]
        self.sub_label.setText("   ·   ".join(b for b in bits if b))
        amd = bool(s.adapter and s.adapter.vendor_id == 0x1002)

        util = nv.util_gpu if nv else None
        self.cards["GPU load"].set(NA if util is None else f"{util:.0f}%", "busiest engine",
                                   BAD if util and util >= 90 else None)
        if s.vram_total and s.vram_used is not None:
            frac = s.vram_used / s.vram_total
            self.cards["VRAM"].set(gb(s.vram_used), f"of {gb(s.vram_total)}  ·  {frac:.0%}",
                                   BAD if frac >= 0.9 else WARN if frac >= 0.75 else None)
        else:
            self.cards["VRAM"].set(NA, f"of {gb(s.vram_total)}" if s.vram_total else "")
        temp = nv.temp if nv else None
        self.cards["Temperature"].set(NA if temp is None else f"{temp:.0f} °C", "",
                                      BAD if temp and temp >= 85 else WARN if temp and temp >= 75 else None)
        power = nv.power_w if nv else None
        limit = nv.power_limit_w if nv else None
        self.cards["Power"].set(NA if power is None else f"{power:.0f} W", f"limit {limit:.0f} W" if limit else "")
        clock = (nv.gfx_clock if amd else nv.sm_clock) if nv else None
        self.cards["Clock"].set(NA if clock is None else f"{clock} MHz",
                                f"memory {nv.mem_clock} MHz" if nv and nv.mem_clock else "")
        shared = s.shared_used
        self.cards["Shared RAM"].set(NA if shared is None else gb(shared),
                                     "spill to system RAM" if s.shared_is_spill else "GPU memory in RAM",
                                     WARN if shared and shared >= 1 << 30 and s.shared_is_spill else None)

        kinds, other = breakdown(s)
        parts = [(v, KIND_COLOR.get(k, MUTED)) for k, v in kinds] + [(other, OTHER_COLOR)]
        self.vram_bar.set_parts(parts if s.vram_used is not None else [], s.vram_total or 1)
        chips = [f"<span style='color:{KIND_COLOR.get(k, MUTED)}'>●</span>&nbsp;{html.escape(k)} "
                 f"<span style='color:{TEXT}'>{gb(v)}</span>" for k, v in kinds[:8]]
        if other > 32 << 20:
            chips.append(f"<span style='color:{OTHER_COLOR}'>●</span>&nbsp;unattributed <span style='color:{TEXT}'>{gb(other)}</span>")
        if s.vram_used is not None:
            chips.append(f"free <span style='color:{TEXT}'>{gb(max(s.vram_total - s.vram_used, 0))}</span>")
        self.legend.setText("&nbsp;&nbsp;&nbsp;&nbsp;".join(chips))
        attributed = s.attributed
        self.vram_text.setText(f"measured per process: {gb(attributed) if attributed is not None else NA}")
        self.note_label.setText(s.counter_status or "")
        self.note_label.setVisible(bool(s.counter_status))

    def visible_rows(self, s: Snapshot) -> list[ProcRow]:
        rows = list(s.procs)
        if not self.show_all:
            rows = [r for r in rows if not r.gpu.attributed or r.gpu.dedicated >= 32 << 20 or r.gpu.gpu_pct >= 1
                    or r.gpu.shared >= 64 << 20 or r.gpu.paged_out >= 128 << 20 or r.llm]
        query = self.search.text().strip().lower()
        if query:
            rows = [r for r in rows if query in r.name.lower() or query in r.kind.lower() or query in str(r.pid)]
        return rows

    def render_table(self, s: Snapshot) -> None:
        t = self.table
        rows = self.visible_rows(s)
        self.count_label.setText(f"{len(rows)} shown")
        head = t.horizontalHeader()
        sort_col, sort_order = head.sortIndicatorSection(), head.sortIndicatorOrder()
        t.blockSignals(True)
        t.setSortingEnabled(False)
        t.setRowCount(len(rows))
        muted, faint = QColor(MUTED), QColor(FAINT)
        right = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        for i, r in enumerate(rows):
            spill_ok = has_spill_counters(s, r) and "shared" in r.gpu.available
            pct = gpu_pct(s, r)
            runtimes = " ".join(r.detail.runtimes[:3])
            name = SortItem(r.name, r.name.lower())
            name.setIcon(self.process_icon(r))
            kind = SortItem(r.kind, r.kind)
            kind.setForeground(QColor(KIND_COLOR.get(r.kind, MUTED)))
            vram = SortItem(vram_label(r.gpu), r.gpu.shown_vram)
            vram.setTextAlignment(right)
            if not r.gpu.attributed or r.gpu.shown_vram is None:
                vram.setForeground(muted)
            else:
                f = vram.font()
                f.setWeight(QFont.Weight.DemiBold)
                vram.setFont(f)
            gpu = SortItem(NA if pct is None else (f"{pct:.0f}%" if pct >= 0.5 else "–"), pct)
            gpu.setTextAlignment(right)
            if pct is None or pct < 0.5:
                gpu.setForeground(faint)
            spill = SortItem(gb(r.gpu.shared) if spill_ok and r.gpu.shared >= 1 << 20 else ("–" if spill_ok else NA),
                             r.gpu.shared if spill_ok else None)
            spill.setTextAlignment(right)
            if spill_ok and r.gpu.shared >= 256 << 20 and r.kind in ("LLM", "AI") and s.shared_is_spill:
                spill.setForeground(QColor(BAD))
            elif not spill_ok or r.gpu.shared < 1 << 20:
                spill.setForeground(faint)
            pid = SortItem(r.pid_label, r.pid)
            pid.setForeground(muted)
            runtime = SortItem(runtimes, runtimes)
            runtime.setForeground(muted)
            inside = SortItem(r.inside, r.inside)
            inside.setForeground(QColor(KIND_COLOR["LLM"]) if r.llm else muted)
            for col, item in enumerate((name, pid, kind, vram, gpu, spill, runtime, inside)):
                item.setData(Qt.ItemDataRole.UserRole, r.key)
                t.setItem(i, col, item)
        t.setSortingEnabled(True)
        t.sortByColumn(sort_col, sort_order)
        if self.selected_key is not None:
            for i in range(t.rowCount()):
                if t.item(i, 0).data(Qt.ItemDataRole.UserRole) == self.selected_key:
                    t.selectRow(i)
                    break
        t.blockSignals(False)

    def _on_select(self) -> None:
        items = self.table.selectedItems()
        if items:
            self.selected_key = items[0].data(Qt.ItemDataRole.UserRole)
            self.render_inspector()

    @staticmethod
    def _placeholder() -> str:
        return f"<p style='color:{MUTED}'>Select a process to see what's inside its GPU memory.</p>"

    def render_inspector(self) -> None:
        s = self.snap
        r = next((x for x in s.procs if x.key == self.selected_key), None) if s else None
        if r is None:
            self.inspector.setHtml(self._placeholder())
            return
        esc = html.escape
        wddm = has_wddm_counters(s, r)
        kind_color = KIND_COLOR.get(r.kind, MUTED)

        def stat(title: str, value: str) -> str:
            return (f"<td style='padding:0 22px 0 0'><div style='color:{MUTED};font-size:8pt'>{title}</div>"
                    f"<div style='font-size:13pt;font-weight:600'>{esc(value)}</div></td>")

        engines = " ".join(f"{k} {v:.0f}%" for k, v in r.gpu.engines.items() if v >= 0.5) or "idle"
        out = [f"<div style='font-size:14pt;font-weight:600'>{esc(r.name)}</div>",
               f"<div style='color:{MUTED}'>PID {esc(r.pid_label)} &nbsp;·&nbsp; "
               f"<span style='color:{kind_color}'>{esc(r.kind)}</span>"
               + (f" &nbsp;·&nbsp; {esc(' '.join(r.detail.runtimes))}" if r.detail.runtimes else "") + "</div><br>",
               "<table cellspacing='0'><tr>"
               + stat("VRAM", vram_label(r.gpu))
               + stat("SPILL (RAM)", gb(r.gpu.shared) if has_spill_counters(s, r) else NA)
               + stat("PAGED (EST)", gb(r.gpu.paged_out) if wddm and r.gpu.paged_available else NA)
               + "</tr></table><br>",
               f"<div><span style='color:{MUTED}'>Engines</span> &nbsp;"
               f"{esc(engines) if has_engine_counters(s, r) else NA}</div>"]

        def note(text: str, color: str = MUTED) -> None:
            out.append(f"<p style='color:{color}'>{text}</p>")

        if r.gpu.inferred is not None or (r.gpu.attributed and r.gpu.inferred_by):
            note(esc(inferred_note(r.gpu)))
        if wddm and r.gpu.paged_out >= 64 << 20:
            note(f"{gb(r.gpu.paged_out)} of {gb(r.gpu.committed)} committed is not accounted for by local/non-local "
                 "usage. Estimated non-residency, not proof of eviction or disk paging.", WARN)
        v = r.llm
        if v:
            if v.segments:
                total = max(r.gpu.shown_vram or 0, sum(x.bytes for x in v.segments), 1)
                seg_colors = {"weights": "#c084fc", "kv": "#fb923c", "compute": "#facc15", "runtime": "#64748b",
                              "unknown": OTHER_COLOR}
                bar = "".join(f"<td style='background:{seg_colors.get(x.kind, MUTED)}' width='{max(int(100 * x.bytes / total), 1)}%'>"
                              "&nbsp;</td>" for x in v.segments)
                out.append(f"<br><div style='color:{MUTED};font-size:8pt'>MODEL MEMORY</div>"
                           f"<table width='100%' cellspacing='0' cellpadding='0' style='margin-top:4px'><tr>{bar}</tr></table>")
                out.append("<p>" + " &nbsp; ".join(
                    f"<span style='color:{seg_colors.get(x.kind, MUTED)}'>●</span> {esc(x.label)} "
                    f"{'<b>' if x.exact else ''}{gb(x.bytes)}{'</b>' if x.exact else ''}" for x in v.segments)
                    + (f"<br><span style='color:{GOOD}'>allocated sizes from {esc(os.path.basename(v.log_source))}</span>"
                       if v.log_source else "") + "</p>")
            for i, g in enumerate(v.models):
                f = v.files[i] if i < len(v.files) else None
                facts = " · ".join(x for x in (g.arch, g.params_label, g.quant,
                                               f"{g.n_layers} layers" if g.n_layers else "",
                                               f"ctx {g.ctx_train:,}" if g.ctx_train else "",
                                               f"~{gb(g.gpu_weight_bytes())} on GPU (est)") if x)
                out.append(f"<p><span style='color:{KIND_COLOR['LLM']}'>{esc(v.kind_label(i))}</span> "
                           f"<b>{esc(v.label(i))}</b><br><span style='color:{MUTED}'>{esc(facts)}"
                           + (f" · evidence <span style='color:{GOOD}'>{esc(f.evidence)}</span>" if f else "")
                           + "</span></p>")
            if v.server:
                sv = v.server
                line = f"<span style='color:{MUTED}'>Server</span> {esc(sv.kind)} {esc(sv.url)}"
                if sv.n_ctx:
                    line += f" · ctx {sv.n_ctx:,}"
                if sv.slots_total is not None:
                    line += f" · slots {sv.slots_busy}/{sv.slots_total}"
                if sv.gen_tok_s:
                    line += f" · <b style='color:{GOOD}'>{sv.gen_tok_s:.1f} tok/s</b>"
                out.append(f"<p>{line}</p>")
            for n in v.notes:
                note("• " + esc(n), BAD if n.startswith("!") else MUTED)
        else:
            if (text := _explain(r.kind)):
                note(esc(text))
            for m in r.detail.models:
                out.append(f"<p>file: {esc(m.store_name or os.path.basename(m.path))} "
                           f"<span style='color:{MUTED}'>({gb(m.size)}, {esc(m.evidence)})</span></p>")
            if r.detail.candidates:
                note("No mapped model file was observed. Installed candidates (not proven loaded): "
                     + esc(", ".join(m.store_name or os.path.basename(m.path) for m in r.detail.candidates)))
        if r.detail.ports:
            note("Listening on " + esc(", ".join(map(str, r.detail.ports[:8]))), FAINT)
        if r.detail.cmdline:
            note(f"<small>{esc(' '.join(r.detail.cmdline)[:400])}</small>", FAINT)
        elif r.detail.access_denied:
            note("Protected process: run as administrator for runtime and file details.", FAINT)
        self.inspector.setHtml("".join(out))


def main() -> None:
    ap = argparse.ArgumentParser(prog="gtm-gui", description="GPU Task Manager desktop window and tray icon.")
    ap.add_argument("--gpu", type=int, default=0, help="GPU index to show first (default 0)")
    ap.add_argument("-i", "--interval", type=float, default=1.0, help="refresh seconds (default 1)")
    ap.add_argument("--tray", action="store_true", help="start minimized to the tray")
    ap.add_argument("--no-host", action="store_true", help="WSL: don't read Windows host GPU counters")
    args = ap.parse_args()
    if args.gpu < 0:
        ap.error("--gpu must be a non-negative index")
    if not math.isfinite(args.interval) or args.interval <= 0:
        ap.error("--interval must be a finite number greater than zero")
    if sys.platform == "win32":
        try:  # Own taskbar identity, so Windows shows our icon instead of python.exe's.
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("gputaskman.gui")
        except Exception:
            pass
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("GPU Task Manager")
    app.setStyle("Fusion")
    app.setQuitOnLastWindowClosed(False)  # the tray keeps running after the window is hidden
    app.setWindowIcon(QIcon(tray_pixmap(0.6)))
    window = MainWindow(gpu_index=args.gpu, interval=args.interval, host=not args.no_host)
    if args.gpu < window.gpu_box.count():
        window.gpu_box.blockSignals(True)
        window.gpu_box.setCurrentIndex(args.gpu)
        window.gpu_box.blockSignals(False)
    if not (args.tray and window.tray.isVisible()):
        window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
