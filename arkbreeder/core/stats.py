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

PERCENTAGE_DISPLAY_STATS = {8, 9, 10, 11}
DEFAULT_STAT_IMPRINT_MULT = (
    0.2,
    0.0,
    0.2,
    0.0,
    0.2,
    0.2,
    0.0,
    0.2,
    0.2,
    0.2,
    0.0,
    0.0,
)


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
    max_wild_level: int | None = None


def extract_stat_multipliers(server_settings: dict | None) -> StatMultipliers:
    multipliers = StatMultipliers()
    if not server_settings:
        return multipliers

    for key in ("game_user_settings", "game_ini"):
        data = server_settings.get(key)
        _apply_multiplier_data(data, multipliers)
    _apply_manual_overrides(server_settings.get("manual_overrides"), multipliers)

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


def _apply_manual_overrides(data: object, multipliers: StatMultipliers) -> None:
    if not isinstance(data, dict):
        return
    imprint = _safe_float(data.get("imprinting"))
    if imprint is not None:
        multipliers.imprinting = imprint

    stats = data.get("stats")
    if not isinstance(stats, dict):
        return
    for stat_key, row in stats.items():
        if not isinstance(stat_key, str) or not isinstance(row, dict):
            continue
        index = STAT_INDEX_BY_KEY.get(stat_key)
        if index is None:
            continue
        wild = _safe_float(row.get("wild"))
        if wild is not None:
            multipliers.wild[index] = wild
        tamed = _safe_float(row.get("tamed"))
        if tamed is not None:
            multipliers.tamed[index] = tamed
        tamed_add = _safe_float(row.get("add"))
        if tamed_add is not None:
            multipliers.tamed_add[index] = tamed_add
        affinity = _safe_float(row.get("affinity"))
        if affinity is not None:
            multipliers.tamed_affinity[index] = affinity


def compute_wild_levels(
    stats: Dict[str, float],
    species_values: SpeciesValues | None = None,
    multipliers: StatMultipliers | None = None,
    imprinting_quality: float | None = None,
    max_wild_level: int | None = None,
    character_level: int | None = None,
    taming_effectiveness_hint: float | None = None,
) -> Dict[str, int]:
    if species_values is None:
        return {}
    multipliers = multipliers or StatMultipliers()
    if max_wild_level is not None:
        max_wild = max_wild_level
    elif multipliers.max_wild_level is not None:
        max_wild = multipliers.max_wild_level
    elif character_level is not None and character_level > 1:
        # Servers can run creatures well above official limits.
        # Without an explicit cap, use the creature level budget as upper bound.
        max_wild = character_level - 1
    else:
        max_wild = 255

    torpor_level = _estimate_torpor_wild_level(
        stats=stats,
        species_values=species_values,
        multipliers=multipliers,
        imprinting_quality=imprinting_quality,
        max_wild=max_wild,
        taming_effectiveness_hint=taming_effectiveness_hint,
    )
    if torpor_level is not None:
        constrained = _estimate_with_level_budget(
            stats=stats,
            species_values=species_values,
            multipliers=multipliers,
            imprinting_quality=imprinting_quality,
            max_wild=max_wild,
            level_wild_sum=torpor_level,
            character_level=character_level,
            taming_effectiveness_hint=taming_effectiveness_hint,
        )
        if constrained:
            return constrained

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
        stat_imprint_mult = _species_stat_imprint_multiplier(species_values, idx)
        level = estimate_wild_level(
            value,
            raw,
            idx,
            multipliers,
            tbhm,
            stat_imprint_mult,
            imprinting_quality,
            max_wild,
            taming_effectiveness_hint=taming_effectiveness_hint,
        )
        if level is not None:
            results[key] = level
    return results


def _estimate_torpor_wild_level(
    stats: Dict[str, float],
    species_values: SpeciesValues,
    multipliers: StatMultipliers,
    imprinting_quality: float | None,
    max_wild: int,
    taming_effectiveness_hint: float | None = None,
) -> int | None:
    if "Torpidity" not in stats:
        return None
    raw = species_values.stats_raw.get(STAT_INDEX_BY_KEY["Torpidity"])
    value = stats.get("Torpidity")
    if raw is None or value is None:
        return None
    return estimate_wild_level(
        stat_value=value,
        raw=raw,
        index=STAT_INDEX_BY_KEY["Torpidity"],
        multipliers=multipliers,
        tbhm=1.0,
        stat_imprint_mult=_species_stat_imprint_multiplier(
            species_values,
            STAT_INDEX_BY_KEY["Torpidity"],
        ),
        imprinting_quality=imprinting_quality,
        max_wild_level=max_wild,
        taming_effectiveness_hint=taming_effectiveness_hint,
    )


