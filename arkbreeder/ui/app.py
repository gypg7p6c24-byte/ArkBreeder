from __future__ import annotations

import logging

from PySide6 import QtCore, QtWidgets

from arkbreeder.config import export_dir
from arkbreeder.core.import_service import ExportImportService
from arkbreeder.logging_config import setup_logging
from arkbreeder.storage.database import get_connection, init_db
from arkbreeder.ui.main_window import MainWindow

logger = logging.getLogger(__name__)

def main() -> int:
    setup_logging()
    logger.info("Starting ARK Breeder")
    conn = get_connection()
    init_db(conn)

    app = QtWidgets.QApplication([])
    export_path = export_dir()
    window = MainWindow(conn, export_path)
    window.resize(1360, 860)
    window.show()
    app.aboutToQuit.connect(conn.close)

    service = ExportImportService(conn, export_path, on_notify=window.show_toast)
    timer = QtCore.QTimer()
    timer.setInterval(500)
    window._import_service = service
    timer.timeout.connect(window.handle_import_tick)
    timer.start()
    logger.info("Watching export directory: %s", export_path)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
