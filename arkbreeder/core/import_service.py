from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
import shutil
from typing import Callable, Optional, Tuple, Iterable

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
    def __init__(
        self,
        conn,
        export_dir: Path,
        delete_after_import: bool = True,
        on_notify: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        self._conn = conn
        self._export_dir = export_dir
        self._delete_after_import = delete_after_import
        self._on_notify = on_notify

    def poll_once(self) -> ImportResult:
        result = ImportResult()
        if not self._export_dir.exists():
            logger.debug("Export directory does not exist: %s", self._export_dir)
            return result

        for path, cleanup_target in self._iter_export_targets():
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
                if self._on_notify:
                    self._on_notify(
                        f"Imported {saved.name}",
                        "success",
                    )
                if self._delete_after_import:
                    self._cleanup_path(cleanup_target)
            except Exception:
                result.failed += 1
                logger.exception("Failed to import %s", path)
                if self._on_notify:
                    self._on_notify(f"Failed to import {path.name}", "error")
        return result

    def _iter_export_targets(self) -> Iterable[Tuple[Path, Path]]:
        for entry in sorted(self._export_dir.iterdir()):
            if entry.is_file():
                yield entry, entry
                continue
            if not entry.is_dir():
                continue
            export_file = self._find_export_file(entry)
            if export_file is None:
                logger.debug("No export file found in %s", entry)
                continue
            yield export_file, entry

    def _find_export_file(self, folder: Path) -> Path | None:
        direct_files = [child for child in folder.iterdir() if child.is_file()]
        if direct_files:
            return sorted(direct_files)[0]
        for child in folder.rglob("*"):
            if child.is_file():
                return child
        return None

    def _cleanup_path(self, target: Path) -> None:
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()

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
