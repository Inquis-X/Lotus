import sqlite3

import pytest
from docx import Document

from lotus.audit import read_log
from lotus.db import connection
from lotus.documents import parse_document
from lotus.functions.service import create_candidate, list_nodes, migrate, review, confirmed_procedure


@pytest.fixture
def material(tmp_path):
    file = tmp_path / "synthetic.docx"
    doc = Document()
    doc.add_paragraph("Учебная функция. Учебная процедура. Приём заявления.")
    doc.save(file)
    path = tmp_path / "functions.sqlite"
    parsed = parse_document(file, path)
    return file, path, dict(source_ref=parsed.source.id, coordinate="абзац 1", edition="Учебная редакция 1",
                           quote=parsed.fragments[0].text)


def test_function_chain_review_and_reopen(material):
    _, path, evidence = material
    f = create_candidate(kind="function", title="Учебная функция", path=path, **evidence)
    p = create_candidate(kind="procedure", title="Учебная процедура", parent_id=f.id, path=path, **evidence)
    s = create_candidate(kind="stage", title="Приём заявления", parent_id=p.id, path=path, **evidence)
    with pytest.raises(ValueError):
        review(s.id, "confirmed", "Проверено", path=path)
    with pytest.raises(ValueError):
        confirmed_procedure(p.id, path)
    for node in (f, p, s):
        review(node.id, "confirmed", "Цитата и редакция проверены", path=path)
    assert len(confirmed_procedure(p.id, path)) == 3
    assert all(n.status == "confirmed" and n.reviewed_at for n in list_nodes(path))
    with pytest.raises(ValueError):
        review(f.id, "rejected", "Пересмотр", path=path)
    assert len([r for r in read_log(path) if r["action"] == "Проверка функции или этапа"]) == 3


@pytest.mark.parametrize("changes", [{"edition": " "}, {"quote": "Нет такой цитаты"},
                                    {"coordinate": "абзац 99"}, {"source_ref": "missing"}])
def test_invalid_evidence_is_not_saved(material, changes):
    _, path, evidence = material
    with pytest.raises(ValueError):
        create_candidate(kind="function", title="Функция", path=path, **(evidence | changes))
    assert list_nodes(path) == []


def test_source_change_and_empty_rationale_block_confirmation(material):
    file, path, evidence = material
    f = create_candidate(kind="function", title="Функция", path=path, **evidence)
    with pytest.raises(ValueError):
        review(f.id, "confirmed", " ", path=path)
    file.write_bytes(b"changed")
    with pytest.raises(ValueError, match="изменён"):
        review(f.id, "confirmed", "Проверено", path=path)
    assert list_nodes(path)[0].status == "candidate"


def test_audit_failure_rolls_back_review_and_migration_preserves_legacy(material):
    _, path, evidence = material
    f = create_candidate(kind="function", title="Функция", path=path, **evidence)
    with connection(path) as con:
        con.execute("INSERT INTO records VALUES ('legacy','1','{}')")
        con.execute("""CREATE TRIGGER fail_review BEFORE INSERT ON audit_log
                       BEGIN SELECT RAISE(ABORT, 'audit unavailable'); END""")
    with pytest.raises(sqlite3.IntegrityError):
        review(f.id, "confirmed", "Проверено", path=path)
    assert list_nodes(path)[0].status == "candidate"
    migrate(path)
    with connection(path) as con:
        assert con.execute("SELECT payload FROM records WHERE id='1'").fetchone()[0] == '{}'
        assert {row[0] for row in con.execute("SELECT version FROM function_schema")} == {1, 2, 4}


def test_function_page_creates_reviews_and_restores(monkeypatch, tmp_path, qapp):
    from lotus.ui.function_page import FunctionPage
    import lotus.db as db

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "ui.sqlite")
    file = tmp_path / "manual.docx"
    doc = Document()
    doc.add_paragraph("Учебная функция предоставления участков.")
    doc.save(file)
    monkeypatch.setattr("PySide6.QtWidgets.QFileDialog.getOpenFileName", lambda *a: (str(file), ""))
    page = FunctionPage()
    assert not page.load_button.isEnabled()
    page.privacy_check.setChecked(True)
    assert page.load_button.isEnabled()
    page.load_button.click()
    page.edition.setText("Учебная редакция 1")
    page.title.setText("Предоставление участков")
    page.create_button.click()
    assert page.table.rowCount() == 1
    assert not page.confirm_button.isEnabled()
    page.rationale.setText("Текст и редакция проверены")
    page.confirm_button.click()
    assert page.nodes[0].status == "confirmed"
    page.close()
    restored = FunctionPage()
    assert restored.nodes == []
    restored.privacy_check.setChecked(True)
    restored.load_button.click()
    assert restored.nodes[0].status == "confirmed"
    restored.close()


