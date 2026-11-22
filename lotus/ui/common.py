from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QActionGroup
from PySide6.QtWidgets import (
    QDialog,
    QComboBox,
    QMenu,
    QSizePolicy,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from lotus.settings import ROOT

LEVELS = {"low": "Обычный", "moderate": "Умеренный", "elevated": "Повышенный", "high": "Высокий"}
CONFIDENCE = {"low": "Низкая", "medium": "Средняя", "high": "Высокая"}
COMPONENTS = {
    "vulnerability": "Уязвимость функции",
    "precedents": "Применимые схемы",
    "signals": "Закупочные сигналы",
    "control_gap": "Контрольная среда",
}
EVENTS = {"trip": "Поездка", "purchase": "Покупка", "vehicle": "Транспорт", "realestate": "Недвижимость"}
COLORS = {"low": "#649d8b", "moderate": "#d0ac58", "elevated": "#d78248", "high": "#b95752"}
ACCENT = "#1668B5"

STYLE = """
QWidget { color: #1c2b33; font-family: 'Segoe UI Variable Text', 'Segoe UI', Arial, sans-serif; font-size: 10pt; }
QTextBrowser { color: #1c2b33; background: white; padding: 10px; }
QMainWindow, QDialog, QScrollArea, QScrollArea > QWidget > QWidget { background: #f4f6f8; }

/* ── Боковая панель ─────────────────────────────────────────── */
QFrame#sidebar { background: #102B4E; border-right: 1px solid #102B4E; }
QFrame#sidebar QLabel { color: #9fb2bf; background: transparent; }
QFrame#sidebar QLabel#brand { color: #ffffff; font-size: 17pt; font-weight: 600; letter-spacing: 0.2px; }
QFrame#sidebar QLabel#brandSub { color: #7e95a4; font-size: 8.5pt; letter-spacing: 1.2px; }
QFrame#sidebar QLabel#sideNote { color: #7e95a4; font-size: 8.5pt; line-height: 140%; }
QFrame#sidebar QListWidget { background: transparent; border: 0; outline: 0; padding: 2px; }
QFrame#sidebar QListWidget::item { color: #b6c6d0; padding: 9px 12px; border-radius: 7px; margin: 1px 0; }
QFrame#sidebar QListWidget::item:hover { color: #e6eef3; background: #273947; }
QFrame#sidebar QListWidget::item:selected { color: #ffffff; background: $ACCENT; }

/* ── Карточки и панели ──────────────────────────────────────── */
QFrame#card, QFrame#metric, QFrame#signal { background: white; border: 1px solid #e0e6ea; border-radius: 10px; }
QFrame#card:hover, QFrame#metric:hover, QFrame#signal:hover { border-color: #cfd9de; }

/* ── Типографика ────────────────────────────────────────────── */
QLabel#title { font-size: 21pt; font-weight: 600; letter-spacing: -0.4px; color: #14242c; }
QLabel#subtitle, QLabel#muted { color: #5f7280; }
QLabel#eyebrow { color: $ACCENT; font-size: 8pt; font-weight: 700; letter-spacing: 1.4px; }
QLabel#section { font-weight: 600; color: #415c6b; }
QLabel#metricValue { font-size: 22pt; font-weight: 600; color: #14242c; }
QLabel#error { color: #a34441; }
QLabel#demo { background: #E6F2FF; color: #1668B5; border: 1px solid #DCE3EC; border-radius: 8px; padding: 8px 12px; }

/* ── Кнопки ─────────────────────────────────────────────────── */
QPushButton { color: #1c2b33; background: white; border: 1px solid #c8d4da; border-radius: 7px; padding: 7px 14px; }
QPushButton:hover { background: #E6F2FF; border-color: $ACCENT; }
QPushButton:pressed { background: #D9EBFF; }
QPushButton:disabled { color: #8a9aa4; background: #eef1f3; border-color: #dde4e8; }
QPushButton#primary { color: white; background: $ACCENT; border-color: $ACCENT; font-weight: 600; }
QPushButton#primary:hover { color: white; background: #125898; border-color: #125898; }
QPushButton#primary:pressed { color: white; background: #104B82; }
QPushButton#primary:disabled { color: #7d9490; background: #d8e6e2; border-color: #d8e6e2; }

/* ── Поля ввода ─────────────────────────────────────────────── */
QLineEdit, QComboBox, QDateEdit { color: #1c2b33; background: white; border: 1px solid #c8d4da; border-radius: 6px; padding: 6px 9px; min-height: 20px; selection-background-color: #E6F2FF; selection-color: #1c2b33; }
QLineEdit:hover, QComboBox:hover, QDateEdit:hover { border-color: #a7bcc6; }
QLineEdit:focus, QComboBox:focus, QDateEdit:focus { border: 1px solid $ACCENT; }
QLineEdit:disabled, QComboBox:disabled, QDateEdit:disabled { color: #8a9aa4; background: #eef1f3; }
QComboBox::drop-down, QDateEdit::drop-down { border: 0; width: 24px; }
QComboBox QAbstractItemView, QComboBoxPrivateContainer, QComboBoxPrivateContainer QListView { color: #1c2b33; background: white; border: 1px solid #b7c8d0; outline: 0; selection-background-color: #E6F2FF; selection-color: #1c2b33; }
QComboBox QAbstractItemView::item, QComboBoxPrivateContainer QListView::item { color: #1c2b33; background: white; min-height: 28px; padding: 4px 8px; }
QComboBox QAbstractItemView::item:selected, QComboBoxPrivateContainer QListView::item:selected { color: #1c2b33; background: #E6F2FF; }

/* ── Таблицы ────────────────────────────────────────────────── */
QTableWidget { color: #1c2b33; background: white; alternate-background-color: #f7f9fa; border: 1px solid #e0e6ea; border-radius: 8px; gridline-color: #ecf0f3; outline: 0; selection-background-color: #E6F2FF; selection-color: #1c2b33; }
QTableWidget::item { padding: 2px 4px; }
QTableWidget::item:selected:active, QTableWidget::item:selected:!active { color: #1c2b33; background: #E6F2FF; }
QHeaderView::section { background: #f0f4f6; color: #47616e; border: 0; border-bottom: 1px solid #dde4e8; padding: 7px 8px; font-weight: 600; }

/* ── Вкладки ────────────────────────────────────────────────── */
QTabWidget::pane { background: white; border: 1px solid #e0e6ea; border-radius: 8px; top: -1px; }
QTabBar::tab { color: #5f7280; background: transparent; padding: 8px 14px; margin-right: 2px; border: 1px solid transparent; border-bottom: 0; border-top-left-radius: 7px; border-top-right-radius: 7px; }
QTabBar::tab:hover { color: #1c2b33; background: #eef3f5; }
QTabBar::tab:selected { background: white; color: $ACCENT; border-color: #e0e6ea; font-weight: 600; }

/* ── Прочее ─────────────────────────────────────────────────── */
QProgressBar { background: #e6ecef; border: 0; border-radius: 4px; height: 8px; text-align: center; }
QProgressBar::chunk { background: $ACCENT; border-radius: 4px; }
QTextEdit, QTextBrowser, QPlainTextEdit, QListWidget#reportRecords { color: #17344b; background: white; border: 1px solid #cbd8e3; border-radius: 7px; padding: 8px; selection-background-color: #d8ebfc; selection-color: #102b4e; }
QTextEdit#quote, QLabel#evidence { color: #183956; background: #f1f7fc; border: 1px solid #d3e2ee; border-left: 3px solid #4285ba; border-radius: 5px; padding: 8px; }
QListWidget#reportRecords::item { padding: 8px 4px; border-bottom: 1px solid #e0e8ef; }
QListWidget#reportRecords::item:selected { background: #e4effa; color: #123957; }
QPushButton#filterButton { text-align: left; padding: 5px 8px; }
QMenu { color: #1c2b33; background: white; border: 1px solid #b7c8d0; border-radius: 6px; padding: 4px; }
QMenu::item { padding: 7px 24px; border-radius: 4px; }
QMenu::item:selected { color: #1c2b33; background: #E6F2FF; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 15px; height: 15px; }
QStatusBar { color: #5f7280; background: #edf1f4; border-top: 1px solid #dde4e8; }
QStatusBar::item { border: 0; }
QToolTip { color: #1c2b33; background: white; border: 1px solid #b7c8d0; padding: 6px 8px; }
QSplitter::handle { background: #e0e6ea; }
""".replace("$ACCENT", ACCENT)


class PageCombo(QComboBox):
    def wheelEvent(self, event):
        if self.view().isVisible():
            super().wheelEvent(event)
        else:
            event.ignore()


class FilterButton(QPushButton):
    """Single-choice menu with a bounded caption, including for long function names."""
    currentIndexChanged = Signal(int)

    def __init__(self, label):
        super().__init__()
        self.label = label
        self.setObjectName("filterButton")
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setMenu(QMenu(self))
        self.choices = QActionGroup(self)
        self._index = -1

    def clear(self):
        self.menu().clear()
        self._index = -1

    def addItem(self, title, data):
        action = self.menu().addAction(title)
        action.setCheckable(True)
        action.setData(data)
        self.choices.addAction(action)
        index = len(self.menu().actions()) - 1
        action.triggered.connect(lambda checked=False: self.setCurrentIndex(index))
        if index == 0:
            self.setCurrentIndex(0)

    def findData(self, value):
        return next((i for i, a in enumerate(self.menu().actions()) if a.data() == value), -1)

    def currentData(self):
        action = self.choices.checkedAction()
        return action.data() if action else None

    def setCurrentIndex(self, index):
        actions = self.menu().actions()
        if index == self._index or not 0 <= index < len(actions):
            return
        self._index = index
        actions[index].setChecked(True)
        self.setToolTip(self.label + " · " + actions[index].text())
        self._caption()
        self.currentIndexChanged.emit(index)

    def _caption(self):
        self.setText(self.fontMetrics().elidedText(self.toolTip(), Qt.TextElideMode.ElideRight, max(20, self.width() - 30)))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._caption()


class ScrollPage(QScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.content = QWidget()
        self.layout = QVBoxLayout(self.content)
        self.layout.setContentsMargins(26, 20, 26, 24)
        self.layout.setSpacing(12)
        self.setWidget(self.content)


def add_heading(layout, eyebrow, title, description):
    eyebrow_label = QLabel(eyebrow)
    eyebrow_label.setObjectName("eyebrow")
    title_label = QLabel(title)
    title_label.setObjectName("title")
    subtitle = QLabel(description)
    subtitle.setObjectName("subtitle")
    subtitle.setWordWrap(True)
    layout.addWidget(eyebrow_label)
    layout.addSpacing(2)
    layout.addWidget(title_label)
    layout.addWidget(subtitle)
    layout.addSpacing(6)


def section_heading(text):
    label = QLabel(text)
    label.setObjectName("section")
    return label


def text_label(text, muted=False):
    label = QLabel(text)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    if muted:
        label.setObjectName("muted")
    return label


def framed(layout=None):
    frame = QFrame()
    frame.setObjectName("card")
    frame_layout = QVBoxLayout(frame)
    frame_layout.setContentsMargins(16, 13, 16, 13)
    frame_layout.setSpacing(8)
    if layout is not None:
        layout.addWidget(frame)
    return frame, frame_layout


def make_empty_state(layout, title, description, button_text, callback):
    frame, body = framed(layout)
    body.addWidget(section_heading(title))
    body.addWidget(text_label(description, muted=True))
    button = QPushButton(button_text)
    button.setObjectName("primary")
    button.clicked.connect(callback)
    body.addWidget(button)
    return frame


def set_message(label, text, error=False):
    label.setStyleSheet("color: #a34441;" if error else "")
    label.setText(text)


def make_table(headers):
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setAlternatingRowColors(True)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setStretchLastSection(True)
    return table


def money(value):
    return f"{value:,.0f} ₽".replace(",", " ")


def save_bytes(parent, suggested_name, data, file_filter):
    path, _ = QFileDialog.getSaveFileName(parent, "Сохранить файл", suggested_name, file_filter)
    if not path:
        return False
    try:
        Path(path).write_bytes(data)
    except OSError as exc:
        QMessageBox.critical(parent, "Не удалось сохранить файл", str(exc))
        return False
    return True


def save_source(parent, relative_path):
    path = ROOT / relative_path
    if not path.is_file():
        QMessageBox.warning(parent, "Источник недоступен", relative_path)
        return False
    saved = save_bytes(parent, path.name, path.read_bytes(), "Исходный файл (*.*)")
    if saved:
        from lotus.audit import log

        log("Открыт источник", "source", relative_path)
    return saved


def horizontal_line():
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setStyleSheet("color: #dfe5e8;")
    return line


def row_widget():
    widget = QWidget()
    layout = QHBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(10)
    return widget, layout


def save_registered_source(parent, source):
    from lotus.sources import source_local_path

    path = source_local_path(source)
    if path is None:
        QMessageBox.warning(parent, "Источник недоступен", "Локальный файл недоступен. Сохранены реквизиты и хеш зарегистрированной версии.")
        return False
    if save_bytes(parent, path.name, path.read_bytes(), "Исходный файл (*.*)"):
        from lotus.audit import log

        log("Экспорт источника", "source", source.id, {"title": source.title})
        return True
    return False


def show_source(parent, source, evidence=None):
    if source is None:
        QMessageBox.information(parent, "Источник", "Для этого доказательства версия источника не зарегистрирована. Доступны только сохранённые идентификатор, цитата и locator.")
        return False
    from lotus.audit import log
    from lotus.sources import source_local_path

    log("Просмотр источника", "source", source.id, {"title": source.title})
    dialog = QDialog(parent)
    dialog.setObjectName("sourceDialog")
    dialog.setWindowTitle("Источник и доказательство")
    dialog.resize(700, 550)
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(18, 18, 18, 14)
    layout.addWidget(section_heading("Сведения об источнике"))
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    card, details = framed()
    scroll.setWidget(card)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    layout.addWidget(scroll, 1)
    rows = [
        ("Название", source.title),
        ("Идентификатор", source.id),
        ("Происхождение", {"document_upload": "Загруженный документ", "local": "Локальный файл"}.get(source.origin, source.origin)),
        ("Тип", source.media_type or source.source_kind),
        ("Зарегистрировано", source.registered_at.isoformat()),
        ("SHA-256", source.sha256 or "Не применимо к производному результату"),
        ("URI / путь", source.uri or "Производный результат обработки"),
    ]
    if evidence is not None:
        rows.extend([
            ("Доказательство", f"{evidence.source_kind} {evidence.source_id}"),
            ("Цитата", evidence.quote),
            ("Координата", evidence.locator or "Не указан"),
        ])
    for label, value in rows:
        details.addWidget(text_label(label, muted=True))
        field = text_label(str(value))
        field.setTextFormat(Qt.TextFormat.PlainText)
        details.addWidget(field)
    controls, row = row_widget()
    row.addStretch()
    if source_local_path(source) is not None:
        save_button = QPushButton("Сохранить исходный файл")
        save_button.clicked.connect(lambda: save_registered_source(dialog, source))
        row.addWidget(save_button)
    close_button = QPushButton("Закрыть")
    close_button.clicked.connect(dialog.accept)
    row.addWidget(close_button)
    layout.addWidget(controls)
    dialog.exec()
    return True
