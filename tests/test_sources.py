import json
import sqlite3

from lotus.sources import read_source, register_file, source_local_path


def test_file_registration_is_idempotent_and_versioned(tmp_path):
    database = tmp_path / "sources.sqlite"
    material = tmp_path / "bundle.json"
    material.write_text(json.dumps({"synthetic": True, "value": 1}), encoding="utf-8")

    first = register_file(material, title="Учебный пакет", source_kind="document", db_path=database)
    second = register_file(material, title="Учебный пакет", source_kind="document", db_path=database)
    assert first.id == second.id
    assert first.sha256 == second.sha256
    assert read_source(first.id, db_path=database).details["size_bytes"] == material.stat().st_size
    assert source_local_path(first) == material.resolve()

    material.write_text(json.dumps({"synthetic": True, "value": 2}), encoding="utf-8")
    changed = register_file(material, title="Учебный пакет", source_kind="document", db_path=database)
    assert changed.id != first.id
    assert read_source(first.id, db_path=database).sha256 == first.sha256


def test_old_database_migration(tmp_path):
    database = tmp_path / "old.sqlite"
    with sqlite3.connect(database) as con:
        con.execute("CREATE TABLE records (model TEXT, id TEXT, payload TEXT)")
    material = tmp_path / "document.yaml"
    material.write_text("synthetic: true\n", encoding="utf-8")
    source = register_file(material, title="Документ", source_kind="document", db_path=database)
    assert read_source(source.id, db_path=database).sha256 == source.sha256


def test_registry_does_not_store_source_content(tmp_path):
    database = tmp_path / "sources.sqlite"
    material = tmp_path / "bundle.json"
    sentinel = "SENTINEL_SOURCE_CONTENT_17485"
    material.write_text(json.dumps({"synthetic": True, "text": sentinel}, ensure_ascii=False), encoding="utf-8")
    register_file(material, title="Учебный пакет", source_kind="document", db_path=database)
    with sqlite3.connect(database) as con:
        dump = "\n".join(con.iterdump())
    assert sentinel not in dump
    assert '"text"' not in dump
