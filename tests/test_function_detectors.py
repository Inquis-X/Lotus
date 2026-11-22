import io
import sqlite3

import pytest
import yaml
from docx import Document

from lotus.db import connection
from lotus.documents import parse_document
from lotus.functions import detectors
from lotus.functions.extraction import extract, save_extraction
from lotus.functions.report import build_report, prepare_snapshot
from lotus.functions.service import list_nodes, list_risks, review, review_risk, record_edition_change


def procedure(tmp_path, text, confirm=True):
    file, path = tmp_path / "procedure.docx", tmp_path / "rules.sqlite"
    doc = Document()
    for line in ("Функция [F]: Предоставление земельных участков",
                 "Процедура [P] функции [F]: Рассмотрение заявления",
                 "Этап [S] процедуры [P]: " + text,
                 "Контроль [C] этапа [S]: Проверка проекта решения"):
        doc.add_paragraph(line)
    doc.save(file)
    batch = extract(parse_document(file, path), "Учебная редакция 1")
    save_extraction(batch, path=path)
    if confirm:
        for node in batch.candidates:
            review(node.id, "confirmed", "Проверены цитата и связь", path=path)
    return file, path, list_nodes(path)


def test_two_rules_evidence_gate_idempotence_and_report(tmp_path):
    _, path, nodes = procedure(tmp_path, "Решение готовят В РАЗУМНЫЙ СРОК, при необходимости запрашивают пояснение.")
    result = detectors.run_rules(nodes[1].id, path=path)
    assert result == {"stages": 1, "matched": 2, "created": 2}
    records = list_risks(path)
    assert all(r.origin == "auto" and r.status == "candidate" for r in records)
    for record in records:
        assert (record.source_ref, record.coordinate, record.edition, record.quote) == (
            nodes[2].source_ref, nodes[2].coordinate, nodes[2].edition, nodes[2].quote)
        match = record.rule_evidence.matches[0]
        assert record.quote[match.start:match.end] == match.text
        assert len(record.rule_evidence.config_sha256) == 64
    with pytest.raises(ValueError, match="подтверждённые"):
        prepare_snapshot([records[0].id], path=path)
    review_risk(records[0].id, "confirmed", "Полный контекст проверен специалистом", path=path)
    review_risk(records[1].id, "rejected", "Условия определены в соседнем пункте", path=path)
    assert detectors.run_rules(nodes[1].id, path=path)["created"] == 0
    assert [r.status for r in list_risks(path)] == ["confirmed", "rejected"]
    content, _ = build_report([records[0].id], path=path)
    text = "\n".join(p.text for p in Document(io.BytesIO(content)).paragraphs)
    assert "найдено автоматически" in text and "F02_VAGUE_TERM" in text
    assert records[0].rule_evidence.config_sha256 in text
    assert "[И1]" in text and "В РАЗУМНЫЙ СРОК" in text


@pytest.mark.parametrize("text", [
    "Решение принимается в течение 10 дней. Критерии определены в пункте 4.",
    "Формулировка «в разумный срок» не применяется. Срок — 10 дней.",
    "Формулировка «при необходимости» не применяется. Условия определены в пункте 4.",
    "Слова: нев разумный сроковой, непри необходимостию.",
])
def test_each_phrase_rule_trap(tmp_path, text):
    _, path, nodes = procedure(tmp_path, text)
    assert detectors.run_rules(nodes[1].id, path=path)["matched"] == 0
    assert list_risks(path) == []
    with connection(path) as con:
        assert con.execute("SELECT COUNT(*) FROM audit_log WHERE action='Проверены формулировки процедуры'").fetchone()[0] == 1


@pytest.mark.parametrize("text, expected", [
    ("Решение готовят в срок, разумный для обеих сторон.", 1),
    ("СРОК разумный на подготовку решения не установлен.", 1),
    ("Проект решения готовится в разумные сроки.", 1),
    ("При возникшей необходимости запрашивают пояснение.", 1),
    ("Сроковой план утверждён, словесная необходимость отсутствует.", 0),
])
def test_reordered_and_inflected_lexemes(tmp_path, text, expected):
    _, path, nodes = procedure(tmp_path, text)
    assert detectors.run_rules(nodes[1].id, path=path)["matched"] == expected
    if not expected:
        assert list_risks(path) == []


