"""Versioned teaching examples and explicitly justified practice links."""
import json
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict

from lotus.db import connection
from lotus.functions.models import Text, RiskRecord
from lotus.functions.service import migrate
from lotus.settings import ROOT, read_yaml
from lotus.sources import register_file

PRACTICE_FILE = ROOT / "data/seed/practice.yaml"


class PracticeCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Text
    code: Text
    title: Text
    sphere: Text
    function: Text
    circumstances: Text
    mechanism: Text
    conditions: Text
    controls: Text
    observable: Text
    limitations: Text
    source_ref: Text
    coordinate: Text
    edition: Text
    origin: Literal["manual"] = "manual"
    status: Literal["candidate"] = "candidate"
    material_type: Literal["teaching_example"] = "teaching_example"


class PracticeLink(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: Text
    risk_id: Text
    matching_condition: Text
    limitations: Text
    rationale: Text
    actor: Text
    reviewed_at: Text
    origin: Literal["manual"] = "manual"
    status: Literal["confirmed"] = "confirmed"


def migrate_practice(path=None):
    migrate(path)
    with connection(path) as con:
        con.execute('''CREATE TABLE IF NOT EXISTS function_practice_cases (
            id TEXT PRIMARY KEY, source_ref TEXT NOT NULL REFERENCES source_documents(id), payload TEXT NOT NULL)''')
        con.execute('''CREATE TABLE IF NOT EXISTS function_practice_links (
            case_id TEXT NOT NULL REFERENCES function_practice_cases(id),
            risk_id TEXT NOT NULL REFERENCES function_risks(id), payload TEXT NOT NULL,
            PRIMARY KEY(case_id, risk_id))''')
        con.execute("INSERT OR IGNORE INTO function_schema VALUES (3)")


def list_cases(path=None):
    migrate_practice(path)
    data = read_yaml(PRACTICE_FILE)
    source = register_file(PRACTICE_FILE, title="Учебные примеры организационных условий",
                           source_kind="practice_teaching", origin="synthetic_seed", db_path=path)
    cases = [PracticeCase(id=f"{row['code']}-{source.sha256[:12]}", **row,
                          source_ref=source.id, coordinate=f"cases[{index}]", edition=data["edition"])
             for index, row in enumerate(data["cases"])]
    with connection(path) as con:
        for case in cases:
            con.execute("INSERT OR IGNORE INTO function_practice_cases VALUES (?,?,?)",
                        (case.id, case.source_ref, case.model_dump_json()))
        # Include preserved versions so existing links remain inspectable after a seed update.
        return [PracticeCase.model_validate_json(row[0]) for row in
                con.execute("SELECT payload FROM function_practice_cases ORDER BY rowid")]


def list_links(*, risk_id=None, path=None):
    migrate_practice(path)
    with connection(path) as con:
        query = "SELECT payload FROM function_practice_links"
        rows = con.execute(query + " WHERE risk_id=?", (risk_id,)) if risk_id else con.execute(query)
        return [PracticeLink.model_validate_json(row[0]) for row in rows]


def save_link(case_id, risk_id, matching_condition, limitations, rationale, *, actor="Специалист", path=None):
    link = PracticeLink(case_id=case_id, risk_id=risk_id, matching_condition=matching_condition,
                        limitations=limitations, rationale=rationale, actor=actor,
                        reviewed_at=datetime.now(timezone.utc).isoformat())
    migrate_practice(path)
    with connection(path) as con:
        con.execute("BEGIN IMMEDIATE")
        if con.execute("SELECT 1 FROM function_practice_cases WHERE id=?", (case_id,)).fetchone() is None:
            raise ValueError("Учебный пример не найден")
        row = con.execute("SELECT payload FROM function_risks WHERE id=?", (risk_id,)).fetchone()
        if row is None:
            raise ValueError("Запись реестра не найдена")
        if RiskRecord.model_validate_json(row[0]).status == "rejected":
            raise ValueError("Нельзя добавлять аналогию к отклонённой записи")
        previous = con.execute("SELECT payload FROM function_practice_links WHERE case_id=? AND risk_id=?",
                               (case_id, risk_id)).fetchone()
        con.execute('''INSERT INTO function_practice_links VALUES (?,?,?)
                       ON CONFLICT(case_id,risk_id) DO UPDATE SET payload=excluded.payload''',
                    (case_id, risk_id, link.model_dump_json()))
        con.execute("INSERT INTO audit_log(actor,action,object_type,object_id,details) VALUES (?,?,?,?,?)",
                    (actor, "Обоснована связь с учебным примером", "practice_link", f"{case_id}/{risk_id}",
                     json.dumps({"previous": json.loads(previous[0]) if previous else None,
                                 "current": link.model_dump()}, ensure_ascii=False)))
    return link


def remove_link(case_id, risk_id, reason, *, actor="Специалист", path=None):
    if not reason.strip() or not actor.strip():
        raise ValueError("Укажите причину удаления связи и специалиста")
    migrate_practice(path)
    with connection(path) as con:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute("SELECT payload FROM function_practice_links WHERE case_id=? AND risk_id=?",
                          (case_id, risk_id)).fetchone()
        if row is None:
            raise ValueError("Связь не найдена")
        con.execute("DELETE FROM function_practice_links WHERE case_id=? AND risk_id=?", (case_id, risk_id))
        con.execute("INSERT INTO audit_log(actor,action,object_type,object_id,details) VALUES (?,?,?,?,?)",
                    (actor, "Удалена связь с учебным примером", "practice_link", f"{case_id}/{risk_id}",
                     json.dumps({"previous": json.loads(row[0]), "reason": reason.strip()}, ensure_ascii=False)))
