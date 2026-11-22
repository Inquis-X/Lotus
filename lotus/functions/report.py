"""Verified snapshots and DOCX drafts of the municipal function risk map."""
from datetime import datetime, timezone
import hashlib

from docx import Document
from docx.shared import Cm, Pt, RGBColor

from lotus.audit import log
from lotus.db import connection
from lotus.functions.models import RiskRecord
from lotus.functions.service import migrate, _risk_dependencies, _verify_evidence
from lotus.report import as_bytes
from lotus.sources import read_source


def prepare_snapshot(record_ids, *, actor="Специалист", path=None):
    if not record_ids or len(record_ids) != len(set(record_ids)):
        raise ValueError("Выберите хотя бы одну запись без повторов")
    if not actor.strip():
        raise ValueError("Укажите специалиста")
    migrate(path)
    entries = []
    with connection(path) as con:
        con.execute("BEGIN")
        for record_id in record_ids:
            row = con.execute("SELECT payload FROM function_risks WHERE id=?", (record_id,)).fetchone()
            if row is None:
                raise ValueError("Запись реестра не найдена")
            record = RiskRecord.model_validate_json(row[0])
            if record.status != "confirmed" or record.needs_review or not record.rationale.strip():
                raise ValueError("В проект включаются только подтверждённые записи с обоснованием")
            nodes = _risk_dependencies(con, record.stage_id, record.control_id)
            entries.append({"record": record.model_dump(), "nodes": [node.model_dump() for node in nodes]})
    sources = {}
    for entry in entries:
        from lotus.functions.models import FunctionNode
        for data in entry["nodes"]:
            node = FunctionNode.model_validate(data)
            _verify_evidence(node, path)
            source = read_source(node.source_ref, path)
            sources[node.source_ref] = source.model_dump(mode="json")
    return {"created_at": datetime.now(timezone.utc).isoformat(), "actor": actor.strip(),
            "status": "draft", "entries": entries, "sources": sources}


def snapshot_preview(snapshot):
    lines = ["ПРОЕКТ · Требует проверки и утверждения", f"Записей: {len(snapshot['entries'])}"]
    for entry in snapshot["entries"]:
        record, nodes = entry["record"], entry["nodes"]
        lines.extend([f"{nodes[0]['title']} / {nodes[2]['title']}",
                      f"Уязвимость: {record['vulnerability']}",
                      f"Мера: {record['proposed_measure']}",
                      f"Основание: {record['coordinate']} · редакция {record['edition']}",
                      f"Обоснование специалиста: {record['rationale']}", ""])
    return "\n".join(lines)


def render_snapshot(snapshot):
    doc = Document()
    section = doc.sections[0]
    section.page_width, section.page_height = Cm(21), Cm(29.7)
    section.top_margin = section.bottom_margin = Cm(2)
    section.left_margin = section.right_margin = Cm(2.2)
    for name in ("Normal", "Title", "Heading 1", "Heading 2"):
        style = doc.styles[name]
        style.font.name = "Arial"
        style.font.color.rgb = RGBColor(0, 0, 0)
    doc.styles["Normal"].font.size = Pt(11)
    doc.styles["Normal"].paragraph_format.space_after = Pt(6)
    doc.add_paragraph("Проект карты коррупционных рисков", "Title")
    doc.add_paragraph("ЛОТОС · Демонстрационные материалы")
    doc.add_paragraph("Проект предназначен для проверки специалистом и последующего утверждения. "
                      "Он содержит выбранные подтверждённые оценки уязвимостей функций и предложения по их минимизации. "
                      "Подтверждение оценки не означает установления нарушения.")
    doc.add_paragraph(f"Сформировал: {snapshot['actor']}. Дата среза (UTC): {snapshot['created_at']}.")
    doc.add_paragraph(f"Включено записей: {len(snapshot['entries'])}. Происхождение указано для каждой записи.")
    section.footer.paragraphs[0].text = "Проект · Требует проверки и утверждения · Решение принимает специалист"
    numbers = {}

    def reference(node):
        key = (node["source_ref"], node["edition"])
        if key not in numbers:
            numbers[key] = len(numbers) + 1
        return f"[И{numbers[key]}]"

    for number, entry in enumerate(snapshot["entries"], 1):
        record, nodes = entry["record"], entry["nodes"]
        function, procedure, stage = nodes[:3]
        doc.add_heading(f"{number} Оценка функции", 1)
        doc.add_paragraph(f"Запись: {record['id']}. Статус: подтверждено специалистом.")
        doc.add_paragraph("Происхождение: " + ("найдено автоматически." if record['origin'] == 'auto' else "внесено вручную."))
        if record.get("rule_evidence"):
            rule = record["rule_evidence"]
            doc.add_paragraph(f"Правило: {rule['rule_id']} · версия {rule['version']} · порог {rule['min_occurrences']}.\n"
                              f"SHA-256 правил: {rule['config_sha256']}")
            for match in rule["matches"]:
                doc.add_paragraph(f"Совпадение: «{match['text']}» · символы {match['start'] + 1}–{match['end']} в цитате этапа.")
        doc.add_paragraph(f"Функция: {function['title']}. Процедура: {procedure['title']}. Этап: {stage['title']}.")
        doc.add_heading("Уязвимость и контроль", 2)
        doc.add_paragraph(record["vulnerability"])
        doc.add_paragraph("Действующий контроль: " + (nodes[3]["title"] if len(nodes) > 3 else
                          "не установлен по представленным данным"))
        doc.add_paragraph(f"Ограничение контроля или данных: {record['control_limitation']}")
        doc.add_heading("Предлагаемая мера", 2)
        doc.add_paragraph(record["proposed_measure"])
        doc.add_heading("Решение специалиста", 2)
        doc.add_paragraph(f"{record['actor']} · {record['reviewed_at']}\n{record['rationale']}")
        doc.add_heading("Документальные основания", 2)
        labels = ["Функция", "Процедура", "Этап", "Контроль"]
        for label, node in zip(labels, nodes):
            doc.add_paragraph(f"{label}: {reference(node)} · {node['coordinate']} · редакция {node['edition']}")
            doc.add_paragraph(node["quote"])
    doc.add_heading("Реестр источников", 1)
    for (source_id, edition), number in numbers.items():
        source = snapshot["sources"][source_id]
        doc.add_paragraph(f"[И{number}] {source['title']} · редакция {edition}.")
        doc.add_paragraph(f"Источник: {source_id}. Происхождение: {source['origin']}.\n"
                          f"SHA-256: {source['sha256']}\nПуть: {source['uri']}")
    doc.add_heading("Ограничения проекта", 1)
    doc.add_paragraph("Оценка ограничена выбранными записями и указанными редакциями документов. "
                      "Меры являются предложениями. Ответственные подразделения и сроки исполнения "
                      "в этом проекте не назначены. При изменении оснований требуется повторная проверка. "
                      "Автоматический поиск формулировок, если использован, ограничен подтверждёнными цитатами этапов. "
                      "Его демонстрационные правила требуют калибровки и не заменяют проверку полного контекста специалистом.")
    return as_bytes(doc)


def build_report(record_ids, *, actor="Специалист", path=None):
    snapshot = prepare_snapshot(record_ids, actor=actor, path=path)
    content = render_snapshot(snapshot)
    digest = hashlib.sha256(content).hexdigest()
    log("Сформирован проект карты рисков", "risk_map_draft", digest,
        {"records": record_ids, "created_at": snapshot["created_at"], "status": "draft"}, actor=actor, path=path)
    return content, snapshot