def test_pending_control_and_changed_source_block_run(tmp_path):
    file, path, nodes = procedure(tmp_path, "Решение в разумный срок", confirm=False)
    for node in nodes[:3]:
        review(node.id, "confirmed", "Проверено", path=path)
    with pytest.raises(ValueError, match="Подтвердите"):
        detectors.run_rules(nodes[1].id, path=path)
    review(nodes[3].id, "confirmed", "Проверено", path=path)
    file.write_bytes(b"changed")
    with pytest.raises(ValueError, match="изменён"):
        detectors.run_rules(nodes[1].id, path=path)
    assert list_risks(path) == []


def test_threshold_config_exclusion_locality_and_disabled_rule(tmp_path, monkeypatch):
    _, path, nodes = procedure(tmp_path, "Формулировка «в разумный срок» не применяется. "
                              "Решение принимается в разумный срок. При необходимости — согласование.")
    config = yaml.safe_load(detectors.CONFIG_PATH.read_bytes())
    config["function_rules"]["rules"][0]["min_occurrences"] = 2
    config["function_rules"]["rules"][1]["enabled"] = False
    file = tmp_path / "rules.yaml"
    file.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(detectors, "CONFIG_PATH", file)
    assert detectors.run_rules(nodes[1].id, path=path)["created"] == 0
    config["function_rules"]["rules"][0]["min_occurrences"] = 1
    file.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    assert detectors.run_rules(nodes[1].id, path=path)["created"] == 1
    assert len(list_risks(path)[0].rule_evidence.matches) == 1
    config["function_rules"]["rules"][0]["min_occurrences"] = 0
    file.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ValueError, match="конфигурация"):
        detectors.run_rules(nodes[1].id, path=path)


def test_audit_failure_rolls_back_whole_run(tmp_path):
    _, path, nodes = procedure(tmp_path, "В разумный срок, при необходимости")
    with connection(path) as con:
        con.execute("""CREATE TRIGGER fail_run BEFORE INSERT ON audit_log
                    WHEN NEW.action = 'Проверены формулировки процедуры'
                    BEGIN SELECT RAISE(ABORT, 'audit unavailable'); END""")
    with pytest.raises(sqlite3.IntegrityError):
        detectors.run_rules(nodes[1].id, path=path)
    assert list_risks(path) == []


def test_changed_edition_cannot_relabel_old_rule_evidence(tmp_path):
    _, path, nodes = procedure(tmp_path, "Решение в разумный срок")
    detectors.run_rules(nodes[1].id, path=path)
    old = list_risks(path)[0]
    new_file = tmp_path / "new-edition.docx"
    doc = Document()
    doc.add_paragraph("Решение в течение 10 дней")
    doc.save(new_file)
    parsed = parse_document(new_file, path)
    record_edition_change(nodes[2].id, source_ref=parsed.source.id, coordinate="абзац 1",
                          edition="Учебная редакция 2", quote=parsed.fragments[0].text,
                          rationale="Срок уточнён", path=path)
    for node in nodes[2:]:
        review(node.id, "confirmed", "Новая редакция проверена", path=path)
    with pytest.raises(ValueError, match="Основание автоматической"):
        review_risk(old.id, "confirmed", "Повторная проверка", path=path)
    assert list_risks(path)[0].rule_evidence == old.rule_evidence
    assert detectors.run_rules(nodes[1].id, path=path)["matched"] == 0
    review_risk(old.id, "rejected", "Формулировка исключена из новой редакции", path=path)
    assert list_risks(path)[0].status == "rejected"


def test_ui_run_and_registry_provenance(tmp_path, monkeypatch, qapp):
    import lotus.db as db
    from lotus.ui.function_page import FunctionPage
    from lotus.ui.risk_registry_page import RiskRegistryPage
    _, path, nodes = procedure(tmp_path, "Решение в разумный срок")
    monkeypatch.setattr(db, "DB_PATH", path)
    page = FunctionPage()
    page.refresh(nodes[1].id)
    page.rules_button.click()
    assert "Новых кандидатов в реестре: 1" in page.message.text()
    registry = RiskRegistryPage()
    registry.table.selectRow(0)
    assert "Найдено автоматически" in registry.detail.text()
    assert "F02_VAGUE_TERM" in registry.detail.text()
    assert "в разумный срок" in registry.detail.text()
    registry.origin_filter.setCurrentIndex(registry.origin_filter.findData("manual"))
    assert registry.table.rowCount() == 0
    registry.origin_filter.setCurrentIndex(registry.origin_filter.findData("auto"))
    assert registry.table.rowCount() == 1
    page.close()
    registry.close()
