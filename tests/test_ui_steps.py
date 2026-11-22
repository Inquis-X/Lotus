from types import SimpleNamespace

from lotus.ui.steps import build_analysis_steps, confirmed_procedures, next_candidate


def node(node_id, kind, status="confirmed", parent_id=None, title=None):
    return SimpleNamespace(id=node_id, kind=kind, status=status, parent_id=parent_id,
                           title=title or node_id)


def risk(risk_id, status="candidate", needs_review=False):
    return SimpleNamespace(id=risk_id, stage_id="s", status=status, needs_review=needs_review,
                           rule_evidence=SimpleNamespace(rule_id="F02"))


def complete_nodes():
    return [
        node("f", "function"),
        node("p", "procedure", parent_id="f"),
        node("s", "stage", parent_id="p"),
        node("r", "role", parent_id="s"),
        node("c", "control", parent_id="s"),
    ]


def test_steps_explain_document_and_candidate_blocks():
    steps = build_analysis_steps([], [])
    assert steps[0]["state"] == "текущий"
    assert all(step["state"] == "заблокирован" for step in steps[1:])
    assert "выберите документ" in steps[1]["reason"]

    steps = build_analysis_steps([], [], document_selected=True)
    assert steps[0]["state"] == "готов"
    assert steps[1]["state"] == "текущий"
    assert "Сначала сохраните кандидатов" in steps[2]["reason"]


def test_steps_count_decisions_and_find_next_candidate():
    nodes = complete_nodes()
    nodes[2].status = "candidate"
    nodes[3].status = "candidate"
    nodes[4].status = "rejected"
    steps = build_analysis_steps(nodes, [], document_selected=True)
    assert steps[2]["state"] == "текущий"
    assert "Подтверждено 2 из 5 записей" in steps[2]["detail"]
    assert steps[3]["state"] == "заблокирован"
    assert next_candidate(nodes).id == "s"
    assert confirmed_procedures(nodes) == []


def test_steps_support_completed_check_without_findings():
    nodes = complete_nodes()
    steps = build_analysis_steps(nodes, [], document_selected=True)
    assert steps[3]["state"] == "текущий"
    assert steps[4]["state"] == "заблокирован"

    steps = build_analysis_steps(nodes, [], document_selected=True,
                                 checked_procedures={"p"})
    assert steps[3]["state"] == "готов"
    assert steps[4]["state"] == "готов"
    assert "Находок нет" in steps[4]["detail"]
    assert steps[5]["state"] == "заблокирован"


def test_steps_track_risk_assessment_and_report_availability():
    nodes = complete_nodes()
    steps = build_analysis_steps(nodes, [risk("old", needs_review=True)], document_selected=True)
    assert steps[3]["state"] == "текущий"

    steps = build_analysis_steps(nodes, [risk("r1")], document_selected=True)
    assert steps[3]["state"] == "готов"
    assert steps[4]["state"] == "текущий"
    assert "Оценено 0 из 1 находок" in steps[4]["detail"]
    assert steps[5]["state"] == "заблокирован"

    steps = build_analysis_steps(nodes, [risk("r1", "confirmed")], document_selected=True)
    assert steps[4]["state"] == "готов"
    assert steps[5]["state"] == "текущий"
    assert "доступно: 1" in steps[5]["detail"]
