"""Deterministic phrase checks over confirmed stage quotations only."""
import hashlib
import json
import re
from uuid import NAMESPACE_URL, uuid5

import yaml
from pydantic import BaseModel, ConfigDict, Field

from lotus.db import connection
from lotus.functions.models import FunctionNode, RiskRecord, RuleEvidence, PhraseMatch, Text
from lotus.functions.service import confirmed_procedure, _risk_audit, _audit
from lotus.settings import ROOT

CONFIG_PATH = ROOT / "config/rules.yaml"


class PhraseRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Text
    enabled: bool
    phrase: Text
    lexemes: list[list[Text]]
    window: int = Field(ge=2, strict=True)
    min_occurrences: int = Field(ge=1, strict=True)
    exclude_patterns: list[str]
    vulnerability: Text
    control_limitation: Text
    proposed_measure: Text


class PhraseRules(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Text
    disclaimer: Text
    rules: list[PhraseRule]


def load_phrase_rules():
    raw = CONFIG_PATH.read_bytes()
    try:
        config = PhraseRules.model_validate(yaml.safe_load(raw)["function_rules"])
        if len({rule.id for rule in config.rules}) != len(config.rules):
            raise ValueError("Идентификаторы правил повторяются")
        for rule in config.rules:
            forms = [form.casefold() for group in rule.lexemes for form in group]
            if not rule.lexemes or any(not group for group in rule.lexemes) or len(set(forms)) != len(forms):
                raise ValueError("Группы словоформ пусты или пересекаются")
            for pattern in rule.exclude_patterns:
                re.compile(pattern)
    except (ValueError, KeyError, TypeError, yaml.YAMLError, re.error) as exc:
        raise ValueError("Некорректная конфигурация правил формулировок") from exc
    return config, hashlib.sha256(raw).hexdigest()


def phrase_matches(quote, rule):
    # Match one token per lexeme group within a token window, in any order;
    # preserve original character offsets and spelling in the evidence.
    tokens = list(re.finditer(r"\w+", quote))
    forms = [{form.casefold() for form in group} for group in rule.lexemes]
    excluded = [match.span() for expression in rule.exclude_patterns
                for match in re.finditer(expression, quote, re.IGNORECASE)]
    matches, spans = [], set()
    for anchor, token in enumerate(tokens):
        if token.group().casefold() not in forms[0]:
            continue
        chosen = {0: anchor}
        for group in range(1, len(forms)):
            nearest = min((index for index in range(len(tokens))
                           if index not in chosen.values() and tokens[index].group().casefold() in forms[group]),
                          key=lambda index: (abs(index - anchor), index), default=None)
            if nearest is None:
                break
            chosen[group] = nearest
        else:
            first, last = min(chosen.values()), max(chosen.values())
            if last - first + 1 > rule.window:
                continue
            start, end = tokens[first].start(), tokens[last].end()
            if (start, end) in spans or any(left <= start and end <= right for left, right in excluded):
                continue
            spans.add((start, end))
            matches.append(PhraseMatch(start=start, end=end, text=quote[start:end]))
    return matches


def run_rules(procedure_id, *, actor="Специалист", path=None):
    if not actor.strip():
        raise ValueError("Укажите специалиста")
    config, digest = load_phrase_rules()
    chain = confirmed_procedure(procedure_id, path)
    if any(not node.rationale.strip() for node in chain):
        raise ValueError("Подтверждение каждого элемента должно иметь обоснование")
    candidates = []
    stages = [node for node in chain if node.kind == "stage"]
    for stage in stages:
        for rule in config.rules:
            if not rule.enabled:
                continue
            matches = phrase_matches(stage.quote, rule)
            if len(matches) < rule.min_occurrences:
                continue
            evidence = RuleEvidence(rule_id=rule.id, version=config.version, config_sha256=digest,
                                    phrase=rule.phrase, min_occurrences=rule.min_occurrences,
                                    exclude_patterns=rule.exclude_patterns, matches=matches)
            key = [stage.id, stage.source_ref, stage.edition, stage.coordinate, stage.quote, rule.id, digest]
            candidates.append(RiskRecord(id=str(uuid5(NAMESPACE_URL, json.dumps(key, ensure_ascii=False))),
                stage_id=stage.id, vulnerability=rule.vulnerability,
                control_limitation=rule.control_limitation, proposed_measure=rule.proposed_measure,
                source_ref=stage.source_ref, coordinate=stage.coordinate, edition=stage.edition,
                quote=stage.quote, origin="auto", rule_evidence=evidence))
    created = 0
    with connection(path) as con:
        con.execute("BEGIN IMMEDIATE")
        # Include new pending children as well: a concurrent change invalidates this run.
        nodes = [FunctionNode.model_validate_json(row[0]) for row in con.execute("SELECT payload FROM function_nodes")]
        current_stages = {node.id for node in nodes if node.parent_id == procedure_id and node.status != "rejected"}
        current = [node for node in nodes if node.id in {chain[0].id, procedure_id}
                   or node.id in current_stages or (node.parent_id in current_stages and node.status != "rejected")]
        if {node.id: node for node in current} != {node.id: node for node in chain}:
            raise ValueError("Процедура изменилась. Повторите проверку формулировок")
        if hashlib.sha256(CONFIG_PATH.read_bytes()).hexdigest() != digest:
            raise ValueError("Правила изменились. Повторите проверку формулировок")
        for record in candidates:
            if con.execute("SELECT 1 FROM function_risks WHERE id=?", (record.id,)).fetchone():
                continue  # Never overwrite a previous human decision, including rejection.
            con.execute("INSERT INTO function_risks VALUES (?,?,?,?,?)",
                        (record.id, record.stage_id, None, record.source_ref, record.model_dump_json()))
            _risk_audit(con, record, "Найден кандидат по формулировке", actor, record.model_dump())
            created += 1
        _audit(con, chain[1], "Проверены формулировки процедуры", actor,
               {"config_sha256": digest, "version": config.version, "stages": len(stages),
                "matched": len(candidates), "created": created,
                "scope": "Только подтверждённые цитаты этапов", "disclaimer": config.disclaimer})
    return {"matched": len(candidates), "created": created, "stages": len(stages)}
