import hashlib
import io

from docx import Document
import pytest

from scripts.generate_function_demo import generate
from lotus.documents import parse_document
from lotus.functions.extraction import extract, save_extraction
from lotus.functions.detectors import run_rules
from lotus.functions.report import build_report, prepare_snapshot
from lotus.functions.service import list_nodes, list_risks, review, review_risk, record_edition_change


def test_demo_reproducibility_and_protection(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    manifest = generate(first)
    assert generate(second) == manifest
    assert generate(first) == manifest
    for entry in manifest["documents"]:
        assert (first / entry["filename"]).read_bytes() == (second / entry["filename"]).read_bytes()
        assert hashlib.sha256((first / entry["filename"]).read_bytes()).hexdigest() == entry["sha256"]
    from lotus.settings import ROOT
    import json
    bundled = ROOT / "data/gold/functions"
    assert json.loads((bundled / "manifest.json").read_text(encoding="utf-8")) == manifest
    for entry in manifest["documents"]:
        assert (first / entry["filename"]).read_bytes() == (bundled / entry["filename"]).read_bytes()
    edited = first / "land_v1.docx"
    edited.write_bytes(b"user edit")
    with pytest.raises(ValueError, match="отличается"):
        generate(first)
    assert edited.read_bytes() == b"user edit"


def test_land_demo_full_lifecycle(tmp_path):
    output, database = tmp_path / "documents", tmp_path / "demo.sqlite"
    manifest = generate(output)
    entry = manifest["documents"][0]
    batch = extract(parse_document(output / entry["filename"], database), entry["edition"])
    assert len(batch.candidates) == entry["expected_candidates"] == 9
    function = next(node for node in batch.candidates if node.kind == "function")
    assert function.department == "Подразделение по земельным отношениям"
    assert function.department in function.quote
    assert all("[" not in node.quote for node in batch.candidates)
    save_extraction(batch, path=database)
    nodes = list_nodes(database)
    procedure = next(n for n in nodes if n.kind == "procedure")
    with pytest.raises(ValueError, match="Подтвердите"):
        run_rules(procedure.id, path=database)
    for node in nodes:
        review(node.id, "confirmed", "Учебная проверка цитаты, типа и связи", path=database)
    assert run_rules(procedure.id, path=database) == {"stages": 5, "matched": 2, "created": 2}
    risks = list_risks(database)
    assert sorted(r.rule_evidence.rule_id for r in risks) == sorted(entry["expected_rules"])
    assert len({r.stage_id for r in risks}) == 1
    for risk in risks:
        review_risk(risk.id, "confirmed", "Учебная оценка требует уточнения полного контекста", path=database)
    content, snapshot = build_report([r.id for r in risks], path=database)
    text = "\n".join(p.text for p in Document(io.BytesIO(content)).paragraphs)
    assert len(snapshot["entries"]) == 2 and "[И1]" in text and "Учебная редакция 1" in text
    revised = manifest["documents"][1]
    parsed = parse_document(output / revised["filename"], database)
    fragment = next(f for f in parsed.fragments if f.text.startswith("1.1.3. "))
    stage_id = risks[0].stage_id
    record_edition_change(stage_id, source_ref=parsed.source.id, coordinate=fragment.locator,
                          edition=revised["edition"], quote=fragment.text,
                          rationale="В учебном примере уточнены срок и условие", path=database)
    assert all(r.needs_review for r in list_risks(database))
    with pytest.raises(ValueError):
        prepare_snapshot([r.id for r in risks], path=database)
    with pytest.raises(ValueError):
        run_rules(procedure.id, path=database)
    for node in list_nodes(database):
        if node.id == stage_id or node.parent_id == stage_id:
            review(node.id, "confirmed", "Сопоставлены изменённый этап и сохранённые роли и контроли", path=database)
    assert run_rules(procedure.id, path=database)["matched"] == 0
    for risk in risks:
        review_risk(risk.id, "rejected", "Прежняя формулировка исключена из учебной редакции 2", path=database)
    assert all(r.status == "rejected" for r in list_risks(database))


@pytest.mark.parametrize("filename", ["land_v2.docx", "land_control.docx"])
def test_demo_control_has_no_phrase_findings(tmp_path, filename):
    output, database = tmp_path / "documents", tmp_path / "control.sqlite"
    manifest = generate(output)
    entry = next(e for e in manifest["documents"] if e["filename"] == filename)
    batch = extract(parse_document(output / filename, database), entry["edition"])
    save_extraction(batch, path=database)
    for node in batch.candidates:
        review(node.id, "confirmed", "Учебный контрольный пример проверен", path=database)
    procedure = next(n for n in batch.candidates if n.kind == "procedure")
    assert run_rules(procedure.id, path=database) == {"stages": 5, "matched": 0, "created": 0}
    assert list_risks(database) == []


def test_demo_documents_match_expected_rules(tmp_path):
    output = tmp_path / "documents"
    manifest = generate(output)
    for entry in manifest["documents"]:
        database = tmp_path / f"rules-{entry['filename']}.sqlite"
        batch = extract(parse_document(output / entry["filename"], database), entry["edition"])
        save_extraction(batch, path=database)
        for node in batch.candidates:
            review(node.id, "confirmed", "Учебная проверка цитаты и связи", path=database)
        procedure = next(n for n in batch.candidates if n.kind == "procedure")
        assert run_rules(procedure.id, path=database)["matched"] == len(entry["expected_rules"])
        assert sorted(r.rule_evidence.rule_id for r in list_risks(database)) == sorted(entry["expected_rules"])


def test_demo_ui_load_extract_review_and_find(tmp_path, monkeypatch, qapp):
    from PySide6.QtWidgets import QDialog, QFileDialog, QPushButton
    import lotus.db as db
    from lotus.ui.function_page import FunctionPage
    from lotus.ui.risk_registry_page import RiskRegistryPage
    output = tmp_path / "documents"
    generate(output)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "ui.sqlite")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a: (str(output / "land_v1.docx"), ""))

    def accept(dialog):
        dialog.findChild(QPushButton, "saveExtraction").click()
        return dialog.result()

    monkeypatch.setattr(QDialog, "exec", accept)
    page = FunctionPage()
    assert not page.load_button.isEnabled()
    page.privacy_check.setChecked(True)
    assert page.load_button.isEnabled()
    page.load_button.click()
    page.edition.setText("Учебная редакция 1")
    page.extract_button.click()
    assert page.table.rowCount() == 9
    for node in list(page.nodes):
        page.refresh(node.id)
        page.rationale.setText("Учебная проверка цитаты и связи")
        page.confirm_button.click()
    procedure = next(n for n in page.nodes if n.kind == "procedure")
    page.refresh(procedure.id)
    page.rules_button.click()
    assert "Новых кандидатов в реестре: 2" in page.message.text()
    assert "Перейдите в «Реестр рисков»" in page.message.text()
    assert page.signal_button.isEnabled()
    assert "2" in page.signal_button.text()
    registry = RiskRegistryPage()
    assert len(registry.records) == 2
    assert all(r.status == "candidate" for r in registry.records)
    registry.table.selectRow(0)
    assert "Учебная редакция 1" in registry.detail.text()
    page.close()
    registry.close()


def test_demo_ui_zero_findings_block_rules_button(tmp_path, monkeypatch, qapp):
    from PySide6.QtWidgets import QDialog, QFileDialog, QPushButton
    import lotus.db as db
    from lotus.ui.function_page import FunctionPage
    output = tmp_path / "documents"
    generate(output)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "ui.sqlite")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a: (str(output / "land_v2.docx"), ""))

    def accept(dialog):
        dialog.findChild(QPushButton, "saveExtraction").click()
        return dialog.result()

    monkeypatch.setattr(QDialog, "exec", accept)
    page = FunctionPage()
    page.privacy_check.setChecked(True)
    page.load_button.click()
    page.edition.setText("Учебная редакция 2")
    page.extract_button.click()
    for node in list(page.nodes):
        page.refresh(node.id)
        page.rationale.setText("Учебная проверка цитаты и связи")
        page.confirm_button.click()
    procedure = next(n for n in page.nodes if n.kind == "procedure")
    page.refresh(procedure.id)
    assert page.rules_button.isEnabled()
    page.rules_button.click()
    assert "Рисков не найдено" in page.message.text()
    assert not page.rules_button.isEnabled()
    assert not page.signal_button.isEnabled()
    page.close()
