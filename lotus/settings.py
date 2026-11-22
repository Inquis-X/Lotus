from pathlib import Path
import os
import yaml

# Read-only application resources bundled with source and desktop builds.
RESOURCE_ROOT = Path(__file__).resolve().parents[1]
ROOT = RESOURCE_ROOT

# Writable runtime data: SQLite database, logs and generated demonstration files.
DATA_ROOT = Path(os.environ.get("LOTUS_DATA_DIR", str(RESOURCE_ROOT / "user_data")))
DB_PATH = Path(os.environ.get("LOTUS_DB_PATH", str(DATA_ROOT / "data/lotus.sqlite")))


def read_yaml(path: Path):
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"Не удалось прочитать {path.name}: {exc}") from exc
