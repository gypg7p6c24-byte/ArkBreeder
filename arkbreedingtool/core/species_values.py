from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
from typing import Dict, List, Optional


STAT_COUNT = 12


@dataclass(frozen=True)
class StatRaw:
    base: float
    inc_wild: float
    inc_tamed: float
    taming_add: float
    taming_mult: float


@dataclass(frozen=True)
class SpeciesValues:
    name: str
    blueprint: str
    stats_raw: Dict[int, StatRaw]
    stat_imprint_mult: tuple[float, ...]
    no_imprinting_for_speed: bool
    tamed_base_health_multiplier: float


class SpeciesValuesStore:
    def __init__(self) -> None:
        self._by_name: Dict[str, SpeciesValues] = {}
        self._by_blueprint: Dict[str, SpeciesValues] = {}

    def count(self) -> int:
        return len(self._by_name)

    def load_values_file(self, path: Path) -> None:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        species_list = data.get("species", [])
        if not isinstance(species_list, list):
            return
        for entry in species_list:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name", "")).strip()
            blueprint = str(entry.get("blueprintPath", "")).strip()
            stats_raw = self._parse_stats(entry.get("fullStatsRaw"))
            stat_imprint_mult = self._parse_stat_imprint(entry.get("statImprintMult"))
            no_imprinting_for_speed = bool(entry.get("NoImprintingForSpeed", False))
            tbhm = float(entry.get("TamedBaseHealthMultiplier", 1.0) or 1.0)
            if not name or not stats_raw:
                continue
            values = SpeciesValues(
                name=name,
                blueprint=blueprint,
                stats_raw=stats_raw,
                stat_imprint_mult=stat_imprint_mult,
                no_imprinting_for_speed=no_imprinting_for_speed,
                tamed_base_health_multiplier=tbhm,
            )
            self._by_name[name.lower()] = values
            if blueprint:
                self._by_blueprint[_normalize_blueprint(blueprint)] = values

    def get_by_species(self, name: str) -> Optional[SpeciesValues]:
        return self._by_name.get(name.lower())

    def get_by_blueprint(self, blueprint: str) -> Optional[SpeciesValues]:
        return self._by_blueprint.get(_normalize_blueprint(blueprint))

    def _parse_stats(self, raw: object) -> Dict[int, StatRaw]:
        if not isinstance(raw, list):
            return {}
        stats: Dict[int, StatRaw] = {}
        for idx, entry in enumerate(raw):
            if entry is None:
                continue
            if not isinstance(entry, list) or len(entry) < 5:
                continue
            try:
                base, iw, it, ta, tm = entry[:5]
                stats[idx] = StatRaw(
                    base=float(base),
                    inc_wild=float(iw),
                    inc_tamed=float(it),
                    taming_add=float(ta),
                    taming_mult=float(tm),
                )
            except (TypeError, ValueError):
                continue
        return stats

    def _parse_stat_imprint(self, raw: object) -> tuple[float, ...]:
        if not isinstance(raw, list):
            return ()
        values: list[float] = []
        for entry in raw:
            try:
                values.append(float(entry))
            except (TypeError, ValueError):
                values.append(0.0)
        return tuple(values)


def _normalize_blueprint(blueprint: str) -> str:
    normalized = blueprint.strip().lower()
    if "." in normalized:
        normalized = normalized.split(".", 1)[0]
    if normalized.endswith("_c"):
        normalized = normalized[:-2]
    return normalized
