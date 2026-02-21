from __future__ import annotations

import logging

from PySide6 import QtWidgets

from arkbreeder.logging_config import setup_logging
from arkbreeder.storage.database import db_session
from arkbreeder.ui.main_window import MainWindow

logger = logging.getLogger(__name__)

def main() -> int:
    setup_logging()
    logger.info("Starting ARK Breeder")
    with db_session():
        pass

    app = QtWidgets.QApplication([])
    window = MainWindow()
    window.resize(960, 600)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
