STEP_DESCRIPTIONS = [
    "Подтвердите отсутствие персональных данных и выберите документ с описанием функций.",
    "Найдите кандидатов в DOCX или создайте записи вручную.",
    "Проверьте записи в иерархическом порядке: функция → процедура → этапы → роли и контроли. "
    "Для каждой подтвердите или отклоните с обоснованием.",
    "Проверьте формулировки подтверждённой процедуры по правилам F02/F04.",
    "Оцените находки в «Реестре рисков» и сохраните решение с обоснованием.",
    "Сформируйте проект карты рисков в «Отчётах».",
]

STEP_TITLES = ["Документ", "Кандидаты", "Проверка записей", "Формулировки", "Находки", "Отчёт"]


def next_candidate(nodes):
    return next((node for node in nodes if node.status == "candidate"), None)


def confirmed_procedures(nodes):
    by_id = {node.id: node for node in nodes}
    children = {}
    for node in nodes:
        children.setdefault(node.parent_id, []).append(node)
    result = []
    for procedure in nodes:
        if procedure.kind != "procedure" or procedure.status != "confirmed":
            continue
        function = by_id.get(procedure.parent_id)
        stages = [node for node in children.get(procedure.id, []) if node.status != "rejected"]
        stage_ids = {node.id for node in stages}
        related = [node for node in nodes if node.parent_id in stage_ids and node.status != "rejected"]
        chain = [function, procedure, *stages, *related]
        if function is not None and stages and all(node.status == "confirmed" for node in chain):
            result.append(procedure)
    return result


def build_analysis_steps(nodes, risks, *, document_selected=False,
                         checked_procedures=()):
    steps = [{"title": title, "description": description, "state": "заблокирован", "detail": "", "reason": ""}
             for title, description in zip(STEP_TITLES, STEP_DESCRIPTIONS)]

    def set_step(index, state, detail, reason=""):
        steps[index].update(state=state, detail=detail, reason=reason)

    if document_selected:
        set_step(0, "готов", "Документ выбран")
    else:
        set_step(0, "текущий", "Выберите документ")
        reasons = [
            "",
            "Сначала выберите документ",
            "Сначала сохраните кандидатов из документа",
            "Нет подтверждённых процедур",
            "Сначала проверьте формулировки подтверждённой процедуры",
            "Нет подтверждённых находок в реестре",
        ]
        for index in range(1, 6):
            set_step(index, "заблокирован", "", reasons[index])
        return steps

    if nodes:
        candidates = sum(node.status == "candidate" for node in nodes)
        set_step(1, "готов", f"Сохранено записей: {len(nodes)} · требуют решения: {candidates}")
    else:
        set_step(1, "текущий", "Найдите кандидатов в DOCX или создайте записи вручную")
        set_step(2, "заблокирован", "", "Сначала сохраните кандидатов из документа")
        set_step(3, "заблокирован", "", "Нет подтверждённых процедур")
        set_step(4, "заблокирован", "", "Сначала проверьте формулировки подтверждённой процедуры")
        set_step(5, "заблокирован", "", "Нет подтверждённых находок в реестре")
        return steps

    confirmed = sum(node.status == "confirmed" for node in nodes)
    candidates = sum(node.status == "candidate" for node in nodes)
    rejected = len(nodes) - confirmed - candidates
    counter = f"Подтверждено {confirmed} из {len(nodes)} записей · отклонено {rejected}"
    if candidates:
        set_step(2, "текущий", counter)
    else:
        set_step(2, "готов", counter)

    procedures = confirmed_procedures(nodes)
    checked = set(checked_procedures)
    by_id = {node.id: node for node in nodes}
    checked_by_findings = set()
    for risk in risks:
        stage = by_id.get(risk.stage_id)
        procedure = by_id.get(stage.parent_id) if stage else None
        if not risk.needs_review and getattr(risk, "rule_evidence", None) is not None and procedure:
            checked_by_findings.add(procedure.id)
    phrases_checked = bool(procedures) and all(
        procedure.id in checked or procedure.id in checked_by_findings for procedure in procedures)
    if candidates:
        set_step(3, "заблокирован", "", "Сначала проверьте все записи и заполните обоснование каждого решения")
    elif not procedures:
        set_step(3, "заблокирован", "", "Нет подтверждённых процедур со всеми этапами, ролями и контролями")
    elif phrases_checked:
        set_step(3, "готов", f"Проверка выполнена · подтверждённых процедур: {len(procedures)}")
    else:
        set_step(3, "текущий", f"Выберите подтверждённую процедуру · доступно: {len(procedures)}")

    pending_risks = sum(risk.status == "candidate" or risk.needs_review for risk in risks)
    assessed_risks = len(risks) - pending_risks
    if steps[3]["state"] != "готов":
        set_step(4, "заблокирован", "", "Сначала проверьте формулировки подтверждённой процедуры")
    elif not risks:
        set_step(4, "готов", "Находок нет; при необходимости создайте запись вручную в реестре")
    elif pending_risks:
        set_step(4, "текущий", f"Оценено {assessed_risks} из {len(risks)} находок · осталось {pending_risks}")
    else:
        confirmed_risks = sum(risk.status == "confirmed" for risk in risks)
        set_step(4, "готов", f"Оценено {len(risks)} из {len(risks)} находок · подтверждено {confirmed_risks}")

    confirmed_risks = sum(risk.status == "confirmed" and not risk.needs_review for risk in risks)
    if steps[4]["state"] != "готов":
        set_step(5, "заблокирован", "", "Сначала оцените все находки в реестре")
    elif not confirmed_risks:
        set_step(5, "заблокирован", "", "Нет подтверждённых актуальных находок для отчёта")
    else:
        set_step(5, "текущий", f"Выберите подтверждённые записи для проекта · доступно: {confirmed_risks}")
    return steps
