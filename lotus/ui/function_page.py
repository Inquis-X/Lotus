from pathlib import Path
import sys

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QFileDialog, QFormLayout, QGridLayout, QLineEdit, QMessageBox,
                               QPushButton, QTableWidgetItem, QTextBrowser, QTextEdit, QDialog, QVBoxLayout, QHBoxLayout)

from lotus.documents import parse_document
from PySide6.QtWidgets import QHeaderView
from lotus.functions.service import (create_candidate, list_nodes, list_risks, review,
                                        edition_history, reset_review)
from lotus.functions.extraction import extract, save_extraction
from lotus.functions.detectors import run_rules
from lotus.ui.common import (PageCombo, ScrollPage, add_heading, framed, make_table,
                                section_heading, set_message, text_label)
from lotus.ui.steps import build_analysis_steps, confirmed_procedures, next_candidate

KINDS = {"function": "Функция", "procedure": "Процедура", "stage": "Этап",
         "role": "Должностная роль", "control": "Контрольная процедура"}
STATUSES = {"candidate": "Кандидат", "confirmed": "Подтверждено", "rejected": "Отклонено"}


class FunctionPage(ScrollPage):
    risks_requested = Signal()
    reports_requested = Signal()

    def __init__(self):
        super().__init__()
        self.document = None
        self.review_source = None
        self.checked_procedures = set()
        self.procedure_results = {}
        add_heading(self.layout, "ФУНКЦИИ / ПРОВЕРКА", "Анализ функций и процедур",
                    "Выделение функций и проверка формулировок. Все находки требуют решения специалиста.")
        self.steps_frame, steps_layout = framed(self.layout)
        steps_layout.addWidget(section_heading("Шаги анализа"))
        steps_layout.addWidget(text_label(
            "Нажмите на шаг, чтобы перейти к нужному блоку. Причина блокировки указана в подсказке.", muted=True))
        step_grid = QGridLayout()
        step_grid.setSpacing(7)
        self.step_buttons = []
        for index in range(6):
            button = QPushButton()
            button.setMinimumHeight(48)
            button.clicked.connect(lambda checked=False, position=index: self.scroll_to_step(position))
            step_grid.addWidget(button, index // 2, index % 2)
            self.step_buttons.append(button)
        steps_layout.addLayout(step_grid)
        self.message = text_label("")
        self.layout.addWidget(self.message)

        self.document_frame, document_layout = framed(self.layout)
        document_layout.addWidget(section_heading("1. Документ"))
        self.privacy_check = QCheckBox("Документ не содержит персональных данных и сведений о третьих лицах")
        self.privacy_check.toggled.connect(self.update_actions)
        document_layout.addWidget(self.privacy_check)
        self.load_button = QPushButton("Выбрать документ для выделения функций")
        self.load_button.setObjectName("primary")
        self.load_button.clicked.connect(self.load_document)
        document_layout.addWidget(self.load_button)
        self.source_label = text_label("Документ не выбран", muted=True)
        document_layout.addWidget(self.source_label)

        self.creation_frame, creation_layout = framed(self.layout)
        creation_layout.addWidget(section_heading("2. Записи из документа"))
        self.extract_button = QPushButton("Найти записи в DOCX")
        self.extract_button.setObjectName("primary")
        self.extract_button.clicked.connect(self.extract_document)
        fields = QFormLayout()
        self.edition = QLineEdit()
        self.edition.setPlaceholderText("Номер и дата редакции акта")
        self.edition.textChanged.connect(self.update_actions)
        self.fragment = PageCombo()
        self.fragment.currentIndexChanged.connect(self.show_fragment)
        self.fragment.currentIndexChanged.connect(self.update_actions)
        self.quote = QTextEdit()
        self.quote.setReadOnly(True)
        self.quote.setObjectName("quote")
        self.quote.setPlaceholderText("Выберите фрагмент документа")
        self.quote.setMaximumHeight(100)
        self.kind = PageCombo()
        for key, label in KINDS.items():
            self.kind.addItem(label, key)
        self.parent = PageCombo()
        self.parent.currentIndexChanged.connect(self.update_actions)
        self.kind.currentIndexChanged.connect(self.refresh_parents)
        self.title = QLineEdit()
        self.title.textChanged.connect(self.update_actions)
        self.department = QLineEdit()
        self.department.setPlaceholderText("Подразделение для функции; можно оставить неуказанным")
        fields.addRow("Редакция", self.edition)
        self.edition.setToolTip("Версия акта, которая будет указана в основании каждой записи.")
        creation_layout.addLayout(fields)
        creation_layout.addWidget(self.extract_button)
        creation_layout.addWidget(text_label(
            "Поиск откроет найденные записи для проверки. Для ручного ввода выберите абзац ниже.", muted=True))
        fields = QFormLayout()
        for label, widget, help_text in [
            ("Координата", self.fragment, "Выберите абзац исходного документа. Его адрес сохранится вместе с цитатой."),
            ("Цитата", self.quote, "Точный текст выбранного абзаца. Обновляется при смене координаты."),
            ("Тип", self.kind, "Выберите, что описывает цитата. Тип определяет допустимую связь с другими записями."),
            ("Родительская запись", self.parent, "Для процедуры выберите функцию, для этапа — процедуру, для роли или контроля — этап."),
            ("Название", self.title, "Введите краткое название для карты и списка проверки."),
            ("Подразделение функции", self.department, "Укажите управление или отдел из документа. Поле доступно для функции."),
        ]:
            fields.addRow(label, widget)
            widget.setToolTip(help_text)
            fields.labelForField(widget).setToolTip(help_text)
        creation_layout.addLayout(fields)
        self.create_button = QPushButton("Сохранить кандидата вручную")
        self.create_button.clicked.connect(self.create)
        creation_layout.addWidget(self.create_button)

        self.review_frame, review_layout = framed(self.layout)
        review_layout.addWidget(section_heading("3. Проверка записей и решения специалиста"))
        self.table = make_table(["Тип записи", "Название", "Статус"])
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 165)
        self.table.setColumnWidth(2, 120)
        self.table.setShowGrid(False)
        self.table.setMinimumHeight(220)
        self.table.itemSelectionChanged.connect(self.show_selection)
        review_layout.addWidget(self.table)
        self.evidence = text_label("Выберите запись для проверки")
        self.evidence.setTextFormat(Qt.TextFormat.PlainText)
        self.evidence.setObjectName("evidence")
        review_layout.addWidget(self.evidence)
        self.rationale = QLineEdit()
        self.rationale.setPlaceholderText("Обязательное обоснование решения")
        self.rationale.textChanged.connect(self.update_actions)
        review_layout.addWidget(self.rationale)
        decisions = QHBoxLayout()
        self.confirm_button = QPushButton("Подтвердить")
        self.confirm_button.setObjectName("primary")
        self.reject_button = QPushButton("Отклонить")
        self.confirm_button.clicked.connect(lambda: self.decide("confirmed"))
        self.reject_button.clicked.connect(lambda: self.decide("rejected"))
        decisions.addWidget(self.confirm_button)
        decisions.addWidget(self.reject_button)
        review_layout.addLayout(decisions)
        self.reset_button = QPushButton("Сбросить проверку записей и решения специалиста")
        self.reset_button.setObjectName("resetReview")
        self.reset_button.clicked.connect(self.reset_records)
        review_layout.addWidget(self.reset_button)

        self.rules_frame, rules_layout = framed(self.layout)
        rules_layout.addWidget(section_heading("4. Формулировки и сигнал о рисках"))
        rules_layout.addWidget(text_label(
            "Проверяются только подтверждённые цитаты этапов: «в разумный срок» и «при необходимости»; "
            "учитываются формы слов и их перестановка. "
            "Совпадения поступают в реестр как кандидаты. Демонстрационные правила требуют калибровки.", muted=True))
        guide = QPushButton("Алгоритм проверки по Методике № 96")
        guide.clicked.connect(self.show_method)
        rules_layout.addWidget(guide)
        rule_actions = QHBoxLayout()
        self.rules_button = QPushButton("Проверить формулировки выбранной процедуры")
        self.rules_button.setObjectName("primary")
        self.rules_button.clicked.connect(self.check_phrases)
        self.signal_button = QPushButton("Сигнал: необработанных находок нет")
        self.signal_button.setObjectName("riskSignal")
        self.signal_button.clicked.connect(self.risks_requested.emit)
        rule_actions.addWidget(self.rules_button)
        rule_actions.addWidget(self.signal_button)
        rules_layout.addLayout(rule_actions)

        self.risks_frame, risks_layout = framed(self.layout)
        risks_layout.addWidget(section_heading("5. Оценка находок"))
        risks_layout.addWidget(text_label(
            "Проверьте контекст каждой находки и сохраните решение с обоснованием в реестре.", muted=True))
        self.risks_button = QPushButton("Открыть реестр рисков")
        self.risks_button.setObjectName("primary")
        self.risks_button.clicked.connect(self.risks_requested.emit)
        risks_layout.addWidget(self.risks_button)

        self.reports_frame, reports_layout = framed(self.layout)
        reports_layout.addWidget(section_heading("6. Проект отчёта"))
        reports_layout.addWidget(text_label(
            "После оценки находок выберите подтверждённые записи и сформируйте проект карты рисков.", muted=True))
        self.reports_button = QPushButton("Перейти в отчёты")
        self.reports_button.setObjectName("primary")
        self.reports_button.clicked.connect(self.reports_requested.emit)
        reports_layout.addWidget(self.reports_button)
        self.step_targets = [self.document_frame, self.creation_frame, self.review_frame,
                             self.rules_frame, self.risks_frame, self.reports_frame]
        self.layout.addStretch()
        self.refresh()

    @staticmethod
    def set_action_state(button, enabled, reason):
        button.setEnabled(enabled)
        button.setToolTip("" if enabled else reason)

    def scroll_to_step(self, index):
        self.ensureWidgetVisible(self.step_targets[index])

    def update_steps(self):
        nodes = getattr(self, "nodes", [])
        stage_ids = {node.id for node in nodes if node.kind == "stage"}
        risks = [risk for risk in list_risks() if risk.stage_id in stage_ids]
        steps = build_analysis_steps(
            nodes, risks, document_selected=self.document is not None and self.privacy_check.isChecked(),
            checked_procedures=self.checked_procedures)
        palettes = {
            "готов": ("#e8f3ed", "#75a58e", "#245840"),
            "текущий": ("#e6f2ff", "#1668b5", "#124f86"),
            "заблокирован": ("#eef1f3", "#dde4e8", "#657985"),
        }
        for index, (button, step) in enumerate(zip(self.step_buttons, steps), start=1):
            detail = step["detail"]
            short_detail = detail if len(detail) <= 52 else detail[:49] + "…"
            button.setText(f"{index}. {step['title']} · {step['state']}" + (f"\n{short_detail}" if short_detail else ""))
            tooltip = step["description"]
            if detail:
                tooltip += f"\n{detail}"
            if step["reason"]:
                tooltip += f"\nПричина: {step['reason']}"
            button.setToolTip(tooltip)
            background, border, foreground = palettes[step["state"]]
            button.setStyleSheet(
                f"QPushButton {{ text-align: left; color: {foreground}; background: {background}; "
                f"border: 1px solid {border}; border-radius: 7px; padding: 6px 10px; }}"
            )

    def next_step_message(self):
        candidate = next_candidate(self.nodes)
        if candidate:
            return f"Что дальше: подтвердите {KINDS[candidate.kind].lower()} «{candidate.title}» с обоснованием."
        if confirmed_procedures(self.nodes):
            return "Что дальше: выберите подтверждённую процедуру и проверьте формулировки."
        return "Что дальше: проверьте записи в иерархическом порядке и укажите обоснование решений."

    def check_phrases(self):
        node = self.selected_node()
        if node is None or node.kind != "procedure":
            set_message(self.message, "Выберите процедуру в таблице", error=True)
            return
        try:
            result = run_rules(node.id)
        except (ValueError, OSError) as exc:
            set_message(self.message, str(exc), error=True)
            return
        self.checked_procedures.add(node.id)
        self.procedure_results[node.id] = result["matched"]
        if result["matched"]:
            set_message(self.message, f"Проверено этапов: {result['stages']}. Совпадений правил: {result['matched']}. "
                                      f"Новых кандидатов в реестре: {result['created']}. "
                                      "Перейдите в «Реестр рисков» и оцените каждую находку с обоснованием.")
        else:
            set_message(self.message, f"Проверено этапов: {result['stages']}. Рисков не найдено. "
                                      "Ноль совпадений не означает отсутствия рисков: проверьте контекст вручную.")
        self.update_actions()

    def show_method(self):
        from lotus.settings import ROOT
        dialog = QDialog(self)
        dialog.setWindowTitle("Алгоритм проверки коррупциогенных факторов")
        dialog.resize(820, 600)
        layout = QVBoxLayout(dialog)
        guide = QTextBrowser()
        guide.setOpenExternalLinks(True)
        guide.setMarkdown((ROOT / "docs/analysis_method.md").read_text(encoding="utf-8"))
        layout.addWidget(guide)
        close = QPushButton("Закрыть")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        dialog.exec()

    def load_document(self):
        if not self.privacy_check.isChecked():
            return
        from lotus.settings import ROOT
        base = Path(sys.executable).parent if getattr(sys, "frozen", False) else ROOT
        examples = base / "data/gold/functions"
        path, _ = QFileDialog.getOpenFileName(self, "Документ для анализа",
                                              str(examples) if examples.is_dir() else "",
                                              "Документы (*.docx *.xlsx *.csv *.pdf)")
        if not path:
            return
        try:
            document = parse_document(path)
        except (ValueError, OSError) as exc:
            set_message(self.message, str(exc), error=True)
            return
        self.document = document
        self.review_source = document.source.id
        self.checked_procedures.clear()
        self.procedure_results.clear()
        self.edition.clear()
        self.fragment.clear()
        self.source_label.setText(f"{document.source.title} · SHA-256: {document.source.sha256}")
        for fragment in document.fragments:
            self.fragment.addItem(fragment.locator, fragment.text)
        set_message(self.message, "Выберите фрагмент и укажите редакцию. " + " ".join(document.warnings))
        self.refresh()

    def show_fragment(self):
        self.quote.setPlainText(self.fragment.currentData() or "")

    def refresh_parents(self):
        self.parent.clear()
        expected = {"procedure": "function", "stage": "procedure", "role": "stage", "control": "stage"}.get(self.kind.currentData())
        self.parent.setEnabled(expected is not None)
        self.department.setEnabled(self.kind.currentData() == "function")
        self.parent.addItem("Выберите запись" if expected else "Не требуется", None)
        for node in list_nodes():
            if node.kind == expected and node.status != "rejected":
                self.parent.addItem(node.title, node.id)

    def create(self):
        if self.document is None or not self.privacy_check.isChecked():
            set_message(self.message, "Выберите документ", error=True)
            return
        self.review_source = self.document.source.id
        try:
            create_candidate(kind=self.kind.currentData(), title=self.title.text(),
                             parent_id=self.parent.currentData(), source_ref=self.document.source.id,
                             coordinate=self.fragment.currentText(), edition=self.edition.text(),
                             quote=self.quote.toPlainText(), department=self.department.text())
        except (ValueError, OSError) as exc:
            set_message(self.message, str(exc), error=True)
            return
        self.refresh()
        candidate = next_candidate(self.nodes)
        if candidate:
            self.refresh(candidate.id)
        set_message(self.message, self.next_step_message())

    def extract_document(self):
        if self.document is None or not self.privacy_check.isChecked():
            set_message(self.message, "Сначала выберите документ", error=True)
            return
        self.review_source = self.document.source.id
        try:
            batch = extract(self.document, self.edition.text())
        except (ValueError, OSError) as exc:
            set_message(self.message, str(exc), error=True)
            return
        if not batch.candidates:
            set_message(self.message, "Записи не распознаны. Выберите абзац и сохраните запись вручную.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Предпросмотр кандидатов из документа")
        dialog.resize(950, 550)
        layout = QVBoxLayout(dialog)
        layout.addWidget(text_label(f"Найдено кандидатов: {len(batch.candidates)}. Пропущено строк: {batch.ignored_lines}. "
                                    "Сохранение не подтверждает сведения: после него проверьте каждую запись с обоснованием."))
        table = make_table(["Тип", "Название", "Родитель", "Координата", "Цитата"])
        by_id = {node.id: node for node in batch.candidates}
        for node in batch.candidates:
            row = table.rowCount()
            table.insertRow(row)
            values = [KINDS[node.kind], node.title, by_id[node.parent_id].title if node.parent_id else "—",
                      node.coordinate, node.quote]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                table.setItem(row, column, item)
        layout.addWidget(table)
        details = QTextEdit()
        details.setReadOnly(True)
        details.setMaximumHeight(140)
        table.itemSelectionChanged.connect(lambda: details.setPlainText(
            batch.candidates[table.currentRow()].quote if table.currentRow() >= 0 else ""))
        layout.addWidget(details)
        message = text_label("")
        layout.addWidget(message)
        save = QPushButton("Сохранить кандидатов для проверки")
        save.setObjectName("saveExtraction")
        layout.addWidget(save)

        def commit():
            try:
                count = save_extraction(batch)
            except (ValueError, OSError) as exc:
                set_message(message, str(exc), error=True)
                return
            set_message(self.message, f"Добавлено кандидатов: {count}. Существующие записи и решения сохранены.")
            dialog.accept()

        save.clicked.connect(commit)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh()
            candidate = next_candidate(self.nodes)
            if candidate:
                self.refresh(candidate.id)
            set_message(self.message, self.next_step_message())

    def refresh(self, selected_id=None):
        all_nodes = list_nodes()
        if selected_id is not None:
            target = next((node for node in all_nodes if node.id == selected_id), None)
            if target is not None and target.source_ref != self.review_source:
                self.review_source = target.source_ref
        previous = self.selected_node() if hasattr(self, "nodes") else None
        selected_id = selected_id or (previous.id if previous else None)
        self.nodes = [node for node in all_nodes
                      if self.review_source is not None and node.source_ref == self.review_source]
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for node in self.nodes:
            row = self.table.rowCount()
            self.table.insertRow(row)
            for col, value in enumerate([KINDS[node.kind], node.title, STATUSES[node.status]]):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.table.setItem(row, col, item)
        self.table.blockSignals(False)
        self.refresh_parents()
        selected_row = next((row for row, node in enumerate(self.nodes) if node.id == selected_id), -1)
        if selected_row >= 0:
            self.table.selectRow(selected_row)
        else:
            self.table.clearSelection()
            self.table.setCurrentCell(-1, -1)
            self.show_selection()
        self.update_actions()

    def selected_node(self):
        row = self.table.currentRow()
        return self.nodes[row] if 0 <= row < len(self.nodes) else None

    def show_selection(self):
        node = self.selected_node()
        if node:
            history = edition_history(node.id) if node.kind == "stage" else []
            self.evidence.setText(f"{node.source_ref} · {node.coordinate} · редакция {node.edition}\n"
                                  f"Происхождение: {'автоматически' if node.origin == 'auto' else 'вручную'}\n"
                                  f"{node.quote}\nРешение: {node.rationale or 'Ещё не принято'}\n"
                                  + "\n".join(f"Изменение {h['created_at']}: {h['rationale']}\n"
                                              f"Прежняя редакция {h['before']['edition']}: {h['before']['quote']}\n"
                                              f"Новая редакция {h['after']['edition']}: {h['after']['quote']}"
                                              for h in history))
        else:
            self.evidence.setText("Выберите запись для проверки")
        self.rationale.clear()
        self.update_actions()

    def update_actions(self):
        if not hasattr(self, "reports_button"):
            return
        self.set_action_state(self.load_button, self.privacy_check.isChecked(), "Подтвердите отсутствие персональных данных")
        document_ready = self.document is not None and self.privacy_check.isChecked()
        edition_ready = bool(self.edition.text().strip())
        node = self.selected_node() if hasattr(self, "nodes") else None
        rationale_ready = bool(self.rationale.text().strip())
        parent_required = self.kind.currentData() != "function"
        parent_ready = not parent_required or self.parent.currentData() is not None
        manual_ready = (document_ready and edition_ready and bool(self.title.text().strip())
                        and self.fragment.currentData() is not None and parent_ready)
        decision_reason = ("Выберите запись в таблице" if node is None else
                           "Заполните обоснование решения" if not rationale_ready else "")
        self.set_action_state(self.extract_button, document_ready and edition_ready,
                              "Выберите документ, укажите редакцию")
        self.set_action_state(self.create_button, manual_ready,
                              "Заполните документ, редакцию, фрагмент, название и родительскую запись, если она требуется")
        for button in (self.confirm_button, self.reject_button):
            self.set_action_state(button, node is not None and rationale_ready, decision_reason)
        self.set_action_state(self.reset_button, bool(getattr(self, "nodes", [])),
                              "Список проверки пуст: выберите документ и сохраните записи")
        complete_ids = {procedure.id for procedure in confirmed_procedures(getattr(self, "nodes", []))}
        rules_ready = node is not None and node.id in complete_ids
        rules_reason = ("Выберите процедуру в таблице" if node is None or node.kind != "procedure" else
                        "Сначала подтвердите функцию, процедуру, этапы, роли и контроли")
        if rules_ready and self.procedure_results.get(node.id) == 0:
            rules_ready = False
            rules_reason = "Проверка выполнена: рисков не найдено"
        self.set_action_state(self.rules_button, rules_ready, rules_reason)
        stage_ids = {item.id for item in getattr(self, "nodes", []) if item.kind == "stage"}
        pending = [risk for risk in list_risks()
                   if risk.stage_id in stage_ids and (risk.status == "candidate" or risk.needs_review)]
        if pending:
            self.signal_button.setEnabled(True)
            self.signal_button.setToolTip("Открыть реестр рисков и оценить находки с обоснованием")
            self.signal_button.setText(f"Внимание: находок требует оценки: {len(pending)} — перейти в реестр рисков")
            self.signal_button.setStyleSheet(
                "QPushButton { color: #ffffff; background: #915000; border: 1px solid #7a4400; "
                "border-radius: 7px; padding: 6px 10px; font-weight: bold; }")
        else:
            self.signal_button.setEnabled(False)
            self.signal_button.setToolTip("Необработанных находок по записям выбранного документа нет")
            self.signal_button.setText("Сигнал: необработанных находок нет")
            self.signal_button.setStyleSheet("")
        self.update_steps()

    def reset_records(self):
        if self.review_source is None or not getattr(self, "nodes", []):
            return
        answer = QMessageBox.question(
            self, "Сброс проверки записей",
            "Удалить записи выбранного документа вместе с решениями специалиста? "
            "Связанные находки реестра и аналогии из базы практики будут удалены. "
            "Действие записывается в журнал.")
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            result = reset_review(self.review_source)
        except (ValueError, OSError) as exc:
            set_message(self.message, str(exc), error=True)
            return
        self.checked_procedures.clear()
        self.procedure_results.clear()
        self.refresh()
        set_message(self.message, f"Проверка сброшена: удалено записей {result['nodes']}, "
                                  f"находок {result['risks']}. Повторите извлечение из документа.")

    def decide(self, decision):
        node = self.selected_node()
        if node is None:
            return
        try:
            review(node.id, decision, self.rationale.text())
        except (ValueError, OSError) as exc:
            set_message(self.message, str(exc), error=True)
            return
        self.refresh()
        candidate = next_candidate(self.nodes)
        self.refresh(candidate.id if candidate else node.id)
        set_message(self.message, self.next_step_message())
