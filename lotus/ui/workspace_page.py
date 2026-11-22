"""Shared empty states and the entry page for the function workspace."""
from PySide6.QtWidgets import QGridLayout, QLabel, QPushButton

from lotus.ui.common import ScrollPage, add_heading, framed, make_empty_state, text_label
from lotus.functions.overview import load_overview


class HomePage(ScrollPage):
    def __init__(self, open_section):
        super().__init__()
        add_heading(self.layout, "ЛОТОС / ОБЗОР", "Обзор состояния системы",
                    "Документы → функции → основания для проверки → проекты решений")
        self.summary = text_label("")
        self.layout.addWidget(self.summary)
        self.empty_state = make_empty_state(
            self.layout, "Рабочее пространство пока пусто",
            "Здесь появятся сведения о муниципальных функциях после разбора документа и проверки кандидатов.",
            "Открыть анализ функций", lambda: open_section(3))
        _, intro = framed(self.layout)
        intro.addWidget(text_label("Рабочее пространство муниципальных функций"))
        intro.addWidget(text_label(
            "Начните с документального центра. Загрузка, предпросмотр и реестр источников доступны. "
            "В разделе анализа функций можно выделить функцию, процедуру и этапы вручную или по шаблонам DOCX, "
            "затем подтвердить их с обоснованием.", muted=True))
        grid = QGridLayout()
        grid.setSpacing(16)
        entries = [
            ("01", "Документы и источники", "Загрузите документ и проверьте его содержимое и источник.", 2),
            ("02", "Функции и процедуры", "Извлечение по шаблонам DOCX, ручное выделение и проверка специалистом.", 3),
            ("03", "Основания для проверки", "Автоматические и ручные находки с цитатой, редакцией и решением специалиста.", 4),
            ("04", "Проекты документов", "Проект карты рисков в DOCX по подтверждённым записям с мерами и источниками.", 6),
        ]
        for index, (number, title, detail, section) in enumerate(entries):
            card, body = framed()
            label = QLabel(number)
            label.setObjectName("metricValue")
            body.addWidget(label)
            body.addWidget(text_label(title))
            body.addWidget(text_label(detail, muted=True))
            button = QPushButton("Открыть раздел")
            button.clicked.connect(lambda checked=False, target=section: open_section(target))
            body.addWidget(button)
            grid.addWidget(card, index // 2, index % 2)
        self.layout.addLayout(grid)
        _, footer = framed(self.layout)
        footer.addWidget(text_label("Статусы карты отражают проверку сохранённых сведений"))
        footer.addWidget(text_label(
            "Актуальность источников повторно проверяется при подтверждении записей и экспорте.", muted=True))
        self.layout.addStretch()
        self.refresh()

    def refresh(self):
        entries = [entry for entry in load_overview() if entry["status"] != "rejected"]
        departments = {entry["function"].department for entry in entries if entry["function"].department}
        self.empty_state.setVisible(not entries)
        self.summary.setText(f"Подразделений указано: {len(departments)} · Функций: {len(entries)} · "
                             f"Сведения проверены: {sum(e['status'] == 'reviewed' for e in entries)} · "
                             f"Функций с основаниями для внимания: {sum(e['status'] == 'attention' for e in entries)}")
