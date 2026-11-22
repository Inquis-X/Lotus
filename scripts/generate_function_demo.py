"""Generate reproducible input fixtures without touching the application database."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Pt

from lotus.settings import ROOT, read_yaml


def normalize_office_archive(path):
    temporary = path.with_suffix(path.suffix + ".tmp")
    with zipfile.ZipFile(path) as source:
        members = [(member, source.read(member.filename)) for member in source.infolist()]
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED) as target:
        for original, content in sorted(members, key=lambda item: item[0].filename):
            if original.filename == "docProps/core.xml":
                content = re.sub(
                    rb"(<dcterms:modified\b[^>]*>)[^<]*(</dcterms:modified>)",
                    rb"\g<1>2025-01-01T00:00:00Z\g<2>",
                    content,
                )
            member = zipfile.ZipInfo(original.filename, date_time=(1980, 1, 1, 0, 0, 0))
            member.compress_type = zipfile.ZIP_STORED
            member.external_attr = original.external_attr
            member.internal_attr = original.internal_attr
            member.create_system = original.create_system
            target.writestr(member, content)
    temporary.replace(path)


def format_order(doc, spec, config):
    section = doc.sections[0]
    section.left_margin, section.right_margin = Cm(3), Cm(1.5)
    section.top_margin = section.bottom_margin = Cm(2)
    normal = doc.styles["Normal"]
    normal.font.name, normal.font.size = "Times New Roman", Pt(12)
    normal.paragraph_format.line_spacing = 1.15
    normal.paragraph_format.space_after = Pt(4)
    styles = read_yaml(ROOT / "config/function_extraction.yaml")["clause_styles"]
    names = {kind: name for name, kind in styles.items()}
    for name in styles:
        style = doc.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        style.base_style = normal
        style.paragraph_format.first_line_indent = Cm(1.25)
        style.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    label = doc.add_paragraph("Проект  ·  " + spec["edition"] + " от " + spec["date"])
    label.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    approval = doc.add_paragraph(
        "Приложение к проекту постановления\nадминистрации муниципального образования\nот ____________ № ______")
    approval.paragraph_format.left_indent = Cm(8.5)
    approval.paragraph_format.space_before = Pt(8)
    approval.paragraph_format.space_after = Pt(10)
    approval.paragraph_format.line_spacing = 1.0
    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.paragraph_format.space_before = Pt(8)
    title.paragraph_format.space_after = Pt(10)
    title.add_run("ПОРЯДОК\n" + config["order_title"].removeprefix("Порядок ")).bold = True
    scope = doc.add_paragraph(
        "Порядок описывает работу подразделения по земельным отношениям с заявлениями в отношении муниципальной земли. "
        "Основания для отказа проверяются по статье 39.16 Земельного кодекса Российской Федерации. "
        "Внутренние сроки обработки входят в срок рассмотрения заявления по статье 39.17 Кодекса.")
    scope.paragraph_format.first_line_indent = Cm(1.25)
    scope.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    for kind, clause in config["clauses"]:
        doc.add_paragraph(clause.format(decision=spec["decision"]), style=names[kind])


def generate(output=None):
    output = Path(output) if output is not None else ROOT / "data/gold/functions"
    config = read_yaml(ROOT / "data/seed/function_demo.yaml")
    payloads, entries = {}, []
    with TemporaryDirectory(prefix="lotus-function-demo-") as scratch:
        for spec in config["documents"]:
            filename = spec["filename"]
            if Path(filename).name != filename or not filename.endswith(".docx"):
                raise ValueError("Некорректное имя демонстрационного файла")
            doc = Document()
            doc.core_properties.author = "ЛОТОС"
            doc.core_properties.created = datetime(2026, 11, 17)
            doc.core_properties.modified = datetime(2026, 11, 17)
            doc.styles["Normal"].font.name = "Arial"
            doc.styles["Normal"].font.size = Pt(11)
            section = doc.sections[0]
            section.page_width, section.page_height = Cm(21), Cm(29.7)
            is_order = spec.get("format") == "order"
            if is_order:
                format_order(doc, spec, config)
            else:
                doc.add_heading(spec["title"], 0)
                doc.add_paragraph(spec["edition"])
                doc.add_paragraph(config["disclaimer"])
                for line in config["common"]:
                    doc.add_paragraph(line.format(decision=spec["decision"]))
            file = Path(scratch) / filename
            doc.save(file)
            normalize_office_archive(file)
            content = file.read_bytes()
            payloads[filename] = content
            entries.append({"filename": filename, "edition": spec["edition"],
                            "sha256": hashlib.sha256(content).hexdigest(),
                            "expected_candidates": len(config["clauses"] if is_order else config["common"]),
                            "expected_rules": spec["expected_rules"]})
    manifest = {"version": config["version"], "synthetic": True, "disclaimer": config["disclaimer"],
                "documents": entries}
    payloads["manifest.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    # Check the entire batch first; never overwrite user-edited source documents.
    for filename, content in payloads.items():
        target = output / filename
        if target.exists() and target.read_bytes() != content:
            raise ValueError(f"Файл уже существует и отличается: {target}. Выберите другую папку через --output")
    output.mkdir(parents=True, exist_ok=True)
    for filename, content in payloads.items():
        target = output / filename
        if not target.exists():
            with target.open("xb") as stream:
                stream.write(content)
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Подготовить учебные документы земельной функции без изменения базы")
    parser.add_argument("--output", type=Path, default=ROOT / "data/gold/functions")
    args = parser.parse_args()
    manifest = generate(args.output)
    print(f"Подготовлено учебных документов: {len(manifest['documents'])}, и manifest.json: {args.output}")
