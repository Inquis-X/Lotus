import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4

from lotus.db import connection, init_db
from lotus.documents import parse_document
from lotus.functions.models import FunctionNode, RiskRecord
from lotus.sources import read_source, source_local_path
from lotus.settings import ROOT, read_yaml


def migrate(path=None):
    init_db(path)
    with connection(path) as con:
        con.execute("CREATE TABLE IF NOT EXISTS function_schema (version INTEGER PRIMARY KEY)")
        con.execute('''CREATE TABLE IF NOT EXISTS function_nodes (
            id TEXT PRIMARY KEY,
            parent_id TEXT REFERENCES function_nodes(id),
            source_ref TEXT NOT NULL REFERENCES source_documents(id),
            payload TEXT NOT NULL)''')
        con.execute("INSERT OR IGNORE INTO function_schema VALUES (1)")
        con.execute('''CREATE TABLE IF NOT EXISTS function_risks (
            id TEXT PRIMARY KEY,
            stage_id TEXT NOT NULL REFERENCES function_nodes(id),
            control_id TEXT REFERENCES function_nodes(id),
            source_ref TEXT NOT NULL REFERENCES source_documents(id),
            payload TEXT NOT NULL)''')
        con.execute("INSERT OR IGNORE INTO function_schema VALUES (2)")
        con.execute('''CREATE TABLE IF NOT EXISTS function_edition_changes (
            id TEXT PRIMARY KEY, stage_id TEXT NOT NULL REFERENCES function_nodes(id),
            source_ref TEXT NOT NULL REFERENCES source_documents(id), payload TEXT NOT NULL)''')
        con.execute("INSERT OR IGNORE INTO function_schema VALUES (4)")


def list_nodes(path=None):
    migrate(path)
    with connection(path) as con:
        return [FunctionNode.model_validate_json(row[0]) for row in
                con.execute("SELECT payload FROM function_nodes ORDER BY rowid")]


def _get(con, node_id):
    row = con.execute("SELECT payload FROM function_nodes WHERE id=?", (node_id,)).fetchone()
    if row is None:
        raise ValueError("Запись не найдена")
    return FunctionNode.model_validate_json(row[0])


def _audit(con, node, action, actor, details):
    con.execute("INSERT INTO audit_log(actor,action,object_type,object_id,details) VALUES (?,?,?,?,?)",
                (actor, action, "function_node", node.id, json.dumps(details, ensure_ascii=False)))


def _verify_evidence(node, path):
    source = read_source(node.source_ref, path)
    file = source_local_path(source) if source else None
    if file is None or not source.sha256:
        raise ValueError("Исходный файл недоступен для проверки цитаты")
    if hashlib.sha256(file.read_bytes()).hexdigest() != source.sha256:
        raise ValueError("Файл изменён. Зарегистрируйте новую редакцию отдельно")
    parsed = parse_document(file, path)
    categories = read_yaml(ROOT / "config/extraction.yaml")["special_categories"]
    if any(word.casefold() in fragment.text.casefold()
           for fragment in parsed.fragments for word in categories):
        raise ValueError("Материал исключён: признаки специальных категорий сведений")
    if not any(fragment.locator == node.coordinate and node.quote in fragment.text
               for fragment in parsed.fragments):
        raise ValueError("Цитата не найдена в указанном фрагменте источника")


def create_candidate(*, kind, title, source_ref, coordinate, edition, quote,
                     parent_id=None, department="", actor="Специалист", path=None):
    node = FunctionNode(id=str(uuid4()), kind=kind, title=title, parent_id=parent_id,
                        source_ref=source_ref, coordinate=coordinate, edition=edition, quote=quote,
                        department=department.strip() if kind == "function" else "")
    if not actor.strip():
        raise ValueError("Укажите специалиста")
    _verify_evidence(node, path)
    migrate(path)
    with connection(path) as con:
        expected = {"procedure": "function", "stage": "procedure", "role": "stage", "control": "stage"}.get(kind)
        if expected:
            parent = _get(con, parent_id)
            if parent.kind != expected or parent.status == "rejected":
                raise ValueError("Выберите родительскую запись подходящего типа")
        elif parent_id is not None:
            raise ValueError("Функция не имеет родительской записи")
        con.execute("INSERT INTO function_nodes VALUES (?,?,?,?)",
                    (node.id, node.parent_id, node.source_ref, node.model_dump_json()))
        _audit(con, node, "Создан кандидат функции или этапа", actor, {"kind": kind, "origin": node.origin})
    return node


