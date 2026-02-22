from __future__ import annotations

from dataclasses import dataclass, field
import math
import re
from typing import Dict

from arkbreeder.core.species_values import SpeciesValues, StatRaw


STAT_INDEX_BY_KEY: dict[str, int] = {
    "Health": 0,
    "Stamina": 1,
    "Torpidity": 2,
    "Oxygen": 3,
    "Food": 4,
    "Water": 5,
    "Temperature": 6,
    "Weight": 7,
    "MeleeDamageMultiplier": 8,
    "MovementSpeed": 9,
    "Fortitude": 10,
    "CraftingSkill": 11,
}


@dataclass(frozen=True)
class StatBreakdown:
    total: float
    wild_levels: float
    tamed_levels: float
    imprinting_bonus: float
    mutations: float


@dataclass
class StatMultipliers:
    wild: Dict[int, float] = field(default_factory=dict)
    tamed: Dict[int, float] = field(default_factory=dict)
    tamed_add: Dict[int, float] = field(default_factory=dict)
    tamed_affinity: Dict[int, float] = field(default_factory=dict)
    imprinting: float = 1.0
    max_wild_level: int = 255


def extract_stat_multipliers(server_settings: dict | None) -> StatMultipliers:
    multipliers = StatMultipliers()
    if not server_settings:
        return multipliers

    for key in ("game_user_settings", "game_ini"):
        data = server_settings.get(key)
        _apply_multiplier_data(data, multipliers)

    return multipliers


def _apply_multiplier_data(data: object, multipliers: StatMultipliers) -> None:
    if not isinstance(data, dict):
        return
    for section in data.values():
        if not isinstance(section, dict):
            continue
        for raw_key, raw_value in section.items():
            if not isinstance(raw_key, str):
                continue
            key = raw_key.strip()
            value = _safe_float(raw_value)
            if value is None:
                continue

            if key.startswith("BabyImprintingStatScale"):
                multipliers.imprinting = value
                continue

            match = re.match(r"PerLevelStatsMultiplier_DinoWild\[(\d+)\]", key)
            if match:
                multipliers.wild[int(match.group(1))] = value
                continue
            match = re.match(r"PerLevelStatsMultiplier_DinoTamed\[(\d+)\]", key)
            if match:
                multipliers.tamed[int(match.group(1))] = value
                continue
            match = re.match(r"PerLevelStatsMultiplier_DinoTamed_Add\[(\d+)\]", key)
            if match:
                multipliers.tamed_add[int(match.group(1))] = value
                continue
            match = re.match(r"PerLevelStatsMultiplier_DinoTamed_Affinity\[(\d+)\]", key)
            if match:
                multipliers.tamed_affinity[int(match.group(1))] = value


def _safe_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def compute_wild_levels(
    stats: Dict[str, float],
    species_values: SpeciesValues | None = None,
    multipliers: StatMultipliers | None = None,
    imprinting_quality: float | None = None,
    max_wild_level: int | None = None,
) -> Dict[str, int]:
    if species_values is None:
        return {key: 0 for key in stats}
    multipliers = multipliers or StatMultipliers()
    max_wild = max_wild_level or multipliers.max_wild_level

    results: Dict[str, int] = {}
    for key, idx in STAT_INDEX_BY_KEY.items():
        if key not in stats:
            continue
        raw = species_values.stats_raw.get(idx)
        if raw is None:
            continue
        value = stats.get(key)
        if value is None:
            continue
        tbhm = species_values.tamed_base_health_multiplier if idx == 0 else 1.0
        level = estimate_wild_level(
            value,
            raw,
            idx,
            multipliers,
            tbhm,
            imprinting_quality,
            max_wild,
        )
        if level is not None:
            results[key] = level
    return results


def estimate_wild_level(
    stat_value: float,
    raw: StatRaw,
    index: int,
    multipliers: StatMultipliers,
    tbhm: float,
    imprinting_quality: float | None,
    max_wild_level: int,
) -> int | None:
    if stat_value is None or math.isnan(stat_value):
        return None

    best_level, best_error = _search_wild_levels(
        stat_value,
        raw,
        index,
        multipliers,
        tbhm,
        imprinting_quality,
        max_wild_level,
        use_tamed_bonus=True,
    )
    alt_level, alt_error = _search_wild_levels(
        stat_value,
        raw,
        index,
        multipliers,
        tbhm,
        imprinting_quality,
        max_wild_level,
        use_tamed_bonus=False,
    )

    if alt_error < best_error:
        return alt_level
    return best_level


def _search_wild_levels(
    stat_value: float,
    raw: StatRaw,
    index: int,
    multipliers: StatMultipliers,
    tbhm: float,
    imprinting_quality: float | None,
    max_wild_level: int,
    use_tamed_bonus: bool,
) -> tuple[int, float]:
    best_level = 0
    best_error = float("inf")
    for level in range(0, max_wild_level + 1):
        expected = _expected_stat_value(
            level,
            raw,
            index,
            multipliers,
            tbhm,
            imprinting_quality,
            use_tamed_bonus,
        )
        error = abs(expected - stat_value)
        if error < best_error:
            best_error = error
            best_level = level
            if error == 0:
                break
    return best_level, best_error


def _expected_stat_value(
    wild_levels: int,
    raw: StatRaw,
    index: int,
    multipliers: StatMultipliers,
    tbhm: float,
    imprinting_quality: float | None,
    use_tamed_bonus: bool,
) -> float:
    wild_mult = multipliers.wild.get(index, 1.0)
    base = raw.base * (1.0 + (wild_levels * raw.inc_wild * wild_mult)) * tbhm
    imprint = max(imprinting_quality or 0.0, 0.0)
    base *= 1.0 + imprint * 0.2 * multipliers.imprinting

    if use_tamed_bonus:
        base += raw.taming_add * multipliers.tamed_add.get(index, 1.0)
        base *= 1.0 + raw.taming_mult * multipliers.tamed_affinity.get(index, 1.0)

    return base
