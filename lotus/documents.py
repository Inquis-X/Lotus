import csv
import io
import zipfile
from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from lotus.sources import SourceDocument, register_file

MAX_DOCUMENT_BYTES = 2 * 1024 * 1024
MAX_ARCHIVE_BYTES = 20 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 512
MAX_TABLE_ROWS = 5000
MAX_TABLE_COLUMNS = 200
SUPPORTED_EXTENSIONS = {".docx", ".xlsx", ".csv", ".pdf"}


class DocumentFragment(BaseModel):
    locator: str
    text: str
    page: int | None = None
    paragraph_style: str = ""


class DocumentRow(BaseModel):
    locator: str
    values: list[str]


class DocumentTable(BaseModel):
    name: str
    locator: str
    rows: list[DocumentRow] = Field(default_factory=list)


class ParsedDocument(BaseModel):
    source: SourceDocument
    format: str
    fragments: list[DocumentFragment] = Field(default_factory=list)
    tables: list[DocumentTable] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def _check_archive(content, suffix):
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            members = archive.infolist()
            if len(members) > MAX_ARCHIVE_MEMBERS:
                raise ValueError(f"Документ {suffix} содержит слишком много внутренних файлов")
            total = sum(member.file_size for member in members)
            if total > MAX_ARCHIVE_BYTES:
                raise ValueError(f"Распакованный размер документа {suffix} превышает 20 МБ")
            if any(member.flag_bits & 0x1 for member in members):
                raise ValueError(f"Зашифрованные документы {suffix} не поддерживаются")
    except zipfile.BadZipFile:
        raise ValueError(f"Документ {suffix} повреждён, зашифрован или имеет неверный формат") from None


def _cell_text(value):
    if value is None:
        return ""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def _check_table_size(row_count, column_count):
    if row_count > MAX_TABLE_ROWS:
        raise ValueError("Таблица содержит более 5000 строк")
    if column_count > MAX_TABLE_COLUMNS:
        raise ValueError("Таблица содержит более 200 столбцов")


def _parse_docx(content):
    from docx import Document

    document = Document(io.BytesIO(content))
    fragments = []
    for index, paragraph in enumerate(document.paragraphs, 1):
        text = paragraph.text.strip()
        if text:
            fragments.append(DocumentFragment(locator=f"абзац {index}", text=text,
                                              paragraph_style=paragraph.style.name if paragraph.style else ""))
    tables = []
    for table_index, table in enumerate(document.tables, 1):
        _check_table_size(len(table.rows), len(table.columns))
        rows = []
        for row_index, row in enumerate(table.rows, 1):
            values = [cell.text.strip() for cell in row.cells]
            if any(values):
                rows.append(DocumentRow(locator=f"строка {row_index}", values=values))
        tables.append(DocumentTable(name=f"Таблица {table_index}", locator=f"таблица {table_index}", rows=rows))
    return fragments, tables, ["Номера страниц DOCX не определяются; используются номера абзацев и таблиц"]


def _parse_xlsx(content):
    try:
        from openpyxl import load_workbook
    except ImportError:
        raise ValueError("Для XLSX требуется пакет openpyxl") from None
    workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True, keep_links=False)
    tables = []
    try:
        for sheet in workbook.worksheets:
            _check_table_size(sheet.max_row or 0, sheet.max_column or 0)
            rows = []
            for row_index, row in enumerate(sheet.iter_rows(values_only=True), 1):
                if row_index > MAX_TABLE_ROWS:
                    raise ValueError("Таблица содержит более 5000 строк")
                values = [_cell_text(value) for value in row]
                if any(values):
                    rows.append(DocumentRow(locator=f"строка {row_index}", values=values))
            tables.append(DocumentTable(name=sheet.title, locator=f"лист {sheet.title}", rows=rows))
    finally:
        workbook.close()
    return [], tables, ["Значения формул берутся из сохранённых результатов XLSX; пересчёт не выполняется"]


def _parse_csv(content):
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError("CSV должен быть в кодировке UTF-8 или UTF-8 с BOM") from None
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = []
    reader = csv.reader(io.StringIO(text), dialect)
    for row_index, values in enumerate(reader, 1):
        if row_index > MAX_TABLE_ROWS:
            raise ValueError("Таблица содержит более 5000 строк")
        _check_table_size(row_index, len(values))
        if any(value.strip() for value in values):
            rows.append(DocumentRow(locator=f"строка {row_index}", values=[value.strip() for value in values]))
    return [], [DocumentTable(name="CSV", locator="файл CSV", rows=rows)], []


def _parse_pdf(content):
    try:
        from pypdf import PdfReader
    except ImportError:
        raise ValueError("Для PDF требуется пакет pypdf") from None
    reader = PdfReader(io.BytesIO(content), strict=False)
    if reader.is_encrypted:
        raise ValueError("Зашифрованные PDF не поддерживаются")
    fragments = []
    empty_pages = 0
    for page_number, page in enumerate(reader.pages, 1):
        text = (page.extract_text() or "").strip()
        if text:
            fragments.append(DocumentFragment(locator=f"страница {page_number}", text=text, page=page_number))
        else:
            empty_pages += 1
    warnings = []
    if empty_pages:
        warnings.append(f"Текстовый слой не обнаружен на страницах: {empty_pages}. OCR не выполняется")
    return fragments, [], warnings


def parse_document(file_path, db_path=None):
    file_path = Path(file_path)
    suffix = file_path.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError("Поддерживаются DOCX, XLSX, CSV и PDF с текстовым слоем")
    size = file_path.stat().st_size
    if size == 0:
        raise ValueError(f"{file_path.name}: файл пуст")
    if size > MAX_DOCUMENT_BYTES:
        raise ValueError(f"{file_path.name}: размер превышает 2 МБ")
    content = file_path.read_bytes()
    if suffix in {".docx", ".xlsx"}:
        _check_archive(content, suffix)
    parsers = {".docx": _parse_docx, ".xlsx": _parse_xlsx, ".csv": _parse_csv, ".pdf": _parse_pdf}
    try:
        fragments, tables, warnings = parsers[suffix](content)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"{file_path.name}: не удалось разобрать документ ({type(exc).__name__})") from None
    source = register_file(
        file_path,
        title=file_path.name,
        source_kind="document",
        origin="document_upload",
        details={"format": suffix[1:]},
        db_path=db_path,
    )
    return ParsedDocument(source=source, format=suffix[1:], fragments=fragments, tables=tables, warnings=warnings)
