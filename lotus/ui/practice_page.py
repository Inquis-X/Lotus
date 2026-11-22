import hashlib

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QFormLayout, QLineEdit, QListWidget, QListWidgetItem, QPushButton

from lotus.functions.practice import list_cases, list_links, save_link, remove_link
from lotus.functions.service import list_risks
from lotus.sources import read_source, source_local_path
from lotus.ui.common import PageCombo, ScrollPage, add_heading, framed, make_empty_state, set_message, text_label, show_source


class PracticePage(ScrollPage):
    documents_requested = Signal()

    def __init__(self):
        super().__init__()
        add_heading(self.layout, "ПРАКТИКА / УЧЕБНЫЕ МАТЕРИАЛЫ", "База практики",
                    "Демонстрационные примеры — не реальные судебные акты. Материалы требуют методической проверки.")
        self.empty_state = make_empty_state(
            self.layout, "Учебные примеры не добавлены",
            "В этом разделе хранятся синтетические разборы организационных условий и ограничения аналогий. "
            "Проверьте исходные материалы в документальном центре.",
            "Открыть документальный центр", self.documents_requested.emit)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск по функции, механизму или сфере…")
        self.search.textChanged.connect(self.filter_cases)
        self.layout.addWidget(self.search)
        self.cases_list = QListWidget()
        self.cases_list.setObjectName("practiceCasesList")
        self.cases_list.setMinimumHeight(124)
        self.cases_list.setMaximumHeight(176)
        self.cases_list.setSpacing(5)
        self.cases_list.setWordWrap(True)
        self.cases_list.setAlternatingRowColors(True)
        self.cases_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.cases_list.setStyleSheet("""
            QListWidget#practiceCasesList {
                color: #1c2b33; background: white; alternate-background-color: #f7f9fa;
                border: 1px solid #d5dfe5; border-radius: 8px; padding: 6px; outline: 0;
                selection-color: #1c2b33; selection-background-color: #d9ebff;
            }
            QListWidget#practiceCasesList::item {
                color: #1c2b33; background: white; border: 1px solid #dfe6ea;
                border-radius: 6px; padding: 9px 11px;
            }
            QListWidget#practiceCasesList::item:alternate {
                color: #1c2b33; background: #f7f9fa;
            }
            QListWidget#practiceCasesList::item:hover {
                color: #1c2b33; background: #edf5fb; border-color: #9fc4e3;
            }
            QListWidget#practiceCasesList::item:selected:active,
            QListWidget#practiceCasesList::item:selected:!active {
                color: #1c2b33; background: #d9ebff; border: 1px solid #1668b5;
            }
        """)
        self.cases_list.currentRowChanged.connect(self.show_case)
        self.layout.addWidget(self.cases_list)
        self.detail = text_label("")
        self.detail.setTextFormat(Qt.TextFormat.PlainText)
        self.layout.addWidget(self.detail)
        self.source_button = QPushButton("Сведения об учебном источнике")
        self.source_button.clicked.connect(self.open_source)
        self.layout.addWidget(self.source_button)
        _, box = framed(self.layout)
        box.addWidget(text_label("Связь с записью реестра · Статус риска не меняется автоматически"))
        form = QFormLayout()
        self.risk = PageCombo()
        self.risk.currentIndexChanged.connect(self.load_link)
        self.matching = QLineEdit()
        self.limitations = QLineEdit()
        self.rationale = QLineEdit()
        for field in (self.matching, self.limitations, self.rationale):
            field.textChanged.connect(self.update_actions)
        for title, widget in [("Запись реестра", self.risk), ("Что совпадает", self.matching),
                              ("Ограничения аналогии", self.limitations),
                              ("Обоснование связи или её удаления", self.rationale)]:
            form.addRow(title, widget)
        box.addLayout(form)
        self.link_state = text_label("")
        box.addWidget(self.link_state)
        self.save_button = QPushButton("Сохранить обоснованную связь")
        self.save_button.setObjectName("primary")
        self.save_button.clicked.connect(self.save)
        self.remove_button = QPushButton("Удалить связь с обоснованием")
        self.remove_button.clicked.connect(self.remove)
        box.addWidget(self.save_button)
        box.addWidget(self.remove_button)
        self.message = text_label("")
        self.layout.addWidget(self.message)
        self.refresh()

    def selected_case(self):
        row = self.cases_list.currentRow()
        return self.visible_cases[row] if 0 <= row < len(getattr(self, "visible_cases", [])) else None

    def refresh(self):
        selected_risk = self.risk.currentData()
        self.cases = list_cases()
        self.empty_state.setVisible(not self.cases)
        self.risk.blockSignals(True)
        self.risk.clear()
        self.risk.addItem("Выберите запись", None)
        for record in list_risks():
            # Keep rejected records visible to inspect or remove existing links.
            label = record.vulnerability + (" · отклонено" if record.status == "rejected" else "")
            self.risk.addItem(label, record.id)
        self.risk.setCurrentIndex(max(0, self.risk.findData(selected_risk)))
        self.risk.blockSignals(False)
        self.filter_cases()

    def filter_cases(self):
        current = self.selected_case()
        selected_id = current.id if current else None
        self.cases_list.blockSignals(True)
        self.cases_list.clear()
        query = self.search.text().strip().casefold()
        self.visible_cases = [case for case in self.cases
                              if query in f"{case.title} {case.function} {case.mechanism} {case.sphere}".casefold()]
        selected_row = 0
        for row, case in enumerate(self.visible_cases):
            item = QListWidgetItem(f"{case.code} · {case.title}\n{case.sphere} · {case.edition}")
            item.setForeground(QColor("#1c2b33"))
            item.setBackground(QColor("white" if row % 2 == 0 else "#f7f9fa"))
            item.setToolTip(f"{case.code} · {case.title}\n{case.function}\n{case.edition}\n{case.id}")
            self.cases_list.addItem(item)
            if case.id == selected_id:
                selected_row = row
        self.cases_list.setCurrentRow(selected_row if self.visible_cases else -1)
        self.cases_list.blockSignals(False)
        self.show_case()

    def show_case(self, *args):
        case = self.selected_case()
        self.source_button.setEnabled(case is not None)
        self.source_button.setToolTip("" if case else "Выберите учебный пример")
        if case:
            self.detail.setText(f"Демонстрационный пример · Не судебный акт\n{case.title}\n"
                                f"Сфера: {case.sphere}\nФункция: {case.function}\n"
                                f"Обстоятельства: {case.circumstances}\nМеханизм: {case.mechanism}\n"
                                f"Организационные условия: {case.conditions}\nКонтроли: {case.controls}\n"
                                f"Признаки в документах: {case.observable}\nОграничения: {case.limitations}\n"
                                f"{case.source_ref} · {case.coordinate} · {case.edition}")
        else:
            self.detail.setText("По запросу примеры не найдены")
        self.load_link()

    def load_link(self):
        for field in (self.matching, self.limitations, self.rationale):
            field.clear()
        case, risk_id = self.selected_case(), self.risk.currentData()
        link = next((link for link in list_links(risk_id=risk_id) if case and link.case_id == case.id), None) if risk_id else None
        self.current_link = link
        if link:
            self.matching.setText(link.matching_condition)
            self.limitations.setText(link.limitations)
            self.rationale.setText(link.rationale)
            self.link_state.setText(f"Связь обоснована: {link.actor} · {link.reviewed_at}")
        else:
            self.link_state.setText("Связь не сохранена")
        self.update_actions()

    def update_actions(self):
        case_ready = self.selected_case() is not None
        risk_ready = self.risk.currentData() is not None
        fields_ready = all(field.text().strip() for field in (self.matching, self.limitations, self.rationale))
        save_ready = case_ready and risk_ready and fields_ready
        self.save_button.setEnabled(save_ready)
        self.save_button.setToolTip(
            "" if save_ready else "Выберите пример и запись реестра; заполните совпадение, ограничения и обоснование")
        remove_ready = getattr(self, "current_link", None) is not None and bool(self.rationale.text().strip())
        self.remove_button.setEnabled(remove_ready)
        self.remove_button.setToolTip("" if remove_ready else "Выберите сохранённую связь и укажите обоснование её удаления")

    def save(self):
        case = self.selected_case()
        if not case:
            return
        try:
            save_link(case.id, self.risk.currentData(), self.matching.text(), self.limitations.text(), self.rationale.text())
        except ValueError as exc:
            set_message(self.message, str(exc), error=True)
            return
        self.load_link()
        set_message(self.message, "Связь сохранена. Статус риска не изменён.")

    def remove(self):
        case = self.selected_case()
        if not case:
            return
        try:
            remove_link(case.id, self.risk.currentData(), self.rationale.text())
        except ValueError as exc:
            set_message(self.message, str(exc), error=True)
            return
        self.load_link()
        set_message(self.message, "Связь удалена; причина сохранена в журнале.")

    def open_source(self):
        case = self.selected_case()
        if case:
            source = read_source(case.source_ref)
            file = source_local_path(source) if source else None
            if file is None or hashlib.sha256(file.read_bytes()).hexdigest() != source.sha256:
                set_message(self.message, "Исходный файл этой версии недоступен или изменён. Сохранённый текст и реквизиты показаны в карточке.", error=True)
                return
            show_source(self, source)
