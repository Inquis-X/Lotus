from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QDialog, QFormLayout, QHBoxLayout, QHeaderView, QLineEdit,
                               QPushButton, QScrollArea, QSizePolicy, QTableWidgetItem, QVBoxLayout, QFrame)
from lotus.ui.common import FilterButton

from lotus.functions.service import create_risk, list_nodes, list_risks, review_risk
from lotus.sources import read_source
from lotus.ui.common import PageCombo, ScrollPage, add_heading, framed, make_empty_state, make_table, set_message, text_label, show_source
from lotus.ui.function_page import STATUSES
from lotus.functions.practice import list_links


class RiskRegistryPage(QFrame):
    analysis_requested = Signal()

    def __init__(self):
        super().__init__()
        self.setStyleSheet("QFrame#registryPage { background: #f4f6f8; }")
        self.setObjectName("registryPage")
        self.layout = QVBoxLayout(self)
        self.layout.setSpacing(6)
        self.layout.setContentsMargins(16, 10, 16, 10)
        title_row = QHBoxLayout()
        title = text_label("Реестр коррупционных рисков")
        title.setObjectName("title")
        title_row.addWidget(title, 1)
        self.new_button = QPushButton("Добавить запись")
        title_row.addWidget(self.new_button)
        self.layout.addLayout(title_row)
        self.summary = text_label("")
        self.layout.addWidget(self.summary)
        self.empty_state = make_empty_state(
            self.layout, "В реестре пока нет находок",
            "Здесь появятся автоматические совпадения и записи, созданные вручную. "
            "Сначала подтвердите процедуру и проверьте формулировки в анализе функций.",
            "Открыть анализ функций", self.analysis_requested.emit)
        self.editor = QDialog(self)
        self.editor.setWindowTitle("Новая запись реестра")
        self.editor.resize(660, 380)
        body = QVBoxLayout(self.editor)
        self.new_button.clicked.connect(self.editor.open)
        form = QFormLayout()
        self.stage = PageCombo()
        self.stage.currentIndexChanged.connect(self.update_controls)
        self.control = PageCombo()
        for combo in (self.control, self.stage):
            combo.setSizeAdjustPolicy(combo.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(18)
        self.vulnerability = QLineEdit()
        self.limitation = QLineEdit()
        self.measure = QLineEdit()
        for field in (self.vulnerability, self.limitation, self.measure):
            field.textChanged.connect(self.update_actions)
        self.basis = text_label("Выберите подтверждённый этап")
        for label, widget in [("Подтверждённый этап", self.stage), ("Действующий контроль", self.control),
                              ("Потенциальная уязвимость", self.vulnerability),
                              ("Ограничение контроля / данных", self.limitation),
                              ("Предлагаемая мера", self.measure)]:
            form.addRow(label, widget)
        body.addLayout(form)
        body.addWidget(self.basis)
        self.create_button = QPushButton("Создать запись для проверки")
        self.create_button.setObjectName("primary")
        self.create_button.clicked.connect(self.create)
        body.addWidget(self.create_button)
        self.editor_message = text_label("")
        body.addWidget(self.editor_message)
        self.message = text_label("")
        self.layout.addWidget(self.message)
        filters = QHBoxLayout()
        self.layout.addLayout(filters)
        self.function_filter = FilterButton("Функция")
        self.function_filter.addItem("Все функции", None)
        self.function_filter.currentIndexChanged.connect(self.refresh_table)
        filters.addWidget(self.function_filter, 1)
        self.filter = FilterButton("Статус")
        self.filter.addItem("Все статусы", None)
        for status, title in STATUSES.items():
            self.filter.addItem(title, status)
        self.filter.addItem("Требует актуализации", "needs_review")
        self.filter.currentIndexChanged.connect(self.refresh_table)
        filters.addWidget(self.filter, 1)
        self.origin_filter = FilterButton("Источник записи")
        self.origin_filter.addItem("Любое происхождение", None)
        self.origin_filter.addItem("Найдено автоматически", "auto")
        self.origin_filter.addItem("Внесено вручную", "manual")
        self.origin_filter.currentIndexChanged.connect(self.refresh_table)
        filters.addWidget(self.origin_filter, 1)
        self.table = make_table(["Код", "Функция / этап", "Уязвимость", "Статус", "Происхождение"])
        self.table.setMinimumHeight(110)
        self.table.horizontalHeader().setStretchLastSection(False)
        for column in (1, 2):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self.show_selection)
        self.layout.addWidget(self.table, 2)
        self.detail = text_label("Выберите запись")
        self.detail.setTextFormat(Qt.TextFormat.PlainText)
        self.detail.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.detail.setObjectName("evidence")
        self.detail.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.details = QScrollArea()
        self.details.setWidgetResizable(True)
        self.details.setMinimumHeight(95)
        self.details.setWidget(self.detail)
        self.layout.addWidget(self.details, 2)
        self.source_button = QPushButton("Источник")
        self.source_button.clicked.connect(self.open_source)
        self.rationale = QLineEdit()
        self.rationale.setPlaceholderText("Обоснование подтверждения или отклонения")
        self.rationale.textChanged.connect(self.update_actions)
        self.layout.addWidget(self.rationale)
        self.confirm_button = QPushButton("Подтвердить")
        self.confirm_button.setObjectName("primary")
        self.reject_button = QPushButton("Отклонить")
        self.confirm_button.clicked.connect(lambda: self.decide("confirmed"))
        self.reject_button.clicked.connect(lambda: self.decide("rejected"))
        actions = QHBoxLayout()
        actions.addWidget(self.source_button)
        actions.addStretch()
        actions.addWidget(self.reject_button)
        actions.addWidget(self.confirm_button)
        self.layout.addLayout(actions)
        self.refresh()

    def refresh(self):
        selected_stage = self.stage.currentData()
        selected_function = self.function_filter.currentData()
        self.nodes = {node.id: node for node in list_nodes()}
        self.function_filter.blockSignals(True)
        self.function_filter.clear()
        self.function_filter.addItem("Все функции", None)
        for node in self.nodes.values():
            if node.kind == "function":
                self.function_filter.addItem(node.title, node.id)
        self.function_filter.setCurrentIndex(max(0, self.function_filter.findData(selected_function)))
        self.function_filter.blockSignals(False)
        self.stage.clear()
        self.stage.addItem("Выберите этап", None)
        for node in self.nodes.values():
            if node.kind == "stage" and node.status == "confirmed":
                self.stage.addItem(self.stage_title(node.id), node.id)
        index = self.stage.findData(selected_stage)
        self.stage.setCurrentIndex(max(0, index))
        self.refresh_table()

    def stage_title(self, stage_id):
        stage = self.nodes[stage_id]
        procedure = self.nodes[stage.parent_id]
        function = self.nodes[procedure.parent_id]
        return f"{function.title} / {procedure.title} / {stage.title}"

    def update_controls(self):
        self.control.clear()
        self.control.addItem("Не установлен по представленным данным", None)
        stage_id = self.stage.currentData()
        for node in getattr(self, "nodes", {}).values():
            if node.kind == "control" and node.parent_id == stage_id and node.status == "confirmed":
                self.control.addItem(node.title, node.id)
        if stage_id:
            stage = self.nodes[stage_id]
            self.basis.setText(f"Основание этапа: {stage.coordinate} · редакция {stage.edition}\n{stage.quote}")
        else:
            self.basis.setText("Сначала подтвердите функцию, процедуру и этап в разделе анализа функций")
        self.update_actions()

    def create(self):
        try:
            record = create_risk(stage_id=self.stage.currentData(), control_id=self.control.currentData(),
                                 vulnerability=self.vulnerability.text(), control_limitation=self.limitation.text(),
                                 proposed_measure=self.measure.text())
        except (ValueError, OSError) as exc:
            set_message(self.editor_message, str(exc), error=True)
            return
        self.editor.accept()
        self.editor_message.clear()
        self.function_filter.setCurrentIndex(0)
        self.filter.setCurrentIndex(0)
        self.origin_filter.setCurrentIndex(0)
        self.refresh_table()
        for row, candidate in enumerate(self.records):
            if candidate.id == record.id:
                self.table.selectRow(row)
        set_message(self.message, "Запись создана вручную. Проверьте вывод и сохраните решение с обоснованием.")

    def refresh_table(self):
        all_records = list_risks()
        self.empty_state.setVisible(not all_records)
        for widget in (self.details, self.table, self.source_button, self.rationale,
                       self.confirm_button, self.reject_button):
            widget.setVisible(bool(all_records))
        self.summary.setText(f"Всего: {len(all_records)} · Требуют проверки: "
                             f"{sum(r.status == 'candidate' and not r.needs_review for r in all_records)} · Подтверждены: "
                             f"{sum(r.status == 'confirmed' and not r.needs_review for r in all_records)} · Отклонены: "
                             f"{sum(r.status == 'rejected' for r in all_records)} · Требуют актуализации: "
                             f"{sum(r.needs_review for r in all_records)}")
        self.table.clearSelection()
        self.table.setRowCount(0)
        function_id = self.function_filter.currentData()
        self.records = [r for r in all_records if self.filter.currentData() in (None, "needs_review" if r.needs_review else r.status)
                        and self.origin_filter.currentData() in (None, r.origin)
                        and (function_id is None or self.nodes[self.nodes[r.stage_id].parent_id].parent_id == function_id)]
        for row, record in enumerate(self.records):
            self.table.insertRow(row)
            values = [record.id, self.stage_title(record.stage_id), record.vulnerability,
                      "Требует актуализации" if record.needs_review else STATUSES[record.status],
                      "Автоматически" if record.origin == "auto" else "Вручную"]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.table.setItem(row, col, item)
        self.table.setColumnWidth(0, 80)
        self.table.setColumnWidth(3, 128)
        self.table.setColumnWidth(4, 118)
        if self.records:
            self.table.selectRow(0)
        self.show_selection()

    def selected_record(self):
        row = self.table.currentRow()
        records = getattr(self, "records", [])
        return records[row] if 0 <= row < len(records) else None

    def show_selection(self):
        record = self.selected_record()
        if record:
            links = list_links(risk_id=record.id)
            control = self.nodes.get(record.control_id)
            control_text = (f"{control.title}\n{control.source_ref} · {control.coordinate} · "
                            f"редакция {control.edition}\n{control.quote}" if control else "Не установлен по представленным данным")
            origin = "Найдено автоматически" if record.origin == "auto" else "Внесено вручную"
            rule_text = ""
            if record.rule_evidence:
                rule = record.rule_evidence
                rule_text = (f"Правило: {rule.rule_id} · версия {rule.version} · порог {rule.min_occurrences}\n"
                             f"SHA-256 правил: {rule.config_sha256}\n"
                             + "\n".join(f"Совпадение: «{match.text}» · символы {match.start + 1}–{match.end}"
                                         for match in rule.matches)
                             + "\nДемонстрационный поиск формулировок; требуется проверка полного контекста.\n")
            self.detail.setText(f"{record.id} · {origin}\n{self.stage_title(record.stage_id)}\n" + rule_text
                                + ("Требует актуализации после изменения редакции. Ниже сохранены прежнее основание и решение.\n" if record.needs_review else "") +
                                f"Уязвимость: {record.vulnerability}\nКонтроль: {control_text}\n"
                                f"Ограничение: {record.control_limitation}\nМера: {record.proposed_measure}\n"
                                f"Основание этапа: {record.source_ref} · {record.coordinate} · редакция {record.edition}\n"
                                f"{record.quote}\nРешение: {record.rationale or 'Ещё не принято'}\n"
                                + "\n".join(f"Учебная аналогия {link.case_id}: {link.matching_condition}\n"
                                            f"Ограничения: {link.limitations}\nОбоснование: {link.rationale}"
                                            for link in links))
        else:
            self.detail.setText("Выберите запись. При отсутствии записей создайте основание по подтверждённому этапу.")
        self.rationale.clear()
        self.update_actions()

    def update_actions(self):
        selected = self.selected_record() is not None
        rationale_ready = bool(self.rationale.text().strip())
        decision_reason = ("Выберите запись реестра" if not selected else
                           "Заполните обоснование решения" if not rationale_ready else "")
        self.source_button.setEnabled(selected)
        self.source_button.setToolTip("" if selected else "Выберите запись реестра")
        for button in (self.confirm_button, self.reject_button):
            button.setEnabled(selected and rationale_ready)
            button.setToolTip(decision_reason)
        fields_ready = all(field.text().strip() for field in (self.vulnerability, self.limitation, self.measure))
        stage_ready = self.stage.currentData() is not None
        self.create_button.setEnabled(stage_ready and fields_ready)
        self.create_button.setToolTip(
            "" if stage_ready and fields_ready else
            "Выберите подтверждённый этап и заполните уязвимость, ограничение и предлагаемую меру")

    def open_source(self):
        record = self.selected_record()
        if record:
            show_source(self, read_source(record.source_ref))

    def decide(self, decision):
        record = self.selected_record()
        if not record:
            return
        try:
            review_risk(record.id, decision, self.rationale.text())
        except (ValueError, OSError) as exc:
            set_message(self.message, str(exc), error=True)
            return
        self.refresh_table()
        set_message(self.message, "Решение сохранено в журнале")
