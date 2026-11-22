from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHBoxLayout, QInputDialog, QLabel, QMessageBox, QLineEdit, QPushButton, QTreeWidget, QTreeWidgetItem

from lotus.functions.overview import LABELS, load_overview
from lotus.sources import read_source
from lotus.functions.service import assign_department
from lotus.ui.common import ScrollPage, add_heading, framed, text_label, show_source
from lotus.ui.function_page import KINDS, STATUSES

COLORS = {"unreviewed": "#59697A", "reviewing": "#1668B5", "reviewed": "#28654F",
          "attention": "#915000", "rejected": "#59697A"}


class FunctionMapPage(ScrollPage):
    node_requested = Signal(str)
    risks_requested = Signal(str)
    analysis_requested = Signal()

    def __init__(self):
        super().__init__()
        self._has_populated_map = False
        add_heading(self.layout, "КАРТА / МУНИЦИПАЛИТЕТ", "Карта муниципалитета",
                    "Подразделения, функции, процедуры и роли на основании сохранённых сведений")
        self.summary = text_label("")
        self.layout.addWidget(self.summary)
        legend = QHBoxLayout()
        legend.setSpacing(7)
        for status in ("unreviewed", "reviewing", "reviewed", "attention", "rejected"):
            chip = QLabel(LABELS[status])
            chip.setStyleSheet(
                f"QLabel {{ color: white; background: {COLORS[status]}; border: 1px solid {COLORS[status]}; "
                "border-radius: 7px; padding: 4px 8px; font-size: 9pt; }"
            )
            legend.addWidget(chip)
        legend.addStretch()
        self.layout.addLayout(legend)
        self.layout.addWidget(text_label(
            "Цвет обозначает статус проверки. Проверка сведений не означает отсутствия рисков.", muted=True))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Найти подразделение, функцию, этап или роль…")
        self.search.textChanged.connect(self.apply_filter)
        self.layout.addWidget(self.search)
        self.empty_state, empty_layout = framed(self.layout)
        self.empty_state.setObjectName("functionMapEmpty")
        empty_layout.addWidget(text_label("На карте пока нет функций"))
        empty_layout.addWidget(text_label(
            "Загрузите синтетический DOCX, сохраните кандидатов и проверьте записи. "
            "После этого здесь появятся функция, процедуры, этапы, роли и контроли.", muted=True))
        self.analysis_button = QPushButton("Открыть анализ функций")
        self.analysis_button.setObjectName("primary")
        self.analysis_button.clicked.connect(self.analysis_requested.emit)
        empty_layout.addWidget(self.analysis_button)
        self.tree = QTreeWidget()
        self.tree.setObjectName("functionMapTree")
        self.tree.setHeaderLabels(["Структура", "Статус проверки", "Основания для внимания"])
        self.tree.setMinimumHeight(310)
        self.tree.setColumnWidth(0, 450)
        self.tree.setColumnWidth(1, 240)
        self.tree.setAlternatingRowColors(True)
        self.tree.setStyleSheet("""
            QTreeWidget {
                color: #1c2b33; background: white; alternate-background-color: #f7f9fa;
                border: 1px solid #d5dfe5; border-radius: 8px; outline: 0;
                selection-color: #1c2b33; selection-background-color: #d9ebff;
            }
            QTreeWidget::item {
                color: #1c2b33; background: white; border-bottom: 1px solid #e0e6ea;
                padding: 6px 4px; min-height: 22px;
            }
            QTreeWidget::item:alternate { color: #1c2b33; background: #f7f9fa; }
            QTreeWidget::item:hover { color: #1c2b33; background: #edf5fb; }
            QTreeWidget::item:selected:active, QTreeWidget::item:selected:!active {
                color: #1c2b33; background: #d9ebff;
            }
            QTreeWidget::branch { color: #1c2b33; background: white; }
            QTreeWidget::branch:selected { color: #1c2b33; background: #d9ebff; }
        """)
        self.tree.currentItemChanged.connect(self.show_selection)
        self.tree.itemExpanded.connect(lambda _: self.fit_tree_to_contents())
        self.tree.itemCollapsed.connect(lambda _: self.fit_tree_to_contents())
        self.layout.addWidget(self.tree)
        self.detail = text_label("Выберите функцию или этап")
        self.detail.setTextFormat(Qt.TextFormat.PlainText)
        self.layout.addWidget(self.detail)
        controls = QHBoxLayout()
        self.open_button = QPushButton("Открыть в анализе функций")
        self.open_button.setObjectName("primary")
        self.open_button.clicked.connect(self.open_node)
        self.risks_button = QPushButton("Находки выбранной функции")
        self.risks_button.clicked.connect(self.open_risks)
        self.source_button = QPushButton("Сведения об источнике")
        self.source_button.clicked.connect(self.open_source)
        self.department_button = QPushButton("Указать подразделение")
        self.department_button.clicked.connect(self.edit_department)
        for button in (self.open_button, self.risks_button, self.source_button, self.department_button):
            controls.addWidget(button)
        self.layout.addLayout(controls)
        self.refresh()

    @staticmethod
    def walk_items(item):
        yield item
        for index in range(item.childCount()):
            yield from FunctionMapPage.walk_items(item.child(index))

    def all_items(self):
        for index in range(self.tree.topLevelItemCount()):
            yield from self.walk_items(self.tree.topLevelItem(index))

    @staticmethod
    def style_item(item, status=None):
        for column in range(3):
            item.setForeground(column, QColor("#1c2b33"))
            item.setBackground(column, QColor("white"))
        if status:
            item.setForeground(1, QColor(COLORS[status]))

    def refresh(self):
        current = self.tree.currentItem()
        selected = current.data(0, Qt.ItemDataRole.UserRole) if current else None
        expanded = {item.data(0, Qt.ItemDataRole.UserRole) for item in self.all_items() if item.isExpanded()}
        self.tree.blockSignals(True)
        self.tree.clear()
        self.overview = load_overview()
        self.nodes, self.roots, self.items = {}, {}, {}
        root = QTreeWidgetItem(self.tree, ["Администрация муниципального образования"])
        root.setData(0, Qt.ItemDataRole.UserRole, "root")
        self.style_item(root)
        departments = {}
        for entry in self.overview:
            function = entry["function"]
            department = function.department or "Подразделение не указано"
            if department not in departments:
                departments[department] = QTreeWidgetItem(root, [department])
                departments[department].setData(0, Qt.ItemDataRole.UserRole, f"department:{department}")
                self.style_item(departments[department])
            # Storage order is creation order: parents precede their children.
            for node in entry["nodes"]:
                parent = departments[department] if node.kind == "function" else self.items[node.parent_id]
                status = LABELS[entry["status"]] if node.kind == "function" else STATUSES[node.status]
                count = str(entry["active_risks"]) if node.kind == "function" else ""
                item = QTreeWidgetItem(parent, [f"{KINDS[node.kind]} · {node.title}", status, count])
                item.setData(0, Qt.ItemDataRole.UserRole, node.id)
                color_status = entry["status"] if node.kind == "function" else {
                    "candidate": "unreviewed", "confirmed": "reviewed", "rejected": "rejected"
                }[node.status]
                self.style_item(item, color_status)
                self.items[node.id], self.nodes[node.id], self.roots[node.id] = item, node, function.id
        if self.overview and not self._has_populated_map:
            if len(self.overview) == 1:
                self.tree.expandAll()
            else:
                self.tree.expandToDepth(2)
        else:
            for item in self.all_items():
                item.setExpanded(item.data(0, Qt.ItemDataRole.UserRole) in expanded)
        self._has_populated_map = self._has_populated_map or bool(self.overview)
        selected_item = next((item for item in self.all_items()
                              if item.data(0, Qt.ItemDataRole.UserRole) == selected), None)
        if selected_item is not None:
            self.tree.setCurrentItem(selected_item)
        self.tree.blockSignals(False)
        active = [entry for entry in self.overview if entry["status"] != "rejected"]
        self.summary.setText(f"Функций: {len(active)} · Оснований для внимания: "
                             f"{sum(entry['active_risks'] for entry in active)} · "
                             f"Отклонённых функций: {len(self.overview) - len(active)}")
        has_functions = bool(self.overview)
        self.empty_state.setVisible(not has_functions)
        self.search.setVisible(has_functions)
        self.tree.setVisible(has_functions)
        self.detail.setVisible(has_functions)
        if not has_functions:
            self.summary.setText("Функции ещё не внесены. Начните с документа в разделе «Анализ функций».")
        self.apply_filter()
        self.fit_tree_to_contents()
        self.show_selection()

    def fit_tree_to_contents(self):
        if len(getattr(self, "overview", [])) != 1 or self.search.text().strip():
            self.tree.setMinimumHeight(310)
            self.tree.setMaximumHeight(16777215)
            return

        def visible_rows(item):
            children = sum(visible_rows(item.child(index)) for index in range(item.childCount())) if item.isExpanded() else 0
            return (0 if item.isHidden() else 1) + children

        rows = sum(visible_rows(self.tree.topLevelItem(index)) for index in range(self.tree.topLevelItemCount()))
        row_height = max(30, self.tree.sizeHintForRow(0))
        height = min(640, max(310, self.tree.header().height() + rows * row_height + 6))
        self.tree.setMinimumHeight(height)
        self.tree.setMaximumHeight(height)

    def apply_filter(self):
        query = self.search.text().casefold().strip()

        def visit(item, ancestor_matches=False):
            own = not query or query in item.text(0).casefold()
            child_matches = [visit(item.child(i), ancestor_matches or own) for i in range(item.childCount())]
            visible = ancestor_matches or own or any(child_matches)
            item.setHidden(not visible)
            if query and any(child_matches):
                item.setExpanded(True)
            return visible

        for i in range(self.tree.topLevelItemCount()):
            visit(self.tree.topLevelItem(i))

    def selected_node(self):
        item = self.tree.currentItem()
        return getattr(self, "nodes", {}).get(item.data(0, Qt.ItemDataRole.UserRole)) if item else None

    def show_selection(self, *args):
        node = self.selected_node()
        for button in (self.open_button, self.risks_button, self.source_button):
            button.setEnabled(node is not None)
            button.setToolTip("" if node is not None else "Сначала выберите функцию, процедуру, этап, роль или контроль")
        self.department_button.setEnabled(node is not None)
        if node is None:
            self.detail.setText("Выберите функцию или этап для просмотра основания и перехода к проверке")
            return
        department = self.nodes[self.roots[node.id]].department or "Не указано"
        self.detail.setText(f"Подразделение администрации: {department}\n{KINDS[node.kind]}: {node.title}\nСтатус записи: {STATUSES[node.status]}\n"
                            f"{node.source_ref} · {node.coordinate} · редакция {node.edition}\n{node.quote}\n"
                            f"Последнее решение: {node.reviewed_at or 'Ещё не принято'}\n"
                            f"Обоснование: {node.rationale or 'Не указано'}\n"
                            "Актуальность файла повторно проверяется при подтверждении и экспорте.")

    def edit_department(self):
        node = self.selected_node()
        if node is None:
            return
        function = self.nodes[self.roots[node.id]]
        department, accepted = QInputDialog.getText(
            self, "Подразделение администрации", f"Подразделение для функции «{function.title}»", text=function.department)
        if accepted:
            try:
                assign_department(function.id, department)
            except ValueError as exc:
                QMessageBox.information(self, "Подразделение администрации", str(exc))
                return
            self.refresh()
            parent = self.items[node.id].parent()
            while parent:
                parent.setExpanded(True)
                parent = parent.parent()

    def open_node(self):
        node = self.selected_node()
        if node:
            self.node_requested.emit(node.id)

    def open_risks(self):
        node = self.selected_node()
        if node:
            self.risks_requested.emit(self.roots[node.id])

    def open_source(self):
        node = self.selected_node()
        if node:
            show_source(self, read_source(node.source_ref))
