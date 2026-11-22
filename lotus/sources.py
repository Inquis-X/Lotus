import hashlib
import json
import mimetypes
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from lotus.db import connection, init_db
from lotus.settings import ROOT


class SourceDocument(BaseModel):
    id: str
    title: str
    source_kind: str
    origin: str
    uri: str | None = None
    media_type: str | None = None
    sha256: str | None = None
    registered_at: datetime
    synthetic: bool = True
    details: dict[str, str | int | float | bool] = Field(default_factory=dict)


def _row_to_source(row):
    return SourceDocument(
        id=row["id"],
        title=row["title"],
        source_kind=row["source_kind"],
        origin=row["origin"],
        uri=row["uri"],
        media_type=row["media_type"],
        sha256=row["sha256"],
        registered_at=row["registered_at"],
        synthetic=bool(row["synthetic"]),
        details=json.loads(row["details"]),
    )


def _store(source: SourceDocument, db_path=None):
    init_db(db_path)
    with connection(db_path) as con:
        con.execute(
            '''INSERT INTO source_documents(
                id, title, source_kind, origin, uri, media_type, sha256,
                registered_at, synthetic, details
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title=excluded.title,
                source_kind=excluded.source_kind,
                origin=excluded.origin,
                uri=excluded.uri,
                media_type=excluded.media_type,
                sha256=excluded.sha256,
                synthetic=excluded.synthetic,
                details=excluded.details''',
            (
                source.id,
                source.title,
                source.source_kind,
                source.origin,
                source.uri,
                source.media_type,
                source.sha256,
                source.registered_at.isoformat(),
                int(source.synthetic),
                json.dumps(source.details, ensure_ascii=False),
            ),
        )
    return source


def _display_path(file_path: Path):
    resolved = file_path.resolve()
    try:
        return resolved.relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def register_file(
    file_path,
    *,
    title,
    source_kind,
    origin="local",
    synthetic=True,
    details=None,
    db_path=None,
):
    if not synthetic:
        raise ValueError("В реестре допускаются только синтетические материалы")
    file_path = Path(file_path)
    content = file_path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    media_type = mimetypes.guess_type(file_path.name)[0]
    if file_path.suffix.lower() in {".yaml", ".yml"}:
        media_type = "application/yaml"
    source = SourceDocument(
        id=f"SRC-{digest[:20].upper()}",
        title=title,
        source_kind=source_kind,
        origin=origin,
        uri=_display_path(file_path),
        media_type=media_type,
        sha256=digest,
        registered_at=datetime.now(timezone.utc),
        synthetic=True,
        details={"size_bytes": len(content), **(details or {})},
    )
    return _store(source, db_path)


def read_source(document_id, db_path=None):
    init_db(db_path)
    with connection(db_path) as con:
        row = con.execute("SELECT * FROM source_documents WHERE id=?", (document_id,)).fetchone()
    return _row_to_source(row) if row else None


def source_local_path(source: SourceDocument):
    if not source.uri or source.uri.startswith(("http://", "https://")) or source.origin == "derived":
        return None
    path = Path(source.uri)
    if not path.is_absolute():
        path = ROOT / path
    if path.suffix.lower() not in {".json", ".csv", ".xml", ".yaml", ".yml", ".md", ".docx", ".xlsx", ".pdf"}:
        return None
    # Earlier releases registered the bundled samples at these same paths.
    if path.parent == ROOT / "data/gold/functions" and path.name in {"land_v1.docx", "land_v2.docx"}:
        previous = path.parent / "previous" / path.name
        if previous.is_file() and hashlib.sha256(previous.read_bytes()).hexdigest() == source.sha256:
            return previous
    return path if path.is_file() else None
