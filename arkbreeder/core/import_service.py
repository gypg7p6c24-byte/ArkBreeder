from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path

from arkbreeder.core.parser import ParsedCreature, parse_creature_file
from arkbreeder.storage.models import Creature
from arkbreeder.storage.repository import upsert_creature

logger = logging.getLogger(__name__)


@dataclass
class ImportResult:
    imported: int = 0
    skipped: int = 0
    failed: int = 0


class ExportImportService:
    def __init__(self, conn, export_dir: Path, delete_after_import: bool = True) -> None:
        self._conn = conn
        self._export_dir = export_dir
        self._delete_after_import = delete_after_import

    def poll_once(self) -> ImportResult:
        result = ImportResult()
        if not self._export_dir.exists():
            logger.debug("Export directory does not exist: %s", self._export_dir)
            return result

        for path in sorted(self._export_dir.iterdir()):
            if not path.is_file():
                continue
            try:
                parsed = parse_creature_file(path)
                creature = self._to_creature(parsed)
                saved = upsert_creature(self._conn, creature)
                result.imported += 1
                logger.info(
                    "Imported %s (%s) from %s",
                    saved.name,
                    saved.external_id or "no-id",
                    path.name,
                )
                if self._delete_after_import:
                    path.unlink()
            except Exception:
                result.failed += 1
                logger.exception("Failed to import %s", path)
        return result

    def _to_creature(self, parsed: ParsedCreature) -> Creature:
        return Creature(
            id=None,
            external_id=parsed.external_id,
            name=parsed.name,
            species=parsed.species,
            sex=parsed.sex,
            level=parsed.level,
            stats=parsed.stats,
            mutations_maternal=parsed.mutations_maternal or 0,
            mutations_paternal=parsed.mutations_paternal or 0,
        )