def assign_department(function_id, department, *, actor="Специалист", path=None):
    department = department.strip()
    if not department or not actor.strip():
        raise ValueError("Укажите подразделение и специалиста")
    migrate(path)
    with connection(path) as con:
        con.execute("BEGIN IMMEDIATE")
        node = _get(con, function_id)
        if node.kind != "function":
            raise ValueError("Подразделение указывается для функции")
        if node.department != department:
            previous, node.department = node.department, department
            con.execute("UPDATE function_nodes SET payload=? WHERE id=?", (node.model_dump_json(), node.id))
            _audit(con, node, "Указано подразделение администрации", actor,
                   {"previous": previous, "department": department})


def review(node_id, decision, rationale, *, actor="Специалист", path=None):
    if decision not in {"confirmed", "rejected"} or not rationale.strip() or not actor.strip():
        raise ValueError("Нужны решение, обоснование и специалист")
    migrate(path)
    # Verify the immutable source before entering the write transaction.
    with connection(path) as con:
        snapshot = _get(con, node_id)
    if decision == "confirmed":
        _verify_evidence(snapshot, path)
    with connection(path) as con:
        con.execute("BEGIN IMMEDIATE")
        node = _get(con, node_id)
        if decision == "confirmed" and node.parent_id:
            if _get(con, node.parent_id).status != "confirmed":
                raise ValueError("Сначала подтвердите родительскую запись")
        if decision == "rejected":
            linked = con.execute("SELECT payload FROM function_risks WHERE stage_id=? OR control_id=?", (node.id, node.id))
            if any(RiskRecord.model_validate_json(row[0]).status == "confirmed" for row in linked):
                raise ValueError("Сначала пересмотрите подтверждённые записи реестра")
            children = con.execute("SELECT payload FROM function_nodes WHERE parent_id=?", (node.id,))
            if any(FunctionNode.model_validate_json(row[0]).status == "confirmed" for row in children):
                raise ValueError("Сначала пересмотрите подтверждённые дочерние записи")
        previous = node.status
        node.status, node.rationale, node.actor = decision, rationale.strip(), actor.strip()
        node.reviewed_at = datetime.now(timezone.utc).isoformat()
        con.execute("UPDATE function_nodes SET payload=? WHERE id=?", (node.model_dump_json(), node.id))
        _audit(con, node, "Проверка функции или этапа", actor,
               {"previous": previous, "status": decision, "rationale": node.rationale})
    return node


def reset_review(source_ref, *, actor="Специалист", path=None):
    """Remove all records of one source document together with their review decisions."""
    if not actor.strip():
        raise ValueError("Укажите специалиста")
    migrate(path)
    with connection(path) as con:
        con.execute("BEGIN IMMEDIATE")
        ids = [row[0] for row in con.execute("SELECT id FROM function_nodes WHERE source_ref=?", (source_ref,))]
        if not ids:
            raise ValueError("Записей выбранного документа нет")
        marks = ",".join("?" for _ in ids)
        risk_ids = [row[0] for row in con.execute(
            f"SELECT id FROM function_risks WHERE stage_id IN ({marks}) OR control_id IN ({marks})",
            (*ids, *ids))]
        links = 0
        if risk_ids and con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='function_practice_links'").fetchone():
            risk_marks = ",".join("?" for _ in risk_ids)
            links = con.execute(
                f"SELECT COUNT(*) FROM function_practice_links WHERE risk_id IN ({risk_marks})", risk_ids).fetchone()[0]
            con.execute(f"DELETE FROM function_practice_links WHERE risk_id IN ({risk_marks})", risk_ids)
            con.execute(f"DELETE FROM function_risks WHERE id IN ({risk_marks})", risk_ids)
        con.execute(f"DELETE FROM function_edition_changes WHERE stage_id IN ({marks})", ids)
        con.execute(f"DELETE FROM function_nodes WHERE id IN ({marks})", ids)
        con.execute("INSERT INTO audit_log(actor,action,object_type,object_id,details) VALUES (?,?,?,?,?)",
                    (actor.strip(), "Сброшена проверка записей документа", "function_source", source_ref,
                     json.dumps({"nodes": len(ids), "risks": len(risk_ids), "practice_links": links},
                                ensure_ascii=False)))
    return {"nodes": len(ids), "risks": len(risk_ids), "practice_links": links}


