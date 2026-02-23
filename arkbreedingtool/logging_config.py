from __future__ import annotations

import logging
import os
import sys


DEFAULT_LEVEL = "INFO"


def setup_logging() -> None:
    level_name = os.getenv("ARKBREEDINGTOOL_LOG_LEVEL", DEFAULT_LEVEL).upper()
    level = getattr(logging, level_name, logging.INFO)

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )

    logging.getLogger("PySide6").setLevel(logging.WARNING)
