from __future__ import annotations

import logging
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from arkbreeder.config import APP_NAME, export_dir
from arkbreeder.core.import_service import ExportImportService
from arkbreeder.logging_config import setup_logging
from arkbreeder.storage.database import get_connection, init_db
from arkbreeder.ui.main_window import MainWindow

logger = logging.getLogger(__name__)


def _load_app_icon() -> QtGui.QIcon:
    resources_icon = Path(__file__).resolve().parents[1] / "resources" / "arkbreeder.svg"
    fallback_icon = Path(__file__).resolve().parents[2] / "packaging" / "arkbreeder.svg"
    for candidate in (resources_icon, fallback_icon):
        if candidate.exists():
            icon = QtGui.QIcon(str(candidate))
            if not icon.isNull():
                return icon
    return QtGui.QIcon()


def main() -> int:
    setup_logging()
    logger.info("Starting ARK Breeder")
    conn = get_connection()
    init_db(conn)

    app = QtWidgets.QApplication([])
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setDesktopFileName("arkbreeder")
    icon = _load_app_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)
    export_path = export_dir()
    window = MainWindow(conn, export_path)
    if not icon.isNull():
        window.setWindowIcon(icon)
    window.resize(1360, 860)
    window.show()
    app.aboutToQuit.connect(conn.close)

    service = ExportImportService(
        conn,
        export_path,
        delete_after_import=False,
        on_notify=window.show_toast,
    )
    timer = QtCore.QTimer()
    timer.setInterval(500)
    window._import_service = service
    timer.timeout.connect(window.handle_import_tick)
    timer.start()
    logger.info("Watching export directory (keep files): %s", export_path)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
