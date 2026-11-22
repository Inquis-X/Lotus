"""Explicit, source-backed template extraction; never approves candidates."""
import hashlib
import json
import re
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict

from lotus.db import connection
from lotus.documents import ParsedDocument, parse_document
from lotus.functions.models import FunctionNode, Text
from lotus.functions.service import migrate, _audit
from lotus.settings import ROOT, read_yaml
from lotus.sources import read_source, source_local_path

CONFIG_PATH = ROOT / "config/function_extraction.yaml"
PARENTS = {"function": None, "procedure": "function", "stage": "procedure", "role": "stage", "control": "stage"}


class ExtractionBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_ref: Text
    edition: Text
    template_hash: Text
    candidates: list[FunctionNode]
    ignored_lines: int


def numbered_clause(line, style, config):
    kind = config.get("clause_styles", {}).get(style)
    if kind is None:
        return None
    match = re.fullmatch(config["clause_pattern"], line)
    if not match:
        return None
    key, title = match.group("key", "title")
    parent, _, _ = key.rpartition(".")
    fields = {"key": key, "parent": parent or None, "title": title, "department": ""}
    if kind == "function":
        wording = re.fullmatch(config["function_wording"], title)
        if wording:
            fields.update(wording.groupdict())
    return kind, fields


def extract(document: ParsedDocument, edition: str):
    edition = edition.strip()
    if not edition:
        raise ValueError("Укажите редакцию документа")
    if document.format != "docx":
        raise ValueError("Шаблонное извлечение пока поддерживает только абзацы DOCX")
    categories = read_yaml(ROOT / "config/extraction.yaml")["special_categories"]
    if any(word.casefold() in fragment.text.casefold()
           for fragment in document.fragments for word in categories):
        raise ValueError("Материал исключён: признаки специальных категорий сведений")
    config = read_yaml(CONFIG_PATH)
    if set(config.get("templates", {})) != set(PARENTS):
        raise ValueError("В конфигурации нужны шаблоны функции, процедуры, этапа, роли и контроля")
    try:
        patterns = {kind: re.compile(pattern) for kind, pattern in config["templates"].items()}
    except re.error as exc:
        raise ValueError("Ошибка регулярного выражения в шаблоне извлечения") from exc
    template_hash = hashlib.sha256(CONFIG_PATH.read_bytes()).hexdigest()
    rows, ignored = {}, 0
    for fragment in document.fragments:
        for raw in fragment.text.splitlines():
            line = raw.strip()
            if not line:
                continue
            matches = [(kind, match.groupdict()) for kind, pattern in patterns.items()
                       if (match := pattern.fullmatch(line))]
            clause = numbered_clause(line, fragment.paragraph_style, config)
            if clause:
                matches.append(clause)
            if not matches:
                ignored += 1
                continue
            if len(matches) != 1:
                raise ValueError("Неоднозначное совпадение шаблонов")
            kind, fields = matches[0]
            key, title = fields.get("key"), fields.get("title", "").strip()
            if not key or not title:
                raise ValueError("Шаблон должен содержать непустые key и title")
            if key in rows:
                raise ValueError(f"Повтор идентификатора {key}; уточните разметку документа")
            rows[key] = {"kind": kind, "title": title, "parent": fields.get("parent"),
                         "coordinate": fragment.locator, "quote": line, "department": fields.get("department", "")}
    for key, row in rows.items():
        parent_kind = PARENTS[row["kind"]]
        if parent_kind and (row["parent"] not in rows or rows[row["parent"]]["kind"] != parent_kind):
            raise ValueError(f"Для {key} отсутствует явная ссылка на родителя подходящего типа в этом документе")
        if not parent_kind and row["parent"]:
            raise ValueError("Функция не должна ссылаться на родительскую запись")
    ids = {key: str(uuid5(NAMESPACE_URL, json.dumps([document.source.id, edition, key], ensure_ascii=False))) for key in rows}
    candidates = []
    for kind in PARENTS:  # Parent types always precede their children.
        for key, row in rows.items():
            if row["kind"] == kind:
                candidates.append(FunctionNode(id=ids[key], kind=kind, title=row["title"],
                    department=row["department"], parent_id=ids.get(row["parent"]), source_ref=document.source.id,
                    edition=edition, coordinate=row["coordinate"], quote=row["quote"], origin="auto"))
    return ExtractionBatch(source_ref=document.source.id, edition=edition, template_hash=template_hash,
                           candidates=candidates, ignored_lines=ignored)


def save_extraction(batch: ExtractionBatch, *, actor="Специалист", path=None):
    if not actor.strip():
        raise ValueError("Укажите специалиста")
    if not batch.candidates:
        raise ValueError("Кандидаты по шаблону не найдены")
    # Reparse and recompute to reject stale previews and modified templates.
    source = read_source(batch.source_ref, path)
    file = source_local_path(source) if source else None
    if file is None or hashlib.sha256(file.read_bytes()).hexdigest() != source.sha256:
        raise ValueError("Источник изменён или недоступен. Повторите извлечение")
    current = extract(parse_document(file, path), batch.edition)
    if current != batch:
        raise ValueError("Предпросмотр изменён или устарел. Повторите извлечение")
    migrate(path)
    created = 0
    with connection(path) as con:
        con.execute("BEGIN IMMEDIATE")
        for node in batch.candidates:
            row = con.execute("SELECT payload FROM function_nodes WHERE id=?", (node.id,)).fetchone()
            if row:
                existing = FunctionNode.model_validate_json(row[0])
                immutable = ("kind", "parent_id", "title", "source_ref", "coordinate", "edition", "quote", "origin")
                if any(getattr(existing, key) != getattr(node, key) for key in immutable):
                    raise ValueError("Ранее извлечённая запись уже изменена. Повторный импорт отменён")
                continue  # Preserve prior human decisions, including rejection.
            con.execute("INSERT INTO function_nodes VALUES (?,?,?,?)",
                        (node.id, node.parent_id, node.source_ref, node.model_dump_json()))
            _audit(con, node, "Извлечён кандидат по шаблону", actor,
                   {"template_sha256": batch.template_hash, "origin": "auto", "status": "candidate"})
            created += 1
    return created
