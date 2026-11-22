from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QListWidget, QMainWindow, QStackedWidget, QVBoxLayout, QWidget, QLineEdit, QMenu, QPushButton

from lotus.audit import log
from lotus.db import init_db
from lotus.settings import DATA_ROOT
from lotus.ui.audit_page import AuditPage
from lotus.ui.document_page import DocumentPage
from lotus.ui.workspace_page import HomePage
from lotus.ui.function_page import FunctionPage
from lotus.ui.risk_registry_page import RiskRegistryPage
from lotus.ui.function_report_page import FunctionReportPage
from lotus.ui.function_map_page import FunctionMapPage
from lotus.ui.practice_page import PracticePage


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Лотос · Рабочее пространство")
        self.setMinimumSize(1100, 720)
        self.resize(1440, 920)
        init_db()

        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.setCentralWidget(central)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(248)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(14, 20, 14, 16)
        side.setSpacing(4)
        brand = QLabel("ЛОТОС")
        brand.setObjectName("brand")
        side.addWidget(brand)
        brand_sub = QLabel("ПРОСТРАНСТВО ПРОФИЛАКТИКИ")
        brand_sub.setObjectName("brandSub")
        side.addWidget(brand_sub)
        side.addSpacing(18)
        self.navigation = QListWidget()
        self.navigation.setObjectName("navigation")
        self.navigation.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.navigation.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sections = ["Главная", "Карта муниципалитета", "Документальный центр",
                    "Анализ функций", "Реестр рисков", "База практики", "Отчёты"]
        for position, title in enumerate(sections, start=1):
            self.navigation.addItem(title)
            item = self.navigation.item(position - 1)
            item.setToolTip(f"Раздел {position} из {len(sections)} — {title}")
        self.navigation.setCurrentRow(0)
        row_height = max(36, self.navigation.sizeHintForRow(0))
        self.navigation.setFixedHeight(row_height * len(sections) + 12)
        side.addWidget(self.navigation)
        side.addStretch()
        root.addWidget(sidebar)

        workspace = QWidget()
        work = QVBoxLayout(workspace)
        work.setContentsMargins(26, 14, 26, 0)
        work.setSpacing(10)
        header = QHBoxLayout()
        self.section_title = QLabel("ЛОТОС · Главная")
        self.section_title.setObjectName("section")
        header.addWidget(self.section_title)
        header.addStretch()
        self.section_search = QLineEdit()
        self.section_search.setPlaceholderText("Найти раздел…")
        self.section_search.setAccessibleName("Поиск раздела")
        self.section_search.setMaximumWidth(240)
        self.section_search.textChanged.connect(self.filter_navigation)
        header.addWidget(self.section_search)
        header.addWidget(QLabel("Специалист"))
        self.service_button = QPushButton("Сервис")
        header.addWidget(self.service_button)
        work.addLayout(header)
        municipality = QLabel("Администрация муниципального образования")
        municipality.setObjectName("muted")
        work.addWidget(municipality)
        self.pages = QStackedWidget()
        self.pages.setObjectName("pageStack")
        work.addWidget(self.pages, 1)
        root.addWidget(workspace, 1)

        self.audit_page = AuditPage()
        self.home_page = HomePage(self.open_section)
        self.function_map_page = FunctionMapPage()
        self.document_page = DocumentPage()
        self.function_page = FunctionPage()
        self.risk_registry_page = RiskRegistryPage()
        self.practice_page = PracticePage()
        self.function_report_page = FunctionReportPage()
        self.section_pages = [self.home_page, self.function_map_page, self.document_page,
                              self.function_page, self.risk_registry_page, self.practice_page,
                              self.function_report_page]
        for page in [*self.section_pages, self.audit_page]:
            self.pages.addWidget(page)

        self.function_map_page.node_requested.connect(self.show_function_node)
        self.function_map_page.risks_requested.connect(self.show_function_risks)
        self.function_map_page.analysis_requested.connect(lambda: self.open_section(3))
        self.function_page.risks_requested.connect(lambda: self.open_section(4))
        self.function_page.reports_requested.connect(lambda: self.open_section(6))
        self.risk_registry_page.analysis_requested.connect(lambda: self.open_section(3))
        self.practice_page.documents_requested.connect(lambda: self.open_section(2))
        self.function_report_page.risks_requested.connect(lambda: self.open_section(4))

        menu = QMenu(self)
        menu.addAction("Журнал действий", self.show_audit)
        self.service_button.setMenu(menu)
        self.navigation.currentRowChanged.connect(self.change_page)
        self.pages.setCurrentWidget(self.home_page)
        self.statusBar().showMessage(f"Локальные данные: {DATA_ROOT}")

    def change_page(self, index):
        if index < 0:
            return
        page = self.section_pages[index]
        self.pages.setCurrentWidget(page)
        self.section_title.setText("ЛОТОС · " + self.navigation.item(index).text())
        if page is self.risk_registry_page:
            self.risk_registry_page.refresh()
        elif page is self.function_page:
            self.function_page.refresh()
        elif page is self.function_map_page:
            self.function_map_page.refresh()
        elif page is self.home_page:
            self.home_page.refresh()
        elif page is self.function_report_page:
            self.function_report_page.refresh()
        elif page is self.practice_page:
            self.practice_page.refresh()
        log("Просмотр страницы", "page", self.navigation.item(index).text())

    def open_section(self, index):
        self.section_search.clear()
        if self.navigation.currentRow() == index:
            self.change_page(index)
        else:
            self.navigation.setCurrentRow(index)

    def show_function_node(self, node_id):
        self.open_section(3)
        self.function_page.refresh(node_id)
        self.function_page.ensureWidgetVisible(self.function_page.table)

    def show_function_risks(self, function_id):
        self.open_section(4)
        page = self.risk_registry_page
        page.filter.setCurrentIndex(0)
        page.origin_filter.setCurrentIndex(0)
        page.function_filter.setCurrentIndex(page.function_filter.findData(function_id))

    def filter_navigation(self, text):
        for index in range(self.navigation.count()):
            item = self.navigation.item(index)
            item.setHidden(text.casefold().strip() not in item.text().casefold())

    def show_audit(self):
        self.navigation.setCurrentRow(-1)
        self.pages.setCurrentWidget(self.audit_page)
        self.section_title.setText("Журнал действий")
        self.audit_page.refresh()
        log("Просмотр страницы", "page", "Журнал действий")
