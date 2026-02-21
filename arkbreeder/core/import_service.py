from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
import shutil
from typing import Callable, Optional, Iterable

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

        for entry in sorted(self._export_dir.iterdir()):
            if entry.is_file():
                self._handle_file(entry, result)
                continue
            if entry.is_dir():
                self._handle_directory(entry, result)
        return result

    def _handle_directory(self, folder: Path, result: ImportResult) -> None:
        files = list(self._list_export_files(folder))
        if not files:
            logger.debug("No export file found in %s", folder)
            return
        for file_path in files:
            self._handle_file(file_path, result, allow_dir_cleanup=False)
        if self._delete_after_import and self._is_dir_empty(folder):
            shutil.rmtree(folder)

    def _handle_file(
        self,
        path: Path,
        result: ImportResult,
        allow_dir_cleanup: bool = True,
    ) -> None:
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
                path.unlink(missing_ok=True)
                if allow_dir_cleanup:
                    parent = path.parent
                    if parent != self._export_dir and self._is_dir_empty(parent):
                        shutil.rmtree(parent)
        except Exception:
            result.failed += 1
            logger.exception("Failed to import %s", path)
            if self._on_notify:
                self._on_notify(f"Failed to import {path.name}", "error")

    def _list_export_files(self, folder: Path) -> Iterable[Path]:
        for child in sorted(folder.rglob("*")):
            if child.is_file():
                yield child

    def _is_dir_empty(self, folder: Path) -> bool:
        return not any(folder.iterdir())

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