def confirmed_procedure(procedure_id, path=None):
    nodes = list_nodes(path)
    by_id = {node.id: node for node in nodes}
    procedure = by_id.get(procedure_id)
    if procedure is None or procedure.kind != "procedure":
        raise ValueError("Процедура не найдена")
    stages = [node for node in nodes if node.parent_id == procedure_id and node.status != "rejected"]
    stage_ids = {node.id for node in stages}
    related = [node for node in nodes if node.parent_id in stage_ids and node.status != "rejected"]
    chain = [by_id[procedure.parent_id], procedure, *stages, *related]
    if not stages or any(node.status != "confirmed" for node in chain):
        raise ValueError("Подтвердите функцию, процедуру, этапы, роли и контроли")
    for node in chain:
        _verify_evidence(node, path)
    return chain


def list_risks(path=None):
    migrate(path)
    with connection(path) as con:
        return [RiskRecord.model_validate_json(row[0]) for row in
                con.execute("SELECT payload FROM function_risks ORDER BY rowid")]


def _risk_dependencies(con, stage_id, control_id):
    stage = _get(con, stage_id)
    if stage.kind != "stage":
        raise ValueError("Выберите этап процедуры")
    procedure = _get(con, stage.parent_id)
    function = _get(con, procedure.parent_id)
    dependencies = [function, procedure, stage]
    if control_id:
        control = _get(con, control_id)
        if control.kind != "control" or control.parent_id != stage_id:
            raise ValueError("Контроль должен относиться к выбранному этапу")
        dependencies.append(control)
    if any(node.status != "confirmed" for node in dependencies):
        raise ValueError("Сначала подтвердите функцию, процедуру, этап и выбранный контроль")
    return dependencies


def _risk_audit(con, record, action, actor, details):
    con.execute("INSERT INTO audit_log(actor,action,object_type,object_id,details) VALUES (?,?,?,?,?)",
                (actor, action, "function_risk", record.id, json.dumps(details, ensure_ascii=False)))


def create_risk(*, stage_id, control_id=None, vulnerability, control_limitation,
                proposed_measure, actor="Специалист", path=None):
    if not actor.strip():
        raise ValueError("Укажите специалиста")
    migrate(path)
    with connection(path) as con:
        dependencies = _risk_dependencies(con, stage_id, control_id)
    for node in dependencies:
        _verify_evidence(node, path)
    stage = dependencies[2]
    record = RiskRecord(id=str(uuid4()), stage_id=stage_id, control_id=control_id,
                        vulnerability=vulnerability, control_limitation=control_limitation,
                        proposed_measure=proposed_measure, source_ref=stage.source_ref,
                        coordinate=stage.coordinate, edition=stage.edition, quote=stage.quote)
    with connection(path) as con:
        con.execute("BEGIN IMMEDIATE")
        _risk_dependencies(con, stage_id, control_id)
        # A repeated submission must not create a second identical finding.
        for row in con.execute("SELECT payload FROM function_risks WHERE stage_id=?", (stage_id,)):
            existing = RiskRecord.model_validate_json(row[0])
            fields = ("stage_id", "control_id", "vulnerability", "control_limitation", "proposed_measure")
            if all(getattr(existing, key) == getattr(record, key) for key in fields):
                raise ValueError("Такая запись уже существует в реестре")
        con.execute("INSERT INTO function_risks VALUES (?,?,?,?,?)",
                    (record.id, stage_id, control_id, record.source_ref, record.model_dump_json()))
        _risk_audit(con, record, "Создана запись реестра функций", actor,
                    {"stage_id": stage_id, "origin": record.origin})
    return record


