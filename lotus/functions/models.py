from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class FunctionNode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Text
    kind: Literal["function", "procedure", "stage", "role", "control"]
    parent_id: str | None = None
    title: Text
    department: str = ""
    source_ref: Text
    coordinate: Text
    edition: Text
    quote: Text
    origin: Literal["manual", "auto"] = "manual"
    status: Literal["candidate", "confirmed", "rejected"] = "candidate"
    rationale: str = ""
    actor: str = ""
    reviewed_at: str | None = None


class Function(FunctionNode):
    kind: Literal["function"] = "function"


class Procedure(FunctionNode):
    kind: Literal["procedure"] = "procedure"


class Stage(FunctionNode):
    kind: Literal["stage"] = "stage"


class Role(FunctionNode):
    kind: Literal["role"] = "role"


class Control(FunctionNode):
    kind: Literal["control"] = "control"


class PhraseMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: int
    end: int
    text: Text


class RuleEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rule_id: Text
    version: Text
    config_sha256: Text
    phrase: Text
    min_occurrences: int
    exclude_patterns: list[str]
    matches: list[PhraseMatch]


class RiskRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Text
    stage_id: Text
    control_id: str | None = None
    vulnerability: Text
    control_limitation: Text
    proposed_measure: Text
    source_ref: Text
    coordinate: Text
    edition: Text
    quote: Text
    origin: Literal["manual", "auto"] = "manual"
    rule_evidence: RuleEvidence | None = None
    status: Literal["candidate", "confirmed", "rejected"] = "candidate"
    rationale: str = ""
    actor: str = ""
    reviewed_at: str | None = None
    needs_review: bool = False
