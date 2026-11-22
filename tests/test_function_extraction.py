import sqlite3

import pytest
from docx import Document

from lotus.audit import read_log
from lotus.db import connection
from lotus.documents import parse_document
from lotus.functions.extraction import extract, save_extraction
from lotus.functions.service import list_nodes, review, confirmed_procedure

LINES = [
    "Функция [F01]: Учебная функция",
    "Процедура [P01] функции [F01]: Учебная процедура",
    "Этап [S01] процедуры [P01]: Подготовка решения",
    "Роль [R01] этапа [S01]: Учебный специалист",
    "Контроль [C01] этапа [S01]: Согласование проекта",
]


def material(tmp_path, lines):
    file = tmp_path / "template.docx"
    doc = Document()
    for line in lines:
        doc.add_paragraph(line)
    doc.save(file)
    database = tmp_path / "extraction.sqlite"
    return file, database, parse_document(file, database)


def test_template_extraction_is_deterministic_pending_and_idempotent(tmp_path):
    _, path, parsed = material(tmp_path, list(reversed(LINES)))
    batch = extract(parsed, "Редакция 1")
    assert batch == extract(parsed, "Редакция 1")
    assert [node.kind for node in batch.candidates] == ["function", "procedure", "stage", "role", "control"]
    assert save_extraction(batch, path=path) == 5
    nodes = list_nodes(path)
    assert all(node.origin == "auto" and node.status == "candidate" for node in nodes)
    assert nodes[0].coordinate == "абзац 5"
    with pytest.raises(ValueError):
        confirmed_procedure(nodes[1].id, path)
    review(nodes[0].id, "confirmed", "Цитата проверена", path=path)
    assert save_extraction(batch, path=path) == 0
    assert list_nodes(path)[0].status == "confirmed"
    assert len([r for r in read_log(path) if r["action"] == "Извлечён кандидат по шаблону"]) == 5


def test_template_trap_ignores_unmarked_and_negated_text(tmp_path):
    _, path, parsed = material(tmp_path, ["Функция предоставления участков описана в документе.",
                                         "Не Функция [F01]: Отрицательный пример", "Критерии определены, срок указан."])
    batch = extract(parsed, "Редакция 1")
    assert batch.candidates == []
    assert batch.ignored_lines == 3
    assert list_nodes(path) == []


@pytest.mark.parametrize("lines", [LINES + [LINES[0]], [LINES[2]],
                                   [LINES[0], "Этап [S01] процедуры [F01]: Неверный тип родителя"]])
def test_template_rejects_duplicates_and_broken_links(tmp_path, lines):
    _, path, parsed = material(tmp_path, lines)
    with pytest.raises(ValueError):
        extract(parsed, "Редакция 1")
    assert list_nodes(path) == []


def test_template_stale_preview_and_audit_failure_leave_no_candidates(tmp_path):
    file, path, parsed = material(tmp_path, LINES)
    batch = extract(parsed, "Редакция 1")
    with connection(path) as con:
        con.execute("""CREATE TRIGGER fail_extract BEFORE INSERT ON audit_log
                       BEGIN SELECT RAISE(ABORT, 'audit unavailable'); END""")
    with pytest.raises(sqlite3.IntegrityError):
        save_extraction(batch, path=path)
    assert list_nodes(path) == []
    file.write_bytes(b"changed")
    with pytest.raises(ValueError, match="изменён"):
        save_extraction(batch, path=path)


def test_template_filters_sensitive_text_and_requires_edition(tmp_path):
    _, _, parsed = material(tmp_path, LINES + ["Учебный диагноз указан в постороннем фрагменте"])
    with pytest.raises(ValueError, match="редакцию"):
        extract(parsed, " ")
    with pytest.raises(ValueError, match="исключён"):
        extract(parsed, "Редакция 1")


def test_template_changes_and_tampered_preview_rejected(tmp_path, monkeypatch):
    import lotus.functions.extraction as extraction
    _, path, parsed = material(tmp_path, LINES)
    config = tmp_path / "templates.yaml"
    config.write_bytes(extraction.CONFIG_PATH.read_bytes())
    monkeypatch.setattr(extraction, "CONFIG_PATH", config)
    batch = extract(parsed, "Редакция 1")
    changed = batch.model_copy(deep=True)
    changed.candidates[0].title = "Изменённый текст"
    with pytest.raises(ValueError, match="предпросмотр|Предпросмотр"):
        save_extraction(changed, path=path)
    config.write_text(config.read_text(encoding="utf-8") + "\n# новая версия\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Предпросмотр"):
        save_extraction(batch, path=path)
    assert list_nodes(path) == []


def test_extraction_ui_preview_save_and_manual_review(tmp_path, monkeypatch, qapp):
    from PySide6.QtWidgets import QDialog, QPushButton
    from lotus.ui.function_page import FunctionPage
    import lotus.db as db
    _, path, parsed = material(tmp_path, LINES)
    monkeypatch.setattr(db, "DB_PATH", path)
    page = FunctionPage()
    page.document = parsed
    assert not page.load_button.isEnabled()
    page.privacy_check.setChecked(True)
    assert page.load_button.isEnabled()
    page.edition.setText("Редакция 1")

    def accept(dialog):
        dialog.findChild(QPushButton, "saveExtraction").click()
        return dialog.result()

    monkeypatch.setattr(QDialog, "exec", accept)
    page.extract_button.click()
    assert page.table.rowCount() == 5
    assert all(node.status == "candidate" for node in page.nodes)
    page.rationale.setText("Проверено по исходному документу")
    page.confirm_button.click()
    assert page.nodes[0].status == "confirmed"
    page.extract_button.click()
    assert page.table.rowCount() == 5
    assert page.nodes[0].status == "confirmed"
    page.close()
