from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QCheckBox, QFileDialog, QLabel, QLineEdit, QPushButton, QTabWidget, QTableWidgetItem, QTextBrowser, QVBoxLayout, QWidget

from lotus.audit import log
from lotus.documents import parse_document
from lotus.ui.common import PageCombo, ScrollPage, add_heading, framed, make_empty_state, make_table, row_widget, save_registered_source, section_heading, show_source, text_label

PREVIEW_ROWS = 200


def section_title(text):
    return section_heading(text)


def caption(text):
    label = QLabel(text)
    label.setObjectName("eyebrow")
    return label


class DocumentPage(ScrollPage):
    def __init__(self):
        super().__init__()
        self.parsed = None
        add_heading(
            self.layout,
            "РАБОЧЕЕ ПРОСТРАНСТВО / МАТЕРИАЛЫ",
            "Документы и источники",
            "Локальный разбор с сохранением страниц, абзацев и строк таблиц",
        )
        self.document_empty = make_empty_state(
            self.layout, "Документ для предпросмотра не выбран",
            "Документальный центр разбирает DOCX, XLSX, CSV и PDF, сохраняет координаты и реквизиты источника. "
            "Начните с синтетического файла без персональных данных.",
            "Выбрать синтетический документ", self.choose_file)
        self.build_form()
        self.build_result()
        self.layout.addStretch()

    def build_form(self):
        frame, layout = framed()
        layout.addWidget(caption("ШАГ 1 · ЛОКАЛЬНЫЙ РАЗБОР"))
        layout.addWidget(section_title("Синтетический документ"))
        file_row, row = row_widget()
        self.file_path = QLineEdit()
        self.file_path.setObjectName("documentPath")
        self.file_path.setReadOnly(True)
        self.file_path.setPlaceholderText("DOCX, XLSX, CSV или PDF с текстовым слоем, до 2 МБ")
        self.browse_button = QPushButton("Выбрать файл…")
        row.addWidget(self.file_path, 1)
        row.addWidget(self.browse_button)
        layout.addWidget(file_row)
        self.confirmed = QCheckBox("Документ вымышлен и предназначен для демонстрации")
        layout.addWidget(self.confirmed)
        actions, row = row_widget()
        self.ready_hint = text_label("Разбор станет доступен после выбора файла и подтверждения.", muted=True)
        row.addWidget(self.ready_hint, 1)
        self.parse_button = QPushButton("Разобрать документ →")
        self.parse_button.setObjectName("primary")
        self.parse_button.setEnabled(False)
        self.parse_button.setToolTip("Выберите файл и подтвердите его синтетический характер")
        row.addWidget(self.parse_button)
        layout.addWidget(actions)
        self.error_label = text_label("")
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)
        self.layout.addWidget(frame)
        self.browse_button.clicked.connect(self.choose_file)
        self.confirmed.toggled.connect(self.update_ready)
        self.parse_button.clicked.connect(self.parse)

    def build_result(self):
        info_frame, info_layout = framed()
        info_layout.addWidget(caption("ШАГ 2 · ПРЕДПРОСМОТР И РЕКВИЗИТЫ"))
        self.metadata = text_label("")
        self.metadata.setWordWrap(True)
        info_layout.addWidget(self.metadata)
        self.warnings = text_label("")
        self.warnings.setWordWrap(True)
        info_layout.addWidget(self.warnings)
        self.info_frame = info_frame
        self.layout.addWidget(info_frame)
        self.tabs = QTabWidget()
        self.fragments = QTextBrowser()
        self.fragments.setOpenExternalLinks(False)
        self.tabs.addTab(self.fragments, "Текст и страницы")
        table_page = QWidget()
        table_layout = QVBoxLayout(table_page)
        picker_row, row = row_widget()
        row.addWidget(QLabel("Таблица"))
        self.table_picker = PageCombo()
        self.table_picker.currentIndexChanged.connect(self.render_table)
        row.addWidget(self.table_picker, 1)
        self.table_location = text_label("", muted=True)
        row.addWidget(self.table_location)
        table_layout.addWidget(picker_row)
        self.table = make_table([])
        self.table.setMinimumHeight(320)
        table_layout.addWidget(self.table)
        self.tabs.addTab(table_page, "Таблицы")
        self.tabs.setMinimumHeight(400)
        self.layout.addWidget(self.tabs)
        exports, row = row_widget()
        self.view_source_button = QPushButton("Реквизиты источника")
        self.view_source_button.clicked.connect(self.view_source)
        self.export_source_button = QPushButton("Сохранить исходный файл")
        self.export_source_button.clicked.connect(self.export_source)
        row.addStretch()
        row.addWidget(self.view_source_button)
        row.addWidget(self.export_source_button)
        self.export_row = exports
        self.layout.addWidget(exports)
        self.preview_note = text_label(
            "Предпросмотр сохраняет только реквизиты источника и не меняет записи анализа функций. "
            "PDF остаётся текстовым предпросмотром; OCR не выполняется.",
            muted=True,
        )
        self.layout.addWidget(self.preview_note)
        self.set_result_visible(False)

    def set_result_visible(self, visible):
        for widget in (self.info_frame, self.tabs, self.export_row, self.preview_note):
            widget.setVisible(visible)

    def update_ready(self):
        ready = bool(self.file_path.text() and self.confirmed.isChecked())
        self.parse_button.setEnabled(ready)
        self.parse_button.setToolTip("" if ready else "Выберите файл и подтвердите его синтетический характер")
        self.ready_hint.setVisible(not ready)

    def choose_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Выбрать синтетический документ",
            "",
            "Документы (*.docx *.xlsx *.csv *.pdf)",
        )
        if path:
            self.file_path.setText(path)
            self.parsed = None
            self.document_empty.setVisible(True)
            self.set_result_visible(False)
            self.error_label.setText("")
            self.update_ready()

    def parse(self):
        if not self.file_path.text() or not self.confirmed.isChecked():
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.parsed = parse_document(Path(self.file_path.text()))
            log(
                "Загружен документ",
                "source",
                self.parsed.source.id,
                {"format": self.parsed.format, "fragments": len(self.parsed.fragments), "tables": len(self.parsed.tables)},
            )
            self.error_label.setText("")
            self.render_result()
        except (ValueError, OSError) as exc:
            self.parsed = None
            self.document_empty.setVisible(True)
            self.set_result_visible(False)
            self.error_label.setStyleSheet("color: #a34441;")
            self.error_label.setText(str(exc))
        finally:
            QApplication.restoreOverrideCursor()

    def render_result(self):
        parsed = self.parsed
        self.document_empty.setVisible(False)
        self.error_label.setStyleSheet("")
        self.metadata.setText(
            f"{parsed.source.title} · {parsed.format.upper()} · {parsed.source.id}\n"
            f"SHA-256: {parsed.source.sha256}\n"
            f"Фрагментов: {len(parsed.fragments)} · Таблиц: {len(parsed.tables)}"
        )
        self.warnings.setText("\n".join(f"• {warning}" for warning in parsed.warnings))
        self.fragments.setPlainText(
            "\n\n".join(f"{fragment.locator}\n{fragment.text}" for fragment in parsed.fragments)
            or "Текстовые фрагменты не обнаружены. Для сканов OCR на этом этапе не выполняется."
        )
        self.table_picker.blockSignals(True)
        self.table_picker.clear()
        for index, table in enumerate(parsed.tables):
            self.table_picker.addItem(f"{table.name} · строк: {len(table.rows)}", index)
        self.table_picker.blockSignals(False)
        self.render_table()
        self.set_result_visible(True)

    def render_table(self):
        if not self.parsed or self.table_picker.currentData() is None:
            self.table.setRowCount(0)
            self.table.setColumnCount(0)
            self.table_location.setText("Таблицы не обнаружены")
            return
        table = self.parsed.tables[self.table_picker.currentData()]
        rows = table.rows[:PREVIEW_ROWS]
        columns = max((len(row.values) for row in rows), default=0)
        self.table.setRowCount(len(rows))
        self.table.setColumnCount(columns)
        self.table.setHorizontalHeaderLabels([f"Колонка {index}" for index in range(1, columns + 1)])
        for row_index, row in enumerate(rows):
            for column, value in enumerate(row.values):
                self.table.setItem(row_index, column, QTableWidgetItem(value))
            self.table.setVerticalHeaderItem(row_index, QTableWidgetItem(row.locator))
        self.table_location.setText(f"{table.locator} · показано {len(rows)} из {len(table.rows)} строк")
        self.table.resizeColumnsToContents()

    def view_source(self):
        if self.parsed:
            show_source(self, self.parsed.source)

    def export_source(self):
        if self.parsed:
            save_registered_source(self, self.parsed.source)