def test_function_page_scopes_records_to_document_and_resets(material, monkeypatch, qapp, tmp_path):
    from PySide6.QtWidgets import QMessageBox
    from lotus.ui.function_page import FunctionPage
    from lotus.functions.practice import list_cases, list_links, save_link
    from lotus.functions.service import create_risk, list_risks
    import lotus.db as db
    file, path, evidence = material
    monkeypatch.setattr(db, "DB_PATH", path)
    stage = confirmed_chain(path, evidence)
    risk = create_risk(stage_id=stage.id, vulnerability="Вопрос", control_limitation="Не установлено",
                       proposed_measure="Проверить", path=path)
    case = list_cases(path)[0]
    save_link(case.id, risk.id, "Совпадает условие", "Неполный комплект", "Учебная аналогия", path=path)
    other = tmp_path / "other.docx"
    other_doc = Document()
    other_doc.add_paragraph("Другой учебный документ.")
    other_doc.save(other)
    page = FunctionPage()
    assert page.nodes == [] and not page.reset_button.isEnabled()
    page.privacy_check.setChecked(True)
    monkeypatch.setattr("PySide6.QtWidgets.QFileDialog.getOpenFileName", lambda *a: (str(file), ""))
    page.load_button.click()
    assert len(page.nodes) == 3 and page.reset_button.isEnabled()
    monkeypatch.setattr("PySide6.QtWidgets.QFileDialog.getOpenFileName", lambda *a: (str(other), ""))
    page.load_button.click()
    assert page.nodes == [] and not page.reset_button.isEnabled()
    monkeypatch.setattr("PySide6.QtWidgets.QFileDialog.getOpenFileName", lambda *a: (str(file), ""))
    page.load_button.click()
    assert len(page.nodes) == 3
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    page.reset_button.click()
    assert page.nodes == [] and list_nodes(path) == [] and list_risks(path) == []
    assert list_links(path=path) == []
    assert not page.reset_button.isEnabled()
    assert any(row["action"] == "Сброшена проверка записей документа" for row in read_log(path))
    page.close()


def test_map_projection_states_and_department_compatibility(material):
    from lotus.functions.overview import load_overview
    from lotus.functions.service import create_risk, review_risk
    from lotus.functions.models import FunctionNode
    _, path, evidence = material
    f = create_candidate(kind="function", title="Функция", department="Земельное управление", path=path, **evidence)
    assert load_overview(path)[0]["status"] == "unreviewed"
    review(f.id, "confirmed", "Проверено", path=path)
    assert load_overview(path)[0]["status"] == "reviewing"
    p = create_candidate(kind="procedure", title="Процедура", parent_id=f.id, path=path, **evidence)
    s = create_candidate(kind="stage", title="Этап", parent_id=p.id, path=path, **evidence)
    for node in (p, s):
        review(node.id, "confirmed", "Проверено", path=path)
    assert load_overview(path)[0]["status"] == "reviewed"
    r = create_risk(stage_id=s.id, vulnerability="Вопрос", control_limitation="Не установлено",
                    proposed_measure="Проверить", path=path)
    assert load_overview(path)[0]["status"] == "attention"
    review_risk(r.id, "rejected", "Основание не подтверждено", path=path)
    assert load_overview(path)[0]["status"] == "reviewed"
    assert load_overview(path)[0]["function"].department == "Земельное управление"
    legacy = f.model_dump()
    del legacy["department"]
    assert FunctionNode.model_validate(legacy).department == ""