def _estimate_with_level_budget(
    stats: Dict[str, float],
    species_values: SpeciesValues,
    multipliers: StatMultipliers,
    imprinting_quality: float | None,
    max_wild: int,
    level_wild_sum: int,
    character_level: int | None,
    taming_effectiveness_hint: float | None = None,
) -> Dict[str, int]:
    if level_wild_sum <= 0:
        return {}

    max_dom_levels = 0
    if character_level is not None and character_level > 1:
        max_dom_levels = max(0, character_level - 1 - level_wild_sum)

    keys: list[str] = []
    costs_by_key: dict[str, list[float]] = {}
    for key, idx in STAT_INDEX_BY_KEY.items():
        if key == "Torpidity":
            continue
        value = stats.get(key)
        raw = species_values.stats_raw.get(idx)
        if value is None or raw is None:
            continue
        if raw.inc_wild <= 0:
            continue
        tbhm = species_values.tamed_base_health_multiplier if idx == STAT_INDEX_BY_KEY["Health"] else 1.0
        stat_imprint_mult = _species_stat_imprint_multiplier(species_values, idx)
        per_level_cost: list[float] = []
        for wild_level in range(0, level_wild_sum + 1):
            error = _fit_stat_error_for_wild_level(
                target_value=value,
                wild_level=wild_level,
                raw=raw,
                index=idx,
                multipliers=multipliers,
                tbhm=tbhm,
                stat_imprint_mult=stat_imprint_mult,
                imprinting_quality=imprinting_quality,
                max_dom_levels=max_dom_levels,
                taming_effectiveness_hint=taming_effectiveness_hint,
            )
            per_level_cost.append(error)
        keys.append(key)
        costs_by_key[key] = per_level_cost

    if not keys:
        return {"Torpidity": level_wild_sum}

    inf = float("inf")
    dp = [inf] * (level_wild_sum + 1)
    dp[0] = 0.0
    backtrack: list[list[int]] = []

    for key in keys:
        per_level_cost = costs_by_key[key]
        new_dp = [inf] * (level_wild_sum + 1)
        parent = [-1] * (level_wild_sum + 1)
        for used in range(0, level_wild_sum + 1):
            current_cost = dp[used]
            if not math.isfinite(current_cost):
                continue
            remaining = level_wild_sum - used
            for wild_level in range(0, remaining + 1):
                candidate = current_cost + per_level_cost[wild_level]
                nxt = used + wild_level
                if candidate < new_dp[nxt]:
                    new_dp[nxt] = candidate
                    parent[nxt] = wild_level
        dp = new_dp
        backtrack.append(parent)

    best_sum = 0
    best_score = float("inf")
    for used in range(0, level_wild_sum + 1):
        score = dp[used] + (level_wild_sum - used) * 0.02
        if score < best_score:
            best_score = score
            best_sum = used

    if not math.isfinite(best_score):
        return {}

    results: Dict[str, int] = {"Torpidity": level_wild_sum}
    remaining = best_sum
    for index in range(len(keys) - 1, -1, -1):
        chosen = backtrack[index][remaining]
        if chosen < 0:
            chosen = 0
        key = keys[index]
        results[key] = chosen
        remaining -= chosen

    for key, idx in STAT_INDEX_BY_KEY.items():
        if key in results or key not in stats:
            continue
        raw = species_values.stats_raw.get(idx)
        value = stats.get(key)
        if raw is None or value is None:
            continue
        tbhm = species_values.tamed_base_health_multiplier if idx == STAT_INDEX_BY_KEY["Health"] else 1.0
        stat_imprint_mult = _species_stat_imprint_multiplier(species_values, idx)
        level = estimate_wild_level(
            stat_value=value,
            raw=raw,
            index=idx,
            multipliers=multipliers,
            tbhm=tbhm,
            stat_imprint_mult=stat_imprint_mult,
            imprinting_quality=imprinting_quality,
            max_wild_level=min(max_wild, level_wild_sum),
            taming_effectiveness_hint=taming_effectiveness_hint,
        )
        if level is not None:
            results[key] = level
    return results


def _fit_stat_error_for_wild_level(
    target_value: float,
    wild_level: int,
    raw: StatRaw,
    index: int,
    multipliers: StatMultipliers,
    tbhm: float,
    stat_imprint_mult: float,
    imprinting_quality: float | None,
    max_dom_levels: int,
    taming_effectiveness_hint: float | None = None,
) -> float:
    if target_value <= 0:
        return 0.0

    if taming_effectiveness_hint is not None:
        te_candidates = [max(0.0, min(1.0, float(taming_effectiveness_hint)))]
    else:
        te_candidates = [0.0]
        if raw.taming_mult > 0:
            te_candidates = [step / 20 for step in range(0, 21)]

    dom_mult = multipliers.tamed.get(index, 1.0)
    inc_tamed = raw.inc_tamed * dom_mult
    best_error = float("inf")
    additive_dom_stat = index in PERCENTAGE_DISPLAY_STATS

    for taming_effectiveness in te_candidates:
        base_value, _ = _expected_stat_value(
            wild_levels=wild_level,
            raw=raw,
            index=index,
            multipliers=multipliers,
            tbhm=tbhm,
            stat_imprint_mult=stat_imprint_mult,
            imprinting_quality=imprinting_quality,
            taming_effectiveness=taming_effectiveness,
        )
        if base_value <= 0:
            continue

        predicted = base_value
        if inc_tamed > 0:
            if additive_dom_stat:
                dom_estimated = int(round((target_value - base_value) / inc_tamed))
            else:
                dom_estimated = int(round((target_value / base_value - 1.0) / inc_tamed))
            dom_clamped = max(0, min(max_dom_levels, dom_estimated))
            if additive_dom_stat:
                predicted = base_value + dom_clamped * inc_tamed
            else:
                predicted = base_value * (1.0 + dom_clamped * inc_tamed)

        error = abs(predicted - target_value)
        if error < best_error:
            best_error = error

    return best_error


