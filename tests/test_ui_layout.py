from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget, QVBoxLayout

from lotus.ui.common import PageCombo, ScrollPage


def test_wheel_over_closed_focused_combo_scrolls_parent(qapp):
    page = ScrollPage()
    combo = PageCombo()
    combo.addItems(["Первое", "Второе", "Третье"])
    combo.setCurrentIndex(1)
    page.layout.addWidget(combo)
    page.layout.addSpacing(800)
    page.resize(400, 220)
    page.show()
    combo.setFocus()
    qapp.processEvents()
    point = combo.mapTo(page, combo.rect().center())
    QTest.wheelEvent(page.windowHandle(), point, QPoint(0, -120))
    qapp.processEvents()
    assert combo.currentIndex() == 1
    assert page.verticalScrollBar().value() > 0
    QTest.keyClick(combo, Qt.Key.Key_Down)
    assert combo.currentIndex() == 2
    page.close()


def test_registry_decisions_fit_and_filter_buttons_work(tmp_path, monkeypatch, qapp):
    import lotus.db as db
    from tests.test_function_detectors import procedure
    from lotus.functions.detectors import run_rules
    from lotus.ui.risk_registry_page import RiskRegistryPage
    from lotus.ui.common import STYLE
    _, path, nodes = procedure(tmp_path, "Подготовка решения в разумный срок")
    run_rules(nodes[1].id, path=path)
    monkeypatch.setattr(db, "DB_PATH", path)
    host = QWidget()
    host.setStyleSheet(STYLE)
    layout = QVBoxLayout(host)
    page = RiskRegistryPage()
    layout.addWidget(page)
    host.resize(792, 555)
    host.show()
    qapp.processEvents()
    assert host.width() == 792 and host.height() == 555
    assert page.confirm_button.mapTo(host, page.confirm_button.rect().bottomRight()).y() < host.height()
    assert page.table.horizontalScrollBar().maximum() == 0
    page.origin_filter.menu().actions()[2].trigger()
    assert page.table.rowCount() == 0
    page.origin_filter.menu().actions()[1].trigger()
    assert page.table.rowCount() == 1
    page.new_button.click()
    assert page.editor.isVisible()
    page.editor.reject()
    host.close()
