import sqlite3
import zipfile

import pytest
from docx import Document
from openpyxl import Workbook
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from lotus.documents import parse_document


def make_pdf(path, encrypted=False):
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject()
    font.update({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    font_ref = writer._add_object(font)
    fonts = DictionaryObject()
    fonts[NameObject("/F1")] = font_ref
    resources = DictionaryObject()
    resources[NameObject("/Font")] = fonts
    page[NameObject("/Resources")] = resources
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 72 720 Td (Synthetic PDF event) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    writer.add_blank_page(width=612, height=792)
    if encrypted:
        writer.encrypt("secret")
    with path.open("wb") as file:
        writer.write(file)


def test_docx_paragraphs_tables_and_no_content_in_registry(tmp_path):
    path = tmp_path / "material.docx"
    document = Document()
    document.add_paragraph("SENTINEL_DOCX_PARAGRAPH_91245")
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Поле"
    table.cell(0, 1).text = "Значение"
    document.save(path)
    database = tmp_path / "documents.sqlite"

    parsed = parse_document(path, db_path=database)
    assert parsed.fragments[0].locator == "абзац 1"
    assert parsed.fragments[0].text == "SENTINEL_DOCX_PARAGRAPH_91245"
    assert parsed.tables[0].rows[0].values == ["Поле", "Значение"]
    assert parsed.tables[0].rows[0].locator == "строка 1"
    assert parsed.source.sha256
    with sqlite3.connect(database) as con:
        dump = "\n".join(con.iterdump())
    assert "SENTINEL_DOCX_PARAGRAPH_91245" not in dump


def test_xlsx_sheets_rows_and_cached_values(tmp_path):
    path = tmp_path / "material.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Закупки"
    sheet.append(["Номер", "Сумма"])
    sheet.append(["З-001", 125000])
    sheet.append(["Формула", "=1+1"])
    workbook.save(path)

    parsed = parse_document(path, db_path=tmp_path / "xlsx.sqlite")
    assert parsed.tables[0].name == "Закупки"
    assert parsed.tables[0].rows[1].locator == "строка 2"
    assert parsed.tables[0].rows[1].values == ["З-001", "125000"]
    assert parsed.tables[0].rows[2].values == ["Формула", ""]
    assert "пересчёт" in parsed.warnings[0]


def test_csv_utf8_bom_and_semicolon(tmp_path):
    path = tmp_path / "material.csv"
    path.write_bytes("Поле;Значение\nДата;2025-01-01\n".encode("utf-8-sig"))
    parsed = parse_document(path, db_path=tmp_path / "csv.sqlite")
    assert parsed.tables[0].rows[0].values == ["Поле", "Значение"]
    assert parsed.tables[0].rows[1].values == ["Дата", "2025-01-01"]


def test_pdf_text_pages_and_empty_page_warning(tmp_path):
    path = tmp_path / "material.pdf"
    make_pdf(path)
    parsed = parse_document(path, db_path=tmp_path / "pdf.sqlite")
    assert len(parsed.fragments) == 1
    assert parsed.fragments[0].page == 1
    assert parsed.fragments[0].locator == "страница 1"
    assert "Synthetic PDF event" in parsed.fragments[0].text
    assert "OCR не выполняется" in parsed.warnings[0]


def test_encrypted_pdf_is_rejected(tmp_path):
    path = tmp_path / "encrypted.pdf"
    make_pdf(path, encrypted=True)
    with pytest.raises(ValueError, match="Зашифрованные PDF"):
        parse_document(path, db_path=tmp_path / "encrypted.sqlite")


def test_invalid_and_oversized_documents_are_rejected(tmp_path):
    invalid = tmp_path / "invalid.docx"
    invalid.write_bytes(b"not a docx")
    with pytest.raises(ValueError, match="повреждён"):
        parse_document(invalid, db_path=tmp_path / "invalid.sqlite")

    oversized = tmp_path / "oversized.csv"
    oversized.write_bytes(b"0" * (2 * 1024 * 1024 + 1))
    with pytest.raises(ValueError, match="превышает 2 МБ"):
        parse_document(oversized, db_path=tmp_path / "oversized.sqlite")


def test_archive_uncompressed_size_is_checked(tmp_path):
    path = tmp_path / "archive.docx"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", b" " * (20 * 1024 * 1024 + 1))
    with pytest.raises(ValueError, match="Распакованный размер"):
        parse_document(path, db_path=tmp_path / "archive.sqlite")
