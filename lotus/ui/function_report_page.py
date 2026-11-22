from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QListWidget, QListWidgetItem, QPushButton, QTextEdit

from lotus.audit import log
from lotus.ui.common import framed, section_heading
from lotus.functions.report import build_report, snapshot_preview
from lotus.functions.service import list_risks
from lotus.ui.common import ScrollPage, add_heading, make_empty_state, set_message, text_label, save_bytes


class FunctionReportPage(ScrollPage):
    risks_requested = Signal()

    def __init__(self):
        super().__init__()
        self.content_bytes = None
        self.snapshot = None
        add_heading(self.layout, "ОТЧЁТЫ / ПРОЕКТ", "Отчёты и меры",
                    "Проект карты коррупционных рисков по подтверждённым записям")
        self.empty_state = make_empty_state(
            self.layout, "Нет записей для проекта отчёта",
            "Сначала оцените находки в реестре. В проект включаются только подтверждённые актуальные записи с источниками.",
            "Открыть реестр рисков", self.risks_requested.emit)
        panels = QHBoxLayout()
        self.layout.addLayout(panels, 1)
        self.selection_panel, selection = framed()
        self.preview_panel, preview_layout = framed()
        panels.addWidget(self.selection_panel, 2)
        panels.addWidget(self.preview_panel, 3)
        selection.addWidget(section_heading("Записи для включения"))
        preview_layout.addWidget(section_heading("Предпросмотр карты рисков"))
        self.records = QListWidget()
        self.records.setWordWrap(True)
        self.records.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.records.setObjectName("reportRecords")
        self.records.setMinimumHeight(180)
        self.records.itemChanged.connect(self.invalidate)
        selection.addWidget(self.records, 1)
        self.generate_button = QPushButton("Сформировать проект отчёта")
        self.generate_button.setObjectName("primary")
        self.generate_button.clicked.connect(self.generate)
        selection.addWidget(self.generate_button)
        self.message = text_label("")
        self.layout.addWidget(self.message)
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setPlaceholderText("Отметьте записи слева и сформируйте проект.")
        self.preview.setMinimumHeight(260)
        preview_layout.addWidget(self.preview, 1)
        self.save_button = QPushButton("Сохранить проект DOCX")
        self.save_button.clicked.connect(self.save)
        self.save_button.setEnabled(False)
        preview_layout.addWidget(self.save_button)
        self.refresh()

    def selected_ids(self):
        return [self.records.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.records.count())
                if self.records.item(i).checkState() == Qt.CheckState.Checked]

    def invalidate(self):
        self.content_bytes = self.snapshot = None
        self.save_button.setEnabled(False)
        self.save_button.setToolTip("Сначала сформируйте проект отчёта для предпросмотра")
        self.preview.clear()
        selected = bool(self.selected_ids())
        self.generate_button.setEnabled(selected)
        self.generate_button.setToolTip("" if selected else "Выберите хотя бы одну подтверждённую запись")

    def refresh(self):
        selected = set(self.selected_ids())
        self.records.clear()
        for record in list_risks():
            if record.status != "confirmed" or record.needs_review:
                continue
            item = QListWidgetItem(record.vulnerability)
            item.setToolTip(record.id)
            item.setData(Qt.ItemDataRole.UserRole, record.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if record.id in selected else Qt.CheckState.Unchecked)
            self.records.addItem(item)
        self.invalidate()
        has_records = self.records.count() > 0
        self.selection_panel.setVisible(has_records)
        self.preview_panel.setVisible(has_records)
        self.empty_state.setVisible(not has_records)
        self.records.setVisible(has_records)
        self.generate_button.setVisible(has_records)
        self.preview.setVisible(has_records)
        self.save_button.setVisible(has_records)
        set_message(self.message, "Нет подтверждённых записей. Проверьте находки в реестре." if not has_records
                    else "После выбора записей сформируйте проект для предпросмотра.")

    def generate(self):
        self.invalidate()
        try:
            self.content_bytes, self.snapshot = build_report(self.selected_ids())
        except (ValueError, OSError) as exc:
            set_message(self.message, str(exc), error=True)
            return
        self.preview.setPlainText(snapshot_preview(self.snapshot))
        self.save_button.setEnabled(True)
        self.save_button.setToolTip("")
        set_message(self.message, "Проект сформирован. Предпросмотр показывает содержание, а не разметку страниц Word.")

    def save(self):
        # Rebuild to recheck decisions and sources, even if the preview is still open.
        self.generate()
        if self.content_bytes is None:
            return
        if save_bytes(self, "lotus_risk_map_draft.docx", self.content_bytes, "Документ Word (*.docx)"):
            log("Экспорт проекта карты рисков", "risk_map_draft", self.snapshot["created_at"],
                {"records": self.selected_ids(), "status": "draft"})
            set_message(self.message, "Проект сохранён. Утверждение документа выполняется отдельно.")
