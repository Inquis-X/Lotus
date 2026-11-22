import os
from pathlib import Path
import subprocess
import sys

import desktop
from lotus.settings import RESOURCE_ROOT


def test_data_root_can_be_overridden(monkeypatch, tmp_path):
    monkeypatch.setenv("LOTUS_DATA_DIR", str(tmp_path / "user-data"))
    assert desktop.default_data_root() == tmp_path / "user-data"


def test_native_check_runs_without_server(tmp_path):
    env = os.environ.copy()
    env["LOTUS_DATA_DIR"] = str(tmp_path / "user-data")
    env["QT_QPA_PLATFORM"] = "offscreen"
    completed = subprocess.run(
        [sys.executable, "desktop.py", "--check"],
        cwd=RESOURCE_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert (tmp_path / "user-data/data/lotus.sqlite").exists()
    assert not (tmp_path / "user-data/lotus-server.log").exists()


def test_native_launcher_has_no_web_server_or_webview():
    source = (RESOURCE_ROOT / "desktop.py").read_text(encoding="utf-8").casefold()
    assert "qapplication" in source
    assert "subprocess" not in source
    assert "webview" not in source
    assert "streamlit" not in source
