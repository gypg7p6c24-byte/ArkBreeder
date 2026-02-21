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
    window = MainWindow()
    window.resize(960, 600)
    window.show()
    app.aboutToQuit.connect(conn.close)

    service = ExportImportService(conn, export_dir(), on_notify=window.show_toast)
    timer = QtCore.QTimer()
    timer.setInterval(500)
    timer.timeout.connect(service.poll_once)
    timer.start()
    logger.info("Watching export directory: %s", export_dir())

    window._import_service = service
    window._import_timer = timer
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
