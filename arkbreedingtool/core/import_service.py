from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
import shutil
from typing import Callable, Optional, Iterable

from arkbreedingtool.core.parser import ParsedCreature, parse_creature_file
from arkbreedingtool.storage.models import Creature
from arkbreedingtool.storage.repository import upsert_creature

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
        # Keep last seen file signature (mtime_ns, size) to avoid re-importing unchanged files.
        self._file_signatures: dict[str, tuple[int, int]] = {}

    def poll_once(self) -> ImportResult:
        result = ImportResult()
        if not self._export_dir.exists():
            logger.debug("Export directory does not exist: %s", self._export_dir)
            return result

        seen_paths: set[str] = set()
        for entry in sorted(self._export_dir.iterdir()):
            if entry.is_file():
                self._handle_file(entry, result, seen_paths=seen_paths)
                continue
            if entry.is_dir():
                self._handle_directory(entry, result, seen_paths=seen_paths)
        if self._file_signatures:
            stale = [key for key in self._file_signatures if key not in seen_paths]
            for key in stale:
                self._file_signatures.pop(key, None)
        return result

    def _handle_directory(
        self,
        folder: Path,
        result: ImportResult,
        seen_paths: set[str],
    ) -> None:
        files = list(self._list_export_files(folder))
        if not files:
            logger.debug("No export file found in %s", folder)
            return
        for file_path in files:
            self._handle_file(
                file_path,
                result,
                allow_dir_cleanup=False,
                seen_paths=seen_paths,
            )
        if self._delete_after_import and self._is_dir_empty(folder):
            shutil.rmtree(folder)

    def _handle_file(
        self,
        path: Path,
        result: ImportResult,
        allow_dir_cleanup: bool = True,
        seen_paths: set[str] | None = None,
    ) -> None:
        signature = self._file_signature(path)
        if signature is None:
            return
        file_key = str(path.resolve())
        if seen_paths is not None:
            seen_paths.add(file_key)
        if self._file_signatures.get(file_key) == signature:
            result.skipped += 1
            return
        try:
            parsed = parse_creature_file(path)
            if not parsed.external_id:
                result.failed += 1
                logger.warning("Skipped %s due to missing Dino IDs", path.name)
                if self._on_notify:
                    self._on_notify(f"Skipped {path.name} (missing ID)", "error")
                if self._delete_after_import:
                    path.unlink(missing_ok=True)
                    self._file_signatures.pop(file_key, None)
                    if allow_dir_cleanup:
                        parent = path.parent
                        if parent != self._export_dir and self._is_dir_empty(parent):
                            shutil.rmtree(parent)
                else:
                    self._file_signatures[file_key] = signature
                return
            existing_id: int | None = None
            if parsed.external_id:
                row = self._conn.execute(
                    "SELECT id FROM creatures WHERE external_id = ?",
                    (parsed.external_id,),
                ).fetchone()
                if row is not None:
                    existing_id = row["id"]
            creature = self._to_creature(parsed)
            saved = upsert_creature(self._conn, creature)
            result.imported += 1
            action = "Updated" if existing_id else "Imported"
            logger.info(
                "%s %s (%s) from %s",
                action,
                saved.name,
                saved.external_id or "no-id",
                path.name,
            )
            if self._on_notify:
                kind = "info" if existing_id else "success"
                self._on_notify(
                    f"{action} {saved.name}",
                    kind,
                )
                if (
                    parsed.baby_age is not None
                    and parsed.baby_age < 1.0
                    and not (parsed.mother_external_id and parsed.father_external_id)
                ):
                    self._on_notify(
                        "Baby lineage pending: open Ancestors in-game then re-export this dino.",
                        "info",
                    )
            if self._delete_after_import:
                path.unlink(missing_ok=True)
                self._file_signatures.pop(file_key, None)
                if allow_dir_cleanup:
                    parent = path.parent
                    if parent != self._export_dir and self._is_dir_empty(parent):
                        shutil.rmtree(parent)
            else:
                self._file_signatures[file_key] = signature
        except Exception:
            result.failed += 1
            logger.exception("Failed to import %s", path)
            if self._on_notify:
                self._on_notify(f"Failed to import {path.name}", "error")
            self._file_signatures[file_key] = signature

    def _file_signature(self, path: Path) -> tuple[int, int] | None:
        try:
            stat = path.stat()
        except OSError:
            return None
        return (int(stat.st_mtime_ns), int(stat.st_size))

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
            blueprint=parsed.blueprint,
            name=parsed.name,
            species=parsed.species,
            sex=parsed.sex,
            level=parsed.level,
            stats=parsed.stats,
            imprinting_quality=parsed.imprinting_quality,
            baby_age=parsed.baby_age,
            mutations_maternal=parsed.mutations_maternal or 0,
            mutations_paternal=parsed.mutations_paternal or 0,
            mother_external_id=parsed.mother_external_id,
            father_external_id=parsed.father_external_id,
        )
