"""Нативный desktop-запуск «Лотоса» на PySide6."""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

APP_TITLE = "Лотос · Рабочее пространство"
APP_NAME = "Lotus"


def resource_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def default_data_root() -> Path:
    override = os.environ.get("LOTUS_DATA_DIR")
    if override:
        return Path(override)
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "user_data"
    return Path(__file__).resolve().parent / "user_data"


def configure_logging(data_root: Path) -> logging.Logger:
    data_root.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("lotus")
    if not logger.handlers:
        handler = logging.FileHandler(data_root / "lotus-desktop.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    check_only = "--check" in argv
    if check_only and sys.platform != "win32":
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    data_root = default_data_root()
    os.environ["LOTUS_DATA_DIR"] = str(data_root)
    logger = configure_logging(data_root)

    from PySide6.QtWidgets import QApplication, QMessageBox

    from lotus.ui.common import STYLE
    from lotus.ui.main_window import MainWindow

    app = QApplication([sys.argv[0]])
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_TITLE)
    app.setOrganizationName(APP_NAME)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)

    try:
        window = MainWindow()
    except (ValueError, OSError) as exc:
        logger.exception("Application startup failed")
        if not check_only:
            QMessageBox.critical(None, APP_TITLE, f"Не удалось запустить приложение.\n{exc}")
        return 1

    def handle_exception(exc_type, exc_value, exc_traceback):
        logger.error("Unhandled UI exception", exc_info=(exc_type, exc_value, exc_traceback))
        QMessageBox.critical(window, APP_TITLE, "Произошла ошибка. Подробности записаны в lotus-desktop.log.")

    sys.excepthook = handle_exception
    window.show()
    app.processEvents()
    logger.info("Application started; data directory: %s", data_root)
    if check_only:
        if sys.stdout is not None:
            print(f"Лотос готов. Данные: {data_root}")
        window.close()
        return 0
    return app.exec()


if __name__ == "__main__":
    try:
        exit_code = main()
    except Exception:
        configure_logging(default_data_root()).exception("Unhandled startup error")
        if "--check" not in sys.argv:
            raise
        exit_code = 1
    raise SystemExit(exit_code)