def test_map_navigation_to_node_and_scoped_registry(material, monkeypatch, qapp):
    import lotus.db as db
    from lotus.ui.main_window import MainWindow
    from lotus.functions.service import create_risk
    _, path, evidence = material
    monkeypatch.setattr(db, "DB_PATH", path)
    stages = [confirmed_chain(path, evidence), confirmed_chain(path, evidence)]
    for stage in stages:
        create_risk(stage_id=stage.id, vulnerability="Вопрос", control_limitation="Не установлено",
                    proposed_measure="Проверить", path=path)
    window = MainWindow()
    try:
        window.open_section(1)
        page = window.function_map_page
        page.tree.setCurrentItem(page.items[stages[0].id])
        page.open_button.click()
        assert window.function_page.selected_node().id == stages[0].id
        window.open_section(1)
        assert page.selected_node().id == stages[0].id
        page.risks_button.click()
        assert window.risk_registry_page.table.rowCount() == 1
        assert window.risk_registry_page.records[0].stage_id == stages[0].id
        window.risk_registry_page.function_filter.setCurrentIndex(0)
        assert window.risk_registry_page.table.rowCount() == 2
        window.open_section(1)
        page.search.setText("несуществующий текст")
        assert page.tree.topLevelItem(0).isHidden()
        page.search.clear()
        assert not page.tree.topLevelItem(0).isHidden()
    finally:
        window.close()


def confirmed_chain(path, evidence):
    function = create_candidate(kind="function", title="Функция", path=path, **evidence)
    procedure = create_candidate(kind="procedure", title="Процедура", parent_id=function.id, path=path, **evidence)
    stage = create_candidate(kind="stage", title="Этап", parent_id=procedure.id, path=path, **evidence)
    for node in (function, procedure, stage):
        review(node.id, "confirmed", "Проверено", path=path)
    return stage


def new_edition(file, path):
    target = file.with_name("new_edition.docx")
    doc = Document()
    doc.add_paragraph("Учебная новая редакция. Подготовка проекта решения.")
    doc.save(target)
    parsed = parse_document(target, path)
    return dict(source_ref=parsed.source.id, coordinate="абзац 1", edition="Учебная редакция 2",
                quote=parsed.fragments[0].text)


def test_edition_change_preserves_history_and_blocks_report(material):
    from lotus.functions.service import (create_risk, review_risk, list_risks,
                                           record_edition_change, edition_history)
    from lotus.functions.report import build_report
    file, path, evidence = material
    stage = confirmed_chain(path, evidence)
    control = create_candidate(kind="control", title="Контроль", parent_id=stage.id, path=path, **evidence)
    review(control.id, "confirmed", "Проверено", path=path)
    risk = create_risk(stage_id=stage.id, control_id=control.id, vulnerability="Вопрос",
                       control_limitation="Не установлено", proposed_measure="Проверить", path=path)
    review_risk(risk.id, "confirmed", "Прежнее решение", path=path)
    changed = new_edition(file, path)
    record_edition_change(stage.id, rationale="Изменено описание этапа", path=path, **changed)
    updated = {node.id: node for node in list_nodes(path)}
    assert updated[stage.id].status == updated[control.id].status == "candidate"
    pending = list_risks(path)[0]
    assert pending.needs_review and pending.quote == evidence["quote"]
    assert pending.rationale == "Прежнее решение"
    history = edition_history(stage.id, path)
    assert history[0]["before"]["quote"] == evidence["quote"]
    assert history[0]["after"]["quote"] == changed["quote"]
    with pytest.raises(ValueError):
        build_report([risk.id], path=path)
    with pytest.raises(ValueError):
        review_risk(risk.id, "confirmed", "Проверено", path=path)
    review(stage.id, "confirmed", "Новая редакция проверена", path=path)
    review(control.id, "confirmed", "Контроль проверен", path=path)
    review_risk(risk.id, "confirmed", "Повторная оценка по новой редакции", path=path)
    current = list_risks(path)[0]
    assert not current.needs_review and current.quote == changed["quote"]
    assert build_report([risk.id], path=path)[0].startswith(b"PK")


def test_edition_change_validation_and_atomicity(material):
    from lotus.functions.service import record_edition_change, edition_history
    file, path, evidence = material
    stage = confirmed_chain(path, evidence)
    with pytest.raises(ValueError):
        record_edition_change(stage.id, rationale="Причина", path=path, **evidence)
    changed = new_edition(file, path)
    with pytest.raises(ValueError):
        record_edition_change(stage.id, rationale=" ", path=path, **changed)
    with connection(path) as con:
        con.execute("""CREATE TRIGGER fail_edition BEFORE INSERT ON audit_log
                       BEGIN SELECT RAISE(ABORT, 'audit unavailable'); END""")
    with pytest.raises(sqlite3.IntegrityError):
        record_edition_change(stage.id, rationale="Изменено описание", path=path, **changed)
    assert edition_history(stage.id, path) == []
    assert next(node for node in list_nodes(path) if node.id == stage.id).status == "confirmed"


