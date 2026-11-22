"""Launch a packaged Windows release with fresh user data."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import zipfile


def check(archive):
    with tempfile.TemporaryDirectory(prefix="lotus-release-") as folder:
        root = Path(folder)
        with zipfile.ZipFile(archive) as package:
            package.extractall(root)
        (exe,) = root.glob("*/Lotus.exe")
        examples = exe.parent / "data/gold/functions"
        manifest = json.loads((examples / "manifest.json").read_text(encoding="utf-8"))
        files = {item["filename"]: item["sha256"] for item in manifest["documents"]}
        expected = {"land_v1.docx", "land_v2.docx", "land_v3.docx", "land_v4.docx", "land_control.docx"}
        if set(files) != expected:
            raise ValueError("Incomplete set of demonstration documents")
        for filename, digest in files.items():
            if hashlib.sha256((examples / filename).read_bytes()).hexdigest() != digest:
                raise ValueError(f"Demo checksum mismatch: {filename}")
        if not (exe.parent / "START_WINDOWS.txt").is_file():
            raise ValueError("Missing start guide")
        data = root / "user-data"
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen", LOTUS_DATA_DIR=str(data))
        env.pop("LOTUS_DB_PATH", None)
        # Reproduce the PATH available on an ordinary Windows machine.
        windows = Path(os.environ["SystemRoot"])
        env["PATH"] = os.pathsep.join((str(windows / "System32"), str(windows)))
        result = subprocess.run([str(exe), "--check"], cwd=root, env=env, timeout=60)
        if result.returncode or not (data / "data/lotus.sqlite").is_file():
            log = data / "lotus-desktop.log"
            detail = log.read_text(encoding="utf-8") if log.is_file() else "No application log"
            raise RuntimeError(f"Packaged startup failed ({result.returncode}): {detail}")
    print("Windows release passed: EXE startup, fresh database, guide and five DOCX checksums.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    check(parser.parse_args().archive)
