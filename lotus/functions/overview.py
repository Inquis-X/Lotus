"""Read-only projection shared by the municipality map and overview."""
from lotus.functions.service import list_nodes, list_risks

LABELS = {"unreviewed": "Не исследовано", "reviewing": "Проверяется",
          "reviewed": "Сведения проверены", "attention": "Есть основания для внимания",
          "rejected": "Отклонено"}


def project_functions(nodes, risks):
    children = {}
    for node in nodes:
        children.setdefault(node.parent_id, []).append(node)

    def descendants(node):
        result = [node]
        for child in children.get(node.id, []):
            result.extend(descendants(child))
        return result

    result = []
    for function in children.get(None, []):
        branch = descendants(function)
        ids = {node.id for node in branch}
        related = [risk for risk in risks if risk.stage_id in ids]
        active_nodes = [node for node in branch if node.status != "rejected"]
        active_risks = [risk for risk in related if risk.status != "rejected"]
        if function.status == "rejected":
            status = "rejected"
        elif active_risks:
            status = "attention"
        elif all(node.status == "candidate" for node in active_nodes):
            status = "unreviewed"
        elif (any(node.status == "candidate" for node in active_nodes)
              or not any(node.kind == "stage" for node in active_nodes)):
            status = "reviewing"
        else:
            status = "reviewed"
        result.append({"function": function, "nodes": branch, "risks": related,
                       "status": status, "active_risks": len(active_risks)})
    return result


def load_overview(path=None):
    return project_functions(list_nodes(path), list_risks(path))