def test_practice_links_require_reason_preserve_risk_and_audit(material):
    from lotus.functions.practice import list_cases, save_link, list_links, remove_link
    from lotus.functions.service import create_risk, list_risks, review_risk
    _, path, evidence = material
    stage = confirmed_chain(path, evidence)
    risk = create_risk(stage_id=stage.id, vulnerability="Вопрос", control_limitation="Не установлено",
                       proposed_measure="Проверить", path=path)
    cases = list_cases(path)
    assert len(cases) == 2
    assert all(c.material_type == "teaching_example" and c.status == "candidate" for c in cases)
    case = cases[0]
    with pytest.raises(ValueError):
        save_link(case.id, risk.id, "Совпадает условие", "", "Проверено", path=path)
    save_link(case.id, risk.id, "Совпадает условие", "Неполный комплект", "Учебная аналогия", path=path)
    save_link(case.id, risk.id, "Уточнённое условие", "Неполный комплект", "Уточнено", path=path)
    assert len(list_links(risk_id=risk.id, path=path)) == 1
    assert list_risks(path)[0].status == "candidate"
    review_risk(risk.id, "rejected", "Пересмотр", path=path)
    with pytest.raises(ValueError, match="отклонённой"):
        save_link(case.id, risk.id, "Условие", "Ограничения", "Причина", path=path)
    remove_link(case.id, risk.id, "Аналогия неприменима", path=path)
    assert list_links(path=path) == []
    assert len([r for r in read_log(path) if r["object_type"] == "practice_link"]) == 3


def test_practice_revision_preserved_and_audit_rollback(material, monkeypatch, tmp_path):
    import lotus.functions.practice as practice
    from lotus.functions.service import create_risk
    _, path, evidence = material
    copied = tmp_path / "practice.yaml"
    copied.write_bytes(practice.PRACTICE_FILE.read_bytes())
    monkeypatch.setattr(practice, "PRACTICE_FILE", copied)
    first = practice.list_cases(path)
    copied.write_text(copied.read_text(encoding="utf-8").replace("Учебная редакция 1", "Учебная редакция 2"), encoding="utf-8")
    versions = practice.list_cases(path)
    assert len(versions) == 4
    assert versions[0] == first[0]
    stage = confirmed_chain(path, evidence)
    risk = create_risk(stage_id=stage.id, vulnerability="Вопрос", control_limitation="Не установлено",
                       proposed_measure="Проверить", path=path)
    with connection(path) as con:
        con.execute("""CREATE TRIGGER fail_practice BEFORE INSERT ON audit_log
                       WHEN NEW.object_type='practice_link'
                       BEGIN SELECT RAISE(ABORT, 'audit unavailable'); END""")
    with pytest.raises(sqlite3.IntegrityError):
        practice.save_link(first[0].id, risk.id, "Условие", "Ограничения", "Причина", path=path)
    assert practice.list_links(path=path) == []


def test_practice_page_filter_link_and_restore(material, monkeypatch, qapp):
    from lotus.ui.practice_page import PracticePage
    from lotus.functions.service import create_risk, list_risks
    import lotus.db as db
    _, path, evidence = material
    monkeypatch.setattr(db, "DB_PATH", path)
    stage = confirmed_chain(path, evidence)
    risk = create_risk(stage_id=stage.id, vulnerability="Вопрос", control_limitation="Не установлено",
                       proposed_measure="Проверить", path=path)
    page = PracticePage()
    assert page.cases_list.count() == 2
    assert all(page.cases_list.item(row).foreground().color().name() == "#1c2b33"
               for row in range(page.cases_list.count()))
    assert page.cases_list.item(0).background().color().name() == "#ffffff"
    assert page.cases_list.item(1).background().color().name() == "#f7f9fa"
    page.search.setText("земель")
    assert page.cases_list.count() == 1
    page.risk.setCurrentIndex(page.risk.findData(risk.id))
    page.matching.setText("Условие совпадает")
    page.limitations.setText("Нужен полный комплект")
    page.rationale.setText("Учебная аналогия")
    page.save_button.click()
    assert page.remove_button.isEnabled()
    page.close()
    reopened = PracticePage()
    reopened.risk.setCurrentIndex(reopened.risk.findData(risk.id))
    assert reopened.matching.text() == "Условие совпадает"
    assert list_risks(path)[0].status == "candidate"
    reopened.rationale.setText("Аналогия неприменима")
    reopened.remove_button.click()
    assert not reopened.remove_button.isEnabled()
    reopened.search.setText("несуществующий запрос")
    assert reopened.cases_list.count() == 0
    reopened.close()