def estimate_wild_level(
    stat_value: float,
    raw: StatRaw,
    index: int,
    multipliers: StatMultipliers,
    tbhm: float,
    stat_imprint_mult: float,
    imprinting_quality: float | None,
    max_wild_level: int,
    taming_effectiveness_hint: float | None = None,
) -> int | None:
    if stat_value is None or math.isnan(stat_value):
        return None

    best_level = 0
    best_error = float("inf")
    for level in range(0, max_wild_level + 1):
        expected, _ = _expected_stat_value_best_te(
            wild_levels=level,
            raw=raw,
            index=index,
            multipliers=multipliers,
            tbhm=tbhm,
            stat_imprint_mult=stat_imprint_mult,
            imprinting_quality=imprinting_quality,
            target_value=stat_value,
            taming_effectiveness_hint=taming_effectiveness_hint,
        )
        error = abs(expected - stat_value)
        if error < best_error:
            best_error = error
            best_level = level
            if error <= _acceptable_error(index):
                break
    return best_level


def _expected_stat_value_best_te(
    wild_levels: int,
    raw: StatRaw,
    index: int,
    multipliers: StatMultipliers,
    tbhm: float,
    stat_imprint_mult: float,
    imprinting_quality: float | None,
    target_value: float,
    taming_effectiveness_hint: float | None = None,
) -> tuple[float, float]:
    if taming_effectiveness_hint is not None:
        te_fixed = max(0.0, min(1.0, float(taming_effectiveness_hint)))
        value_fixed, _ = _expected_stat_value(
            wild_levels=wild_levels,
            raw=raw,
            index=index,
            multipliers=multipliers,
            tbhm=tbhm,
            stat_imprint_mult=stat_imprint_mult,
            imprinting_quality=imprinting_quality,
            taming_effectiveness=te_fixed,
        )
        return value_fixed, te_fixed

    value_te0, tm_scaled = _expected_stat_value(
        wild_levels=wild_levels,
        raw=raw,
        index=index,
        multipliers=multipliers,
        tbhm=tbhm,
        stat_imprint_mult=stat_imprint_mult,
        imprinting_quality=imprinting_quality,
        taming_effectiveness=0.0,
    )
    if tm_scaled <= 0 or value_te0 <= 0:
        return value_te0, 0.0

    te_estimated = (target_value / value_te0 - 1.0) / tm_scaled
    te_clamped = max(0.0, min(1.0, te_estimated))
    value_with_te = value_te0 * (1.0 + tm_scaled * te_clamped)
    return value_with_te, te_clamped


def _expected_stat_value(
    wild_levels: int,
    raw: StatRaw,
    index: int,
    multipliers: StatMultipliers,
    tbhm: float,
    stat_imprint_mult: float,
    imprinting_quality: float | None,
    taming_effectiveness: float,
) -> tuple[float, float]:
    wild_mult = multipliers.wild.get(index, 1.0)
    wild_level_increase = wild_levels * raw.inc_wild * wild_mult

    imprint = max(imprinting_quality or 0.0, 0.0)
    imprint_multiplier = 1.0 + stat_imprint_mult * imprint * multipliers.imprinting

    add_scale = multipliers.tamed_add.get(index, 1.0) if raw.taming_add > 0 else 1.0
    add_value = raw.taming_add * add_scale

    if raw.taming_mult > 0:
        affinity_scale = multipliers.tamed_affinity.get(index, 1.0)
        tm_scaled = raw.taming_mult * affinity_scale
    else:
        tm_scaled = 0.0

    base_value = raw.base * (1.0 + wild_level_increase) * tbhm * imprint_multiplier
    base_value = base_value + add_value
    if tm_scaled > 0:
        value = base_value * (1.0 + tm_scaled * taming_effectiveness)
    else:
        value = base_value
    return value, max(tm_scaled, 0.0)


def _acceptable_error(index: int) -> float:
    return 0.001 if index in PERCENTAGE_DISPLAY_STATS else 0.2


def _species_stat_imprint_multiplier(species_values: SpeciesValues, index: int) -> float:
    if index == 9 and species_values.no_imprinting_for_speed:
        return 0.0
    if index < len(species_values.stat_imprint_mult):
        return species_values.stat_imprint_mult[index]
    if index < len(DEFAULT_STAT_IMPRINT_MULT):
        return DEFAULT_STAT_IMPRINT_MULT[index]
    return 0.0
