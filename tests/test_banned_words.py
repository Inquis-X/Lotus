from io import BytesIO

from docx import Document

from lotus.documents import parse_document
from lotus.functions.detectors import run_rules
from lotus.functions.extraction import extract, save_extraction
from lotus.functions.report import build_report
from lotus.functions.service import review, review_risk
from lotus.settings import ROOT
from scripts.generate_function_demo import generate

BANNED = [
    "коррупционер", "виновен", "виновна", "виноват", "преступник",
    "склонность к коррупции", "коррупционная склонность", "рейтинг коррумпированности",
    "уровень коррумпированности", "оценка личности", "доказано", "доказательство вины",
    "факт нарушения установлен",
]


def test_interface_templates_and_config_language():
    paths = [ROOT / "desktop.py"]
    paths += list((ROOT / "lotus").rglob("*.py"))
    paths += list((ROOT / "config").glob("*.yaml"))
    for path in paths:
        text = path.read_text(encoding="utf-8").casefold()
        for word in BANNED:
            assert word not in text, (str(path), word)


def test_generated_report_language(tmp_path):
    output, database = tmp_path / "documents", tmp_path / "report.sqlite"
    generate(output)
    batch = extract(parse_document(output / "land_v1.docx", database), "Учебная редакция 1")
    save_extraction(batch, path=database)
    for node in batch.candidates:
        review(node.id, "confirmed", "Учебная проверка цитаты и связи", path=database)
    procedure = next(node for node in batch.candidates if node.kind == "procedure")
    run_rules(procedure.id, path=database)
    from lotus.functions.service import list_risks
    risks = list_risks(database)
    for risk in risks:
        review_risk(risk.id, "confirmed", "Проверен полный контекст учебной цитаты", path=database)
    content, _ = build_report([risk.id for risk in risks], path=database)
    text = "\n".join(p.text for p in Document(BytesIO(content)).paragraphs).casefold()
    assert not any(word in text for word in BANNED)