def test_roles_controls_and_risk_review_dependencies(material):
    from lotus.functions.service import create_risk, review_risk, list_risks
    _, path, evidence = material
    stage = confirmed_chain(path, evidence)
    role = create_candidate(kind="role", title="Учебная должностная роль", parent_id=stage.id, path=path, **evidence)
    control = create_candidate(kind="control", title="Проверка проекта", parent_id=stage.id, path=path, **evidence)
    data = dict(stage_id=stage.id, control_id=control.id, vulnerability="Вопрос о критериях",
                control_limitation="Объём проверки требует уточнения", proposed_measure="Уточнить критерии", path=path)
    with pytest.raises(ValueError, match="подтвердите"):
        create_risk(**data)
    for node in (role, control):
        review(node.id, "confirmed", "Проверено", path=path)
    risk = create_risk(**data)
    with pytest.raises(ValueError, match="существует"):
        create_risk(**data)
    with pytest.raises(ValueError):
        review_risk(risk.id, "confirmed", " ", path=path)
    review_risk(risk.id, "confirmed", "Основание и ограничение проверены", path=path)
    with pytest.raises(ValueError, match="реестра"):
        review(control.id, "rejected", "Пересмотр", path=path)
    assert list_risks(path)[0].quote == evidence["quote"]
    assert list_risks(path)[0].status == "confirmed"
    review_risk(risk.id, "rejected", "Требуется новая оценка", path=path)
    review(control.id, "rejected", "Контроль пересмотрен", path=path)
    with pytest.raises(ValueError):
        review_risk(risk.id, "confirmed", "Повторная проверка", path=path)


def test_risk_rejects_control_from_other_stage(material):
    from lotus.functions.service import create_risk
    _, path, evidence = material
    stage = confirmed_chain(path, evidence)
    other = create_candidate(kind="stage", title="Другой этап", parent_id=stage.parent_id, path=path, **evidence)
    review(other.id, "confirmed", "Проверено", path=path)
    control = create_candidate(kind="control", title="Другой контроль", parent_id=other.id, path=path, **evidence)
    review(control.id, "confirmed", "Проверено", path=path)
    with pytest.raises(ValueError, match="относиться"):
        create_risk(stage_id=stage.id, control_id=control.id, vulnerability="Вопрос",
                    control_limitation="Не установлено", proposed_measure="Проверить", path=path)


def test_risk_audit_failure_rolls_back_creation_and_review(material):
    from lotus.functions.service import create_risk, review_risk, list_risks
    _, path, evidence = material
    stage = confirmed_chain(path, evidence)
    data = dict(stage_id=stage.id, vulnerability="Вопрос", control_limitation="Не установлено",
                proposed_measure="Проверить", path=path)
    risk = create_risk(**data)
    with connection(path) as con:
        con.execute("""CREATE TRIGGER fail_risk BEFORE INSERT ON audit_log
                       WHEN NEW.object_type='function_risk'
                       BEGIN SELECT RAISE(ABORT, 'audit unavailable'); END""")
    with pytest.raises(sqlite3.IntegrityError):
        review_risk(risk.id, "confirmed", "Проверено", path=path)
    with pytest.raises(sqlite3.IntegrityError):
        create_risk(**(data | {"vulnerability": "Другой вопрос"}))
    records = list_risks(path)
    assert len(records) == 1 and records[0].status == "candidate"


def test_risk_page_create_filter_review_and_reopen(material, monkeypatch, qapp):
    from lotus.ui.risk_registry_page import RiskRegistryPage
    import lotus.db as db
    _, path, evidence = material
    monkeypatch.setattr(db, "DB_PATH", path)
    stage = confirmed_chain(path, evidence)
    page = RiskRegistryPage()
    page.stage.setCurrentIndex(page.stage.findData(stage.id))
    page.vulnerability.setText("Критерии требуют уточнения")
    page.limitation.setText("Контроль не установлен по представленным данным")
    page.measure.setText("Проверить комплект документов")
    page.create_button.click()
    assert page.table.rowCount() == 1
    assert not page.confirm_button.isEnabled()
    page.rationale.setText("Вывод проверен по источнику")
    page.confirm_button.click()
    page.filter.setCurrentIndex(page.filter.findData("candidate"))
    assert page.table.rowCount() == 0
    page.close()
    reopened = RiskRegistryPage()
    assert reopened.records[0].status == "confirmed"
    reopened.close()


