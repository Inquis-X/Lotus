import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from desktop import default_data_root

os.environ.setdefault("LOTUS_DATA_DIR", str(default_data_root()))

from lotus.audit import log
from lotus.db import init_db
from lotus.settings import DATA_ROOT, DB_PATH
from scripts.generate_function_demo import generate


def reset():
    for suffix in ("", "-wal", "-shm"):
        Path(str(DB_PATH) + suffix).unlink(missing_ok=True)
    init_db()
    output = DATA_ROOT / "data/gold/functions"
    for filename in ("land_v1.docx", "land_v2.docx", "land_v3.docx", "land_v4.docx",
                     "land_control.docx", "manifest.json"):
        (output / filename).unlink(missing_ok=True)
    manifest = generate(output)
    log(
        "Демонстрация подготовлена",
        "system",
        "function_demo",
        {"documents": [entry["filename"] for entry in manifest["documents"]]},
    )
    print(f"Демонстрация готова: {output}")
    print("База анализа функций очищена; восстановлены учебные документы land_v1–v4 и land_control")


if __name__ == "__main__":
    reset()
