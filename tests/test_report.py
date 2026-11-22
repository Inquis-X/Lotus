from io import BytesIO

from docx import Document

from lotus.report import as_bytes


def test_docx_serializes_to_readable_bytes():
    source = Document()
    source.add_paragraph("Синтетический проект")
    content = as_bytes(source)
    assert content.startswith(b"PK")
    assert Document(BytesIO(content)).paragraphs[0].text == "Синтетический проект"