def review_risk(record_id, decision, rationale, *, actor="Специалист", path=None):
    if decision not in {"confirmed", "rejected"} or not rationale.strip() or not actor.strip():
        raise ValueError("Нужны решение, обоснование и специалист")
    migrate(path)
    with connection(path) as con:
        row = con.execute("SELECT payload FROM function_risks WHERE id=?", (record_id,)).fetchone()
        if row is None:
            raise ValueError("Запись реестра не найдена")
        record = RiskRecord.model_validate_json(row[0])
        dependencies = _risk_dependencies(con, record.stage_id, record.control_id) if decision == "confirmed" else []
    for node in dependencies:
        _verify_evidence(node, path)
    with connection(path) as con:
        con.execute("BEGIN IMMEDIATE")
        record = RiskRecord.model_validate_json(con.execute(
            "SELECT payload FROM function_risks WHERE id=?", (record_id,)).fetchone()[0])
        if decision == "confirmed":
            _risk_dependencies(con, record.stage_id, record.control_id)
        previous = record.status
        previous_record = record.model_dump()
        if decision == "confirmed":
            stage = _get(con, record.stage_id)
            if record.origin == "auto" and any(getattr(record, field) != getattr(stage, field)
                    for field in ("source_ref", "coordinate", "edition", "quote")):
                raise ValueError("Основание автоматической находки изменилось. Отклоните прежнюю запись и повторно запустите правила")
            record.source_ref, record.coordinate = stage.source_ref, stage.coordinate
            record.edition, record.quote = stage.edition, stage.quote
        record.needs_review = False
        record.status, record.rationale, record.actor = decision, rationale.strip(), actor.strip()
        record.reviewed_at = datetime.now(timezone.utc).isoformat()
        con.execute("UPDATE function_risks SET source_ref=?,payload=? WHERE id=?",
                    (record.source_ref, record.model_dump_json(), record.id))
        _risk_audit(con, record, "Проверка записи реестра функций", actor,
                    {"previous": previous, "previous_record": previous_record,
                     "current_record": record.model_dump(), "status": decision, "rationale": record.rationale})
    return record


def record_edition_change(stage_id, *, source_ref, coordinate, edition, quote, rationale,
                          actor="Специалист", path=None):
    if not rationale.strip() or not actor.strip():
        raise ValueError("Укажите обоснование изменения и специалиста")
    migrate(path)
    with connection(path) as con:
        before = _get(con, stage_id)
    if before.kind != "stage" or before.status == "rejected":
        raise ValueError("Выберите неотклонённый этап процедуры")
    proposed = FunctionNode(**(before.model_dump() | {
        "source_ref": source_ref, "coordinate": coordinate, "edition": edition, "quote": quote,
        "status": "candidate", "origin": "manual", "rationale": "", "actor": "", "reviewed_at": None}))
    if proposed.source_ref == before.source_ref or proposed.edition == before.edition:
        raise ValueError("Нужны отдельный файл с изменённым содержимым и другая редакция")
    _verify_evidence(proposed, path)
    with connection(path) as con:
        con.execute("BEGIN IMMEDIATE")
        if _get(con, stage_id) != before:
            raise ValueError("Этап изменился. Обновите список и повторите действие")
        children = [FunctionNode.model_validate_json(row[0]) for row in
                    con.execute("SELECT payload FROM function_nodes WHERE parent_id=?", (stage_id,))]
        risks = [RiskRecord.model_validate_json(row[0]) for row in
                 con.execute("SELECT payload FROM function_risks WHERE stage_id=?", (stage_id,))]
        change = {"id": str(uuid4()), "stage_id": stage_id, "before": before.model_dump(),
                  "after": proposed.model_dump(), "previous_children": [node.model_dump() for node in children],
                  "previous_risks": [risk.model_dump() for risk in risks], "rationale": rationale.strip(),
                  "actor": actor.strip(), "created_at": datetime.now(timezone.utc).isoformat(), "origin": "manual"}
        con.execute("INSERT INTO function_edition_changes VALUES (?,?,?,?)",
                    (change["id"], stage_id, proposed.source_ref, json.dumps(change, ensure_ascii=False)))
        con.execute("UPDATE function_nodes SET source_ref=?,payload=? WHERE id=?",
                    (proposed.source_ref, proposed.model_dump_json(), stage_id))
        for node in children:
            if node.status != "rejected":
                node.status, node.rationale, node.actor, node.reviewed_at = "candidate", "", "", None
                con.execute("UPDATE function_nodes SET payload=? WHERE id=?", (node.model_dump_json(), node.id))
        for risk in risks:
            if risk.status != "rejected":
                risk.needs_review = True
                con.execute("UPDATE function_risks SET payload=? WHERE id=?", (risk.model_dump_json(), risk.id))
        _audit(con, proposed, "Зафиксирована новая редакция этапа", actor, change)
    return change


def edition_history(stage_id, path=None):
    migrate(path)
    with connection(path) as con:
        return [json.loads(row[0]) for row in con.execute(
            "SELECT payload FROM function_edition_changes WHERE stage_id=? ORDER BY rowid", (stage_id,))]
