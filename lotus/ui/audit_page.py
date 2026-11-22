import csv
import io
from datetime import datetime, timedelta, timezone

from PySide6.QtCore import QDate, Qt, QTimer
from PySide6.QtWidgets import (
    QDateEdit,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidgetItem,
    QVBoxLayout,
)

from lotus.audit import log, read_log
from lotus.ui.common import PageCombo, ScrollPage, add_heading, framed, make_table, row_widget, save_bytes, section_heading


class AuditPage(ScrollPage):
    def __init__(self):
        super().__init__()
        self.rows = []
        add_heading(self.layout, "РАБОЧЕЕ ПРОСТРАНСТВО / КОНТРОЛЬ", "Журнал действий", "История переходов, анализа дел и формирования документов")

        filters_card, filters_layout = framed(self.layout)
        filters_layout.setContentsMargins(14, 12, 14, 12)
        filters_layout.addWidget(self._section_title("Фильтры"))

        filters, row = row_widget()
        self.action_filter = PageCombo()
        self.object_filter = QLineEdit()
        self.object_filter.setPlaceholderText("Дело или объект")
        self.object_filter.setClearButtonEnabled(True)
        self.start_date = QDateEdit()
        self.start_date.setCalendarPopup(True)
        self.start_date.setDisplayFormat("dd.MM.yyyy")
        self.end_date = QDateEdit()
        self.end_date.setCalendarPopup(True)
        self.end_date.setDisplayFormat("dd.MM.yyyy")
        row.addLayout(self._field("Действие", self.action_filter), 2)
        row.addLayout(self._field("Объект", self.object_filter), 2)
        row.addLayout(self._field("Период с", self.start_date), 1)
        row.addLayout(self._field("по", self.end_date), 1)
        filters_layout.addWidget(filters)

        export = QPushButton("Скачать журнал CSV")
        export.setObjectName("primary")
        export.clicked.connect(self.export_csv)
        self.count_label = QLabel()
        self.count_label.setObjectName("muted")
        controls, controls_row = row_widget()
        controls_row.addWidget(export)
        controls_row.addSpacing(14)
        controls_row.addWidget(self.count_label, 1, Qt.AlignmentFlag.AlignVCenter)
        controls_row.addStretch()
        filters_layout.addWidget(controls)

        table_card, table_layout = framed(self.layout)
        table_layout.addWidget(self._section_title("Записи журнала"))
        self.table = make_table(["Время", "Сотрудник", "Действие", "Тип объекта", "Объект", "Подробности"])
        self.table.setMinimumHeight(420)
        self.table.verticalHeader().setDefaultSectionSize(34)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(1, 110)
        self.table.setColumnWidth(2, 170)
        self.table.setColumnWidth(3, 110)
        self.table.setColumnWidth(4, 150)
        table_layout.addWidget(self.table)

        self._last_logged_query = ""
        self.search_log_timer = QTimer(self)
        self.search_log_timer.setSingleShot(True)
        self.search_log_timer.setInterval(700)
        self.search_log_timer.timeout.connect(self._log_object_search)
        self.period_log_timer = QTimer(self)
        self.period_log_timer.setSingleShot(True)
        self.period_log_timer.setInterval(700)
        self.period_log_timer.timeout.connect(self._log_period_change)

        self.layout.addStretch()
        self.action_filter.currentIndexChanged.connect(self._on_action_changed)
        self.object_filter.textChanged.connect(self._on_object_changed)
        self.start_date.dateChanged.connect(self._on_period_changed)
        self.end_date.dateChanged.connect(self._on_period_changed)
        self.refresh()

    @staticmethod
    def _section_title(text):
        return section_heading(text)

    @staticmethod
    def _field(caption, widget):
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        caption_label = QLabel(caption)
        caption_label.setObjectName("muted")
        caption_label.setStyleSheet("font-size: 8pt;")
        layout.addWidget(caption_label)
        layout.addWidget(widget)
        return layout

    def refresh(self):
        self.rows = read_log()
        selected = self.action_filter.currentText()
        self.action_filter.blockSignals(True)
        self.action_filter.clear()
        self.action_filter.addItem("Все")
        self.action_filter.addItems(sorted({row["action"] for row in self.rows}))
        index = self.action_filter.findText(selected)
        self.action_filter.setCurrentIndex(max(0, index))
        self.action_filter.blockSignals(False)
        if self.rows:
            times = [self.moscow_time(row["ts"]) for row in self.rows]
            self.set_date_range(self.start_date, min(times).date())
            self.set_date_range(self.end_date, max(times).date())
        self.apply_filters()

    @staticmethod
    def moscow_time(value):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone(timedelta(hours=3)))

    @staticmethod
    def set_date_range(widget, value):
        widget.blockSignals(True)
        widget.setDate(QDate(value.year, value.month, value.day))
        widget.blockSignals(False)

    def _on_action_changed(self):
        self.apply_filters()
        log("Изменён фильтр действия", "audit", "filters", {"action": self.action_filter.currentText()})

    def _on_object_changed(self):
        self.apply_filters()
        self.search_log_timer.start()

    def _on_period_changed(self):
        self.apply_filters()
        self.period_log_timer.start()

    def _log_object_search(self):
        query = self.object_filter.text().strip()
        if query and query != self._last_logged_query:
            self._last_logged_query = query
            log("Задан поиск объекта", "audit", "filters", {"query": query})

    def _log_period_change(self):
        log("Изменён период журнала", "audit", "filters", {
            "start": self.start_date.date().toString("yyyy-MM-dd"),
            "end": self.end_date.date().toString("yyyy-MM-dd"),
        })

    def filtered_rows(self):
        query = self.object_filter.text().casefold()
        start = self.start_date.date().toPython()
        end = self.end_date.date().toPython()
        return [
            row for row in self.rows
            if (self.action_filter.currentText() == "Все" or row["action"] == self.action_filter.currentText())
            and query in row["object_id"].casefold()
            and start <= self.moscow_time(row["ts"]).date() <= end
        ]

    def apply_filters(self):
        rows = self.filtered_rows()
        self.count_label.setText(f"Записей: {len(rows)} · московское время, UTC+3")
        self.table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            values = [
                self.moscow_time(row["ts"]).strftime("%d.%m.%Y %H:%M:%S"),
                row["actor"], row["action"], row["object_type"], row["object_id"], row["details"],
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.table.setItem(index, column, item)

    def export_csv(self):
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["Время", "Сотрудник", "Действие", "Тип объекта", "Объект", "Подробности"])
        for row in self.filtered_rows():
            writer.writerow([self.moscow_time(row["ts"]).strftime("%d.%m.%Y %H:%M:%S"), row["actor"], row["action"], row["object_type"], row["object_id"], row["details"]])
        if save_bytes(self, "lotus_audit.csv", buffer.getvalue().encode("utf-8-sig"), "CSV (*.csv)"):
            log("Экспорт журнала", "audit", "all")
