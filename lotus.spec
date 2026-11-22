# -*- mode: python ; coding: utf-8 -*-
"""Single-file PyInstaller build for the native PySide6 application."""
from PyInstaller.utils.hooks import collect_all, collect_submodules


datas = [
    ("config", "config"),
    ("docs/analysis_method.md", "docs"),
    ("data/seed", "data/seed"),
    ("data/gold", "data/gold"),
]
binaries = []
hiddenimports = collect_submodules("lotus")

for package in ("docx", "openpyxl", "pypdf"):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden


a = Analysis(
    ["desktop.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "tests", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Lotus",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