def test_risk_report_rejects_unconfirmed_and_changed_source(material):
    from lotus.functions.service import create_risk, review_risk
    from lotus.functions.report import build_report
    file, path, evidence = material
    stage = confirmed_chain(path, evidence)
    record = create_risk(stage_id=stage.id, vulnerability="Вопрос", control_limitation="Не установлено",
                         proposed_measure="Проверить", path=path)
    for ids in ([], [record.id], ["missing"], [record.id, record.id]):
        with pytest.raises(ValueError):
            build_report(ids, path=path)
    review_risk(record.id, "confirmed", "Проверено", path=path)
    file.write_bytes(b"changed")
    with pytest.raises(ValueError, match="изменён"):
        build_report([record.id], path=path)


def test_risk_report_contains_citations_decisions_and_control(material):
    from io import BytesIO
    from lotus.functions.service import create_risk, review_risk
    from lotus.functions.report import build_report
    _, path, evidence = material
    stage = confirmed_chain(path, evidence)
    control = create_candidate(kind="control", title="Согласование", parent_id=stage.id, path=path, **evidence)
    review(control.id, "confirmed", "Проверено", path=path)
    record = create_risk(stage_id=stage.id, control_id=control.id, vulnerability="Вопрос о критериях",
                         control_limitation="Объём проверки не установлен", proposed_measure="Уточнить критерии", path=path)
    review_risk(record.id, "confirmed", "Основание проверено специалистом", path=path)
    content, snapshot = build_report([record.id], path=path)
    text = "\n".join(p.text for p in Document(BytesIO(content)).paragraphs)
    for required in ("Проект карты", "[И1]", evidence["quote"], evidence["edition"], "Согласование",
                     "Уточнить критерии", "Основание проверено специалистом", "SHA-256"):
        assert required in text
    assert "[И2]" not in text  # Same immutable source and edition are deduplicated.
    assert snapshot["status"] == "draft"
    assert any(row["action"] == "Сформирован проект карты рисков" for row in read_log(path))


def test_report_ui_exports_and_invalidates_preview(material, monkeypatch, tmp_path, qapp):
    from PySide6.QtCore import Qt
    from lotus.ui.function_report_page import FunctionReportPage
    from lotus.functions.service import create_risk, review_risk
    import lotus.db as db
    _, path, evidence = material
    monkeypatch.setattr(db, "DB_PATH", path)
    stage = confirmed_chain(path, evidence)
    record = create_risk(stage_id=stage.id, vulnerability="Вопрос", control_limitation="Не установлено",
                         proposed_measure="Проверить", path=path)
    review_risk(record.id, "confirmed", "Проверено", path=path)
    output = tmp_path / "draft.docx"
    monkeypatch.setattr("PySide6.QtWidgets.QFileDialog.getSaveFileName", lambda *a: (str(output), ""))
    page = FunctionReportPage()
    page.records.item(0).setCheckState(Qt.CheckState.Checked)
    page.generate_button.click()
    assert page.save_button.isEnabled()
    page.save_button.click()
    assert output.read_bytes().startswith(b"PK")
    page.records.item(0).setCheckState(Qt.CheckState.Unchecked)
    assert not page.save_button.isEnabled()
    assert page.content_bytes is None
    page.records.item(0).setCheckState(Qt.CheckState.Checked)
    page.generate_button.click()
    review_risk(record.id, "rejected", "Пересмотр", path=path)
    page.save_button.click()
    assert page.content_bytes is None
    page.close()


def test_assign_department_from_map_keeps_review_and_regroups_function(material, monkeypatch, qapp):
    import lotus.db as db
    from PySide6.QtWidgets import QInputDialog
    from lotus.ui.function_map_page import FunctionMapPage
    _, path, evidence = material
    monkeypatch.setattr(db, "DB_PATH", path)
    function = create_candidate(kind="function", title="Учебная функция", path=path, **evidence)
    review(function.id, "confirmed", "Проверен пункт регламента", path=path)
    page = FunctionMapPage()
    page.tree.setCurrentItem(page.items[function.id])
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("Управление земельных отношений", True))
    page.department_button.click()
    updated, = list_nodes(path)
    assert updated.department == page.items[function.id].parent().text(0) == "Управление земельных отношений"
    assert updated.status == "confirmed"
    assert updated.department in page.detail.text()
    assert any(row["action"] == "Указано подразделение администрации" for row in read_log(path))
    page.close()
