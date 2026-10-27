"""ATCB Giọng đọc: the window teachers use to turn an exported .json (or typed sentences) into mp3 files (spec 12.8, screen 14).

Qt only does the window; every rule (file checks, names, hashes, tags, mp3) lives in core.py.
Run with: uv run --frozen --extra gui python -m atcb_tts.gui
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QSize, QStandardPaths, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import TOOL_VERSION
from .core import (
    ExportError,
    Export,
    Item,
    differs_from_default,
    is_current,
    export_scope,
    load_engine,
    load_export,
    load_lexicon,
    make_all,
    mp3_seconds,
    short_voice,
    slot_label,
    typed_items,
    voice_details,
    voice_summary,
)
from .defaults import MODEL, MODELS, VOICE, tool_url
from .player import Player
from .ui_text import eta_text, format_seconds, scope_text

HERE = Path(__file__).resolve().parent.parent
PLATFORM = "Windows" if sys.platform.startswith("win") else "macOS" if sys.platform == "darwin" else sys.platform
SPINNER = "◐◓◑◒"

GREEN, GREEN_DARK, PURPLE, PURPLE_DARK = "#1F7A5C", "#17573F", "#6B5BB5", "#4A3D8F"
INK, MUTED, LINE, SOFT = "#1D2B27", "#4A5B55", "#C9D6CF", "#F4F8F3"

STYLE = f"""
QWidget {{ color: {INK}; font-size: 14px; }}
QMainWindow, #outer {{ background: #DCE6E0; }}
#card {{ background: #FFFFFF; border-radius: 12px; }}
QLabel#muted {{ color: {MUTED}; font-size: 12px; }}
QLabel#fieldLabel {{ color: {MUTED}; font-size: 12px; font-weight: 600; }}
QPushButton {{ height: 36px; padding: 0 14px; border-radius: 10px; border: 1px solid {LINE}; background: #FFFFFF; }}
QPushButton:disabled {{ color: #9AA9A3; background: {SOFT}; }}
QPushButton#primary {{ background: {GREEN}; color: #FFFFFF; border: none; font-weight: 600; padding: 0 16px; height: 40px; }}
QPushButton#primary:hover {{ background: {GREEN_DARK}; }}
QPushButton#primary:disabled {{ background: #A7CBBD; color: #FFFFFF; }}
QPushButton#secondary {{ height: 40px; }}
QPushButton#reset {{ border: 1px solid {GREEN}; color: {GREEN}; font-weight: 600; height: 38px; }}
QPushButton#reset:disabled {{ border-color: {LINE}; color: #9AA9A3; background: #FFFFFF; }}
QPushButton#tab {{ border-radius: 18px; }}
QPushButton#tab:checked {{ background: {INK}; color: #FFFFFF; border-color: {INK}; }}
QPushButton#play {{ width: 32px; height: 32px; padding: 0; border-radius: 8px; color: {GREEN}; }}
QComboBox {{ height: 38px; border-radius: 10px; border: 1px solid {LINE}; padding: 0 10px; background: #FFFFFF; }}
QComboBox QAbstractItemView {{ background: #FFFFFF; color: {INK}; selection-background-color: #DDEFE6; selection-color: {INK}; }}
QPlainTextEdit {{ background: #FFFFFF; border-radius: 10px; border: 1px solid {LINE}; padding: 6px 8px; }}
QProgressBar {{ height: 10px; border-radius: 5px; background: #EEF3F0; border: none; }}
QProgressBar::chunk {{ background: {GREEN}; border-radius: 5px; }}
QListWidget {{ background: #FFFFFF; border: none; }}
QListWidget::item {{ border-top: 1px solid #EEF3F0; }}
QLabel#banner {{ background: #FCEFD2; color: #5C3E08; border-radius: 10px; padding: 8px 12px; font-size: 13px; }}
QLabel#error {{ background: #FBE3DA; color: #6B2410; border-radius: 10px; padding: 8px 12px; font-size: 13px; }}
#drop {{ border: 1.5px dashed {LINE}; border-radius: 12px; }}
"""


class EngineLoader(QThread):
    """Loads a VieNeu model in the background (the first time it downloads it, which can take minutes)."""

    loaded = Signal(str, object, list)  # model, engine, [(voice short name, details)]
    failed = Signal(str)

    def __init__(self, model: str) -> None:
        super().__init__()
        self.model = model

    def run(self) -> None:
        try:
            engine = load_engine(self.model)
            voices: list[tuple[str, str]] = []
            for label, _ in engine.list_preset_voices():
                name = short_voice(label)
                if all(name != known for known, _ in voices):
                    voices.append((name, voice_details(label)))
            self.loaded.emit(self.model, engine, voices)
        except Exception as err:  # noqa: BLE001 - shown to the teacher
            self.failed.emit(str(err) or err.__class__.__name__)


class MakeWorker(QThread):
    started_item = Signal(str)
    progressed = Signal(int, int, str, str)  # index, total, file, status
    finished_all = Signal(list)
    failed = Signal(str)

    def __init__(self, engine, export: Export, out_dir: Path, voice: str, force: bool) -> None:
        super().__init__()
        self.engine, self.export, self.out_dir, self.voice, self.force = engine, export, out_dir, voice, force
        self.stop_flag = threading.Event()

    def run(self) -> None:
        try:
            report = make_all(
                self.export,
                self.out_dir,
                voice_name=self.voice,
                lexicon=load_lexicon(HERE / "lexicon.json"),
                only_missing=not self.force,
                engine=self.engine,
                on_start=lambda item: self.started_item.emit(item.file),
                on_progress=lambda i, n, item, status: self.progressed.emit(i, n, item.file, status),
                should_stop=self.stop_flag.is_set,
            )
            self.finished_all.emit(report)
        except Exception as err:  # noqa: BLE001
            self.failed.emit(str(err) or err.__class__.__name__)


class Row(QWidget):
    """One sentence in the list: status icon, name + file, result text, play button."""

    play_clicked = Signal(str)

    def __init__(self, item: Item) -> None:
        super().__init__()
        self.item = item
        name = slot_label(item.slot) if item.slot else item.text
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 6, 4, 6)
        layout.setSpacing(10)
        self.icon = QLabel("○")
        self.icon.setFixedWidth(18)
        title = QLabel(f"<b>{_escape(_elide(name, 60))}</b> <span style='color:{MUTED}; font-size:11px'>{_escape(_elide(item.file, 60))}</span>")
        title.setToolTip(item.text)
        title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.state = QLabel("Chờ")
        self.play = QPushButton("▶")
        self.play.setObjectName("play")
        self.play.setAccessibleName(f"Nghe thử {name}")
        self.play.setCursor(Qt.CursorShape.PointingHandCursor)
        self.play.setVisible(False)
        self.play.clicked.connect(lambda: self.play_clicked.emit(item.file))
        layout.addWidget(self.icon)
        layout.addWidget(title, 1)
        layout.addWidget(self.state)
        layout.addWidget(self.play)
        self.set_waiting()

    def _set(self, icon: str, color: str, text: str, text_color: str = MUTED, bold: bool = False, play: bool = False) -> None:
        self.icon.setText(icon)
        self.icon.setStyleSheet(f"color: {color}; font-weight: 700;")
        self.state.setText(text)
        self.state.setStyleSheet(f"color: {text_color}; font-size: 13px;" + (" font-weight: 600;" if bold else ""))
        self.play.setVisible(play)

    def set_waiting(self) -> None:
        self._set("○", "#C9D6CF", "Chờ", "#6B7C75")

    def set_making(self, frame: str) -> None:
        self._set(frame, PURPLE, "Đang tạo…", PURPLE_DARK, bold=True)

    def set_done(self, seconds: str) -> None:
        self._set("✓", GREEN, format_seconds(float(seconds)) if seconds else "Xong", play=True)

    def set_existing(self) -> None:
        self._set("✓", GREEN, "Đã có", play=True)

    def set_error(self, message: str) -> None:
        self._set("⚠", "#B45309", "Lỗi", "#B45309", bold=True)
        self.state.setToolTip(message)


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _elide(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def documents_dir() -> Path:
    found = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
    return Path(found or Path.home()) / "ATCB Giọng đọc"


class Window(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"ATCB Giọng đọc · phiên bản {TOOL_VERSION} · {PLATFORM}")
        self.resize(760, 700)
        self.setMinimumSize(700, 640)
        self.setAcceptDrops(True)
        self.player = Player()
        self.engine = None
        self.engine_model = ""
        self.loader: EngineLoader | None = None
        self.worker: MakeWorker | None = None
        self.export: Export | None = None  # from the .json tab
        self.file_name = ""
        self.typed: list[Item] = []
        self.voice_details: dict[str, str] = {}
        self.typed_notes: list[str] = []
        self.rows: dict[str, Row] = {}
        self.started_at = 0.0
        self.made = 0
        self.errors = 0
        self.finished_ok = False
        self.last_out_dir: Path | None = None
        self.spin = 0
        self.playing_file = ""
        self._build()
        self.timer = QTimer(self, interval=150)
        self.timer.timeout.connect(self._tick)
        self._load_engine(MODEL)

    # ---- layout -------------------------------------------------------------------------------

    def _build(self) -> None:
        outer = QWidget()
        outer.setObjectName("outer")
        self.setCentralWidget(outer)
        outer_layout = QVBoxLayout(outer)
        outer_layout.setContentsMargins(20, 20, 20, 20)
        card = QFrame()
        card.setObjectName("card")
        outer_layout.addWidget(card)
        root = QVBoxLayout(card)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(12)

        steps = QHBoxLayout()
        steps.setSpacing(8)
        for number, text, bg, fg, bold in (
            ("1", "Xuất file .json trên web", "#DDEFE6", GREEN_DARK, False),
            ("2", "Tạo giọng đọc ở đây", "#E9E5F6", PURPLE_DARK, True),
            ("3", "Kéo thư mục mp3 lên web", SOFT, MUTED, False),
        ):
            label = QLabel(f"<b>{number}</b>&nbsp; {text}")
            label.setStyleSheet(f"background: {bg}; color: {fg}; border-radius: 10px; padding: 8px 10px; font-size: 13px;" + (" font-weight: 600;" if bold else ""))
            label.setWordWrap(True)
            steps.addWidget(label, 1)
        root.addLayout(steps)

        tabs = QHBoxLayout()
        self.tab_group = QButtonGroup(self)
        self.tab_file = self._tab_button("Từ file .json (xuất trên web)")
        self.tab_text = self._tab_button("Gõ câu")
        self.tab_file.setChecked(True)
        self.tab_group.addButton(self.tab_file, 0)
        self.tab_group.addButton(self.tab_text, 1)
        self.tab_group.idClicked.connect(self._on_tab)
        tabs.addWidget(self.tab_file)
        tabs.addWidget(self.tab_text)
        tabs.addStretch(1)
        root.addLayout(tabs)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._file_page())
        self.pages.addWidget(self._text_page())
        root.addWidget(self.pages)

        options = QHBoxLayout()
        options.setSpacing(10)
        self.model_box = QComboBox()
        for name in MODELS:
            self.model_box.addItem(name + (" (mặc định)" if name == MODEL else ""), name)
        self.voice_box = QComboBox()
        self.voice_box.addItem(VOICE + " (mặc định)", VOICE)
        self.reset_button = QPushButton("↺ Mặc định")
        self.reset_button.setObjectName("reset")
        options.addLayout(self._field("Model", self.model_box), 2)
        options.addLayout(self._field("Giọng", self.voice_box), 3)
        options.addWidget(self.reset_button, 0, Qt.AlignmentFlag.AlignBottom)
        root.addLayout(options)
        self.voice_info = QLabel("")
        self.voice_info.setObjectName("muted")
        self.voice_info.setWordWrap(True)
        root.addWidget(self.voice_info)
        self.model_box.activated.connect(self._on_model)
        self.voice_box.activated.connect(lambda _: (self._rebuild_list(), self._refresh()))
        self.reset_button.clicked.connect(self._reset_defaults)

        self.banner = QLabel(
            "Đang dùng model hoặc giọng khác giọng chuẩn của trường. Giọng sẽ không đồng đều với các câu khác, "
            "và web sẽ đánh dấu các file này khi tải lên. Bấm “Mặc định” để quay về Kim Thanh, VieNeu-TTS-v3-Turbo."
        )
        self.banner.setObjectName("banner")
        self.banner.setWordWrap(True)
        self.banner.setVisible(False)
        self.banner.setAccessibleName("Cảnh báo giọng khác chuẩn")
        root.addWidget(self.banner)

        self.error_box = QLabel()
        self.error_box.setObjectName("error")
        self.error_box.setWordWrap(True)
        self.error_box.setVisible(False)
        root.addWidget(self.error_box)

        progress = QHBoxLayout()
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setRange(0, 1)
        self.progress_label = QLabel("")
        self.progress_label.setStyleSheet(f"color: {MUTED};")
        progress.addWidget(self.bar, 1)
        progress.addWidget(self.progress_label)
        root.addLayout(progress)

        self.list = QListWidget()
        self.list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        root.addWidget(self.list, 1)

        bottom = QHBoxLayout()
        bottom.setSpacing(10)
        self.out_label = QLabel("")
        self.out_label.setObjectName("muted")
        self.out_label.setWordWrap(True)
        self.force_box = QCheckBox("Tạo lại tất cả")
        self.stop_button = QPushButton("Dừng")
        self.stop_button.setObjectName("secondary")
        self.open_button = QPushButton("Mở thư mục kết quả")
        self.open_button.setObjectName("secondary")
        self.start_button = QPushButton("Tạo giọng đọc")
        self.start_button.setObjectName("primary")
        bottom.addWidget(self.out_label, 1)
        bottom.addWidget(self.force_box)
        bottom.addWidget(self.stop_button)
        bottom.addWidget(self.open_button)
        bottom.addWidget(self.start_button)
        root.addLayout(bottom)
        self.stop_button.clicked.connect(self._stop)
        self.open_button.clicked.connect(self._open_folder)
        self.start_button.clicked.connect(self._start)
        self.setStyleSheet(STYLE)
        self._refresh()

    def _tab_button(self, text: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("tab")
        button.setCheckable(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    def _field(self, caption: str, box: QComboBox) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setSpacing(4)
        label = QLabel(caption)
        label.setObjectName("fieldLabel")
        column.addWidget(label)
        column.addWidget(box)
        return column

    def _file_page(self) -> QWidget:
        page = QFrame()
        page.setObjectName("drop")
        layout = QHBoxLayout(page)
        layout.setContentsMargins(14, 12, 14, 12)
        icon = QLabel("📄")
        icon.setStyleSheet("font-size: 24px;")
        self.file_title = QLabel("Kéo file .json vào đây hoặc bấm “Chọn file”")
        self.file_title.setStyleSheet("font-weight: 600;")
        self.file_title.setWordWrap(True)
        self.file_sub = QLabel("File lấy từ nút “Xuất text đọc (.json)” hoặc “Xuất phần còn thiếu” trên web.")
        self.file_sub.setObjectName("muted")
        self.file_sub.setWordWrap(True)
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(self.file_title)
        text.addWidget(self.file_sub)
        self.choose_button = QPushButton("Chọn file")
        self.choose_button.clicked.connect(self._choose_file)
        layout.addWidget(icon)
        layout.addLayout(text, 1)
        layout.addWidget(self.choose_button)
        return page

    def _text_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        caption = QLabel("Mỗi dòng là một câu, tạo một file mp3")
        caption.setObjectName("fieldLabel")
        self.text_edit = QPlainTextEdit()
        self.text_edit.setFixedHeight(84)
        self.text_edit.setPlaceholderText("An toàn trong nhà bếp\nCon không chạm vào nồi đang nóng nhé.")
        self.text_edit.textChanged.connect(self._on_text)
        hint = QLabel(
            "Nên bấm “Sao chép câu” trên web rồi dán vào đây để câu chữ khớp từng dấu. File đặt tên theo câu, "
            "ví dụ <code>an-toan-trong-nha-bep__4c1d07aa.mp3</code>; khi tải lên đúng ô trên web, web tự kiểm tra câu chữ."
        )
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(caption)
        layout.addWidget(self.text_edit)
        layout.addWidget(hint)
        return page

    # ---- state --------------------------------------------------------------------------------

    @property
    def running(self) -> bool:
        return self.worker is not None and self.worker.isRunning()

    @property
    def loading(self) -> bool:
        return self.loader is not None and self.loader.isRunning()

    def _items(self) -> list[Item]:
        if self.tab_text.isChecked():
            return self.typed
        return self.export.items if self.export else []

    def _scope(self) -> str:
        if self.tab_text.isChecked():
            return "go-cau"
        return export_scope(self.export) if self.export else ""

    def _out_dir(self) -> Path | None:
        scope = self._scope()
        return documents_dir() / scope if scope else None

    def _model(self) -> str:
        return self.model_box.currentData() or MODEL

    def _voice(self) -> str:
        return self.voice_box.currentData() or VOICE

    def _refresh(self) -> None:
        """Re-draws everything that depends on the current choices (not on a run in progress)."""
        different = differs_from_default(self._model(), self._voice())
        self.banner.setVisible(different)
        details = self.voice_details.get(self._voice(), "")
        self.voice_info.setText(f"Giọng {self._voice()}: {voice_summary(details)}" if details else "")
        self.reset_button.setEnabled(different and not self.running)
        out = self._out_dir()
        self.out_label.setText(f"Lưu vào: {out}" if out else "")
        busy = self.running or self.loading
        for widget in (self.model_box, self.voice_box, self.tab_file, self.tab_text, self.choose_button, self.text_edit, self.force_box):
            widget.setEnabled(not busy)
        self.reset_button.setEnabled(different and not busy)
        self.stop_button.setEnabled(self.running)
        self.open_button.setEnabled(bool(out) and out.exists() and not self.running)
        ready = bool(self._items()) and self.engine is not None and not busy
        self.start_button.setEnabled(ready)
        self.start_button.setText("Thử lại các câu lỗi" if self.errors and not self.running else "Tạo giọng đọc")

    def _show_error(self, message: str) -> None:
        self.error_box.setText(message)
        self.error_box.setVisible(bool(message))

    def _rebuild_list(self) -> None:
        self.list.clear()
        self.rows.clear()
        out = self._out_dir()
        for item in self._items():
            row = Row(item)
            row.play_clicked.connect(self._play)
            if out and is_current(out / item.file, self._model(), self._voice(), item.text_hash):
                row.set_existing()
            entry = QListWidgetItem()
            entry.setSizeHint(QSize(0, max(row.sizeHint().height(), 42)))
            self.list.addItem(entry)
            self.list.setItemWidget(entry, row)
            self.rows[item.file] = row
        total = len(self._items())
        self.bar.setRange(0, max(total, 1))
        self.bar.setValue(0)
        self.progress_label.setText("")
        self.errors = 0
        self.finished_ok = False

    # ---- engine -------------------------------------------------------------------------------

    def _load_engine(self, model: str) -> None:
        self.engine = None
        self.loader = EngineLoader(model)
        self.loader.loaded.connect(self._engine_loaded)
        self.loader.failed.connect(self._engine_failed)
        self.bar.setRange(0, 0)
        self.progress_label.setText("Đang nạp model (lần đầu cần mạng, vài phút)…")
        self.loader.start()
        self._refresh()

    def _engine_loaded(self, model: str, engine, voices: list) -> None:
        self.engine, self.engine_model = engine, model
        wanted = self._voice()
        self.voice_details = {}
        self.voice_box.blockSignals(True)
        self.voice_box.clear()
        for name, details in voices:
            short = details.replace("Phong cách ", "").replace("Giọng đọc ", "")
            text = name + (" (mặc định)" if name == VOICE else "") + (f" — {short}" if short else "")
            self.voice_box.addItem(text, name)
            self.voice_box.setItemData(self.voice_box.count() - 1, voice_summary(details) or name, Qt.ItemDataRole.ToolTipRole)
            self.voice_details[name] = details
        index = self.voice_box.findData(wanted)
        if index < 0:
            fallback = self.voice_box.findData(VOICE)
            index = fallback if fallback >= 0 else 0
            self._show_error(f"Model này không có giọng “{wanted}”, đã chọn lại “{self.voice_box.itemData(index)}”.")
        self.voice_box.setCurrentIndex(index)
        self.voice_box.blockSignals(False)
        self._rebuild_list()
        self.progress_label.setText("")
        self._refresh()

    def _engine_failed(self, message: str) -> None:
        self.bar.setRange(0, 1)
        self.progress_label.setText("")
        self._show_error(f"Không nạp được model: {message}\nKiểm tra kết nối mạng (lần đầu cần tải model) rồi mở lại công cụ.")
        self._refresh()

    def _on_model(self) -> None:
        self._show_error("")
        self._load_engine(self._model())

    def _reset_defaults(self) -> None:
        self._show_error("")
        if self._model() != MODEL:
            self.model_box.setCurrentIndex(self.model_box.findData(MODEL))
            self._load_engine(MODEL)
        else:
            self.voice_box.setCurrentIndex(max(self.voice_box.findData(VOICE), 0))
            self._refresh()

    # ---- input --------------------------------------------------------------------------------

    def _on_tab(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        self._show_error("")
        if index == 1:
            self._on_text()
        else:
            self._rebuild_list()
            self._refresh()

    def _on_text(self) -> None:
        self.typed, self.typed_notes = typed_items(self.text_edit.toPlainText())
        self._show_error("\n".join(self.typed_notes))
        self._rebuild_list()
        self._refresh()

    def _choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Chọn file .json xuất từ web", str(Path.home() / "Downloads"), "File xuất (*.json)")
        if path:
            self._open_export(Path(path))

    def _open_export(self, path: Path) -> None:
        self.tab_file.setChecked(True)
        self.pages.setCurrentIndex(0)
        try:
            export = load_export(path)
        except ExportError as err:
            message = str(err)
            url = tool_url()
            if "bản mới" in message and url:
                message += f"\nTải bản mới tại: {url}"
            self._show_error(message)
            return
        if not export.items:
            self._show_error("File xuất không có câu nào để đọc.")
            return
        self._show_error("")
        self.export, self.file_name = export, path.name
        self.file_title.setText(path.name)
        self.file_sub.setText(scope_text(len(export.items), export_scope(export)))
        self.choose_button.setText("Chọn file khác")
        # The web decides model and voice; unknown ones fall back to the standard pair.
        model = export.model if export.model in MODELS else MODEL
        if self.model_box.currentData() != model:
            self.model_box.setCurrentIndex(self.model_box.findData(model))
            self._load_engine(model)
        index = self.voice_box.findData(export.voice)
        if index >= 0:
            self.voice_box.setCurrentIndex(index)
        self._rebuild_list()
        self._refresh()

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt name
        if not self.running and event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.suffix.lower() == ".json":
                self._open_export(path)
                break

    # ---- run ----------------------------------------------------------------------------------

    def _start(self) -> None:
        out = self._out_dir()
        items = self._items()
        if not out or not items or self.engine is None:
            return
        self._show_error("")
        self.player.stop()
        # The export file's own model/voice are only defaults; the choices in the window win.
        export = Export(model=self._model(), voice=self._voice(), items=items)
        force = self.force_box.isChecked()
        self.last_out_dir = out
        self.errors = 0
        self.made = 0
        self.started_at = time.monotonic()
        total = len(items)
        for item in items:
            if force:
                self.rows[item.file].set_waiting()
        self.bar.setRange(0, total)
        self.bar.setValue(0)
        self.worker = MakeWorker(self.engine, export, out, self._voice(), force)
        self.worker.started_item.connect(self._on_item_start)
        self.worker.progressed.connect(self._on_progress)
        self.worker.finished_all.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()
        self.timer.start()
        self._refresh()

    def _stop(self) -> None:
        if self.worker:
            self.worker.stop_flag.set()
            self.stop_button.setEnabled(False)
            self.progress_label.setText("Đang dừng sau câu này…")

    def _on_item_start(self, file: str) -> None:
        self.current_file = file
        row = self.rows.get(file)
        if row:
            row.set_making(SPINNER[self.spin % len(SPINNER)])
            self.list.scrollToItem(self.list.item(list(self.rows).index(file)))

    def _on_progress(self, index: int, total: int, file: str, status: str) -> None:
        row = self.rows.get(file)
        out = self.last_out_dir
        if status == "ok":
            self.made += 1
            if row:
                seconds = self._duration(out / file) if out else ""
                row.set_done(seconds)
        elif status == "skipped":
            if row:
                row.set_existing()
        else:
            self.errors += 1
            if row:
                row.set_error(status.removeprefix("error: "))
        self.bar.setValue(index)
        self.progress_label.setText(eta_text(index, total, time.monotonic() - self.started_at, self.made))

    @staticmethod
    def _duration(path: Path) -> str:
        try:
            return f"{mp3_seconds(path):.1f}"
        except Exception:  # noqa: BLE001 - the duration is only a label
            return ""

    def _on_finished(self, report: list) -> None:
        self.timer.stop()
        stopped = len(report) < len(self._items())
        ok = sum(r["status"] == "ok" for r in report)
        failed = [r for r in report if r["status"].startswith("error")]
        self.finished_ok = not failed and not stopped
        if stopped:
            self.progress_label.setText(f"Đã dừng · {ok} file mới")
        elif failed:
            self.progress_label.setText(f"Xong · {len(failed)} câu lỗi")
            self._show_error(f"{len(failed)} câu chưa tạo được (đánh dấu ⚠, rê chuột vào chữ “Lỗi” để xem lý do). Bấm “Thử lại các câu lỗi”.")
        else:
            self.progress_label.setText(f"Xong · {ok} file mới")
        self.worker = None
        self._refresh()

    def _on_failed(self, message: str) -> None:
        self.timer.stop()
        self.worker = None
        self._show_error(f"Có lỗi khi tạo giọng đọc: {message}")
        self._refresh()

    def _tick(self) -> None:
        self.spin += 1
        file = getattr(self, "current_file", "")
        row = self.rows.get(file)
        if row and self.running and row.state.text() == "Đang tạo…":
            row.set_making(SPINNER[self.spin % len(SPINNER)])

    # ---- results ------------------------------------------------------------------------------

    def _play(self, file: str) -> None:
        out = self.last_out_dir or self._out_dir()
        if not out:
            return
        path = out / file
        if self.playing_file == file:
            self.player.stop()
            self.playing_file = ""
            return
        if path.exists():
            self.playing_file = file
            self.player.play(path)

    def _open_folder(self) -> None:
        out = self.last_out_dir if self.last_out_dir and self.last_out_dir.exists() else self._out_dir()
        if out and out.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(out)))

    def closeEvent(self, event) -> None:  # noqa: N802
        self.player.stop()
        if self.running:
            answer = QMessageBox.question(self, "Đang tạo giọng đọc", "Dừng và đóng công cụ? File đã xong vẫn được giữ.")
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.worker.stop_flag.set()
            self.worker.wait(30000)
        event.accept()


def main() -> int:
    app = QApplication(sys.argv)
    # The stylesheet is a light design; without this a dark system theme leaves dark-on-dark text in inputs and lists.
    app.setStyle("Fusion")
    app.styleHints().setColorScheme(Qt.ColorScheme.Light)
    window = Window()
    window.show()
    if len(sys.argv) > 1 and Path(sys.argv[1]).suffix.lower() == ".json":
        window._open_export(Path(sys.argv[1]))
    return app.exec()


if __name__ == "__main__":
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    sys.exit(main())
