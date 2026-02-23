from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable


@dataclass(frozen=True)
class ParsedCreature:
    name: str
    species: str
    sex: str
    level: int
    stats: Dict[str, float]
    external_id: str | None
    mutations_maternal: int | None
    mutations_paternal: int | None
    mother_external_id: str | None
    father_external_id: str | None
    blueprint: str | None
    imprinting_quality: float | None
    baby_age: float | None
    raw_text: str


def parse_creature_file(path: Path) -> ParsedCreature:
    """
    Placeholder parser for exported creature files.
    This implementation reads the file and extracts a few common fields if present.
    """
    text = _read_text(path)
    sections = _parse_sections(text)
    dino_data = _get_section(sections, "Dino Data")
    stat_section = _get_section(sections, "Max Character Status Values")

    dino_class = dino_data.get("DinoClass", "")
    species = _extract_species(dino_class) or "Unknown"
    tamed_name = (dino_data.get("TamedName") or "").strip()
    name_tag = (dino_data.get("DinoNameTag") or "").strip()
    name = tamed_name or name_tag or species or "Unknown"
    sex = _parse_sex(dino_data.get("bIsFemale"))
    level = _parse_int(dino_data.get("CharacterLevel"), default=0)
    imprinting_quality = _parse_float(dino_data.get("DinoImprintingQuality"))
    baby_age = _parse_float(dino_data.get("BabyAge"))

    dino_id_1 = dino_data.get("DinoID1")
    dino_id_2 = dino_data.get("DinoID2")
    external_id: str | None = None
    if dino_id_1 and dino_id_2:
        external_id = f"{dino_id_1}-{dino_id_2}"
    elif dino_id_1:
        external_id = dino_id_1

    mutations_paternal = _parse_int(dino_data.get("RandomMutationsMale"))
    mutations_maternal = _parse_int(dino_data.get("RandomMutationsFemale"))

    mother_external_id: str | None = None
    father_external_id: str | None = None
    ancestors = _get_section(sections, "DinoAncestors")
    if ancestors:
        ancestor_line = _first_value(ancestors)
        mother_external_id, father_external_id = _parse_ancestor_line(ancestor_line)
    if not (mother_external_id and father_external_id):
        for section_name in ("DinoAncestorsMale", "DinoAncestorsFemale"):
            section = _get_section(sections, section_name)
            if not section:
                continue
            fallback_mother, fallback_father = _parse_ancestor_line(_first_value(section))
            mother_external_id = mother_external_id or fallback_mother
            father_external_id = father_external_id or fallback_father
            if mother_external_id and father_external_id:
                break

    stats: Dict[str, float] = {}
    for key, value in stat_section.items():
        normalized = _normalize_stat_key(key)
        if normalized is None:
            continue
        parsed = _parse_float(value)
        if parsed is not None:
            stats[normalized] = parsed

    return ParsedCreature(
        name=name,
        species=species,
        sex=sex,
        level=level,
        stats=stats,
        external_id=external_id,
        mutations_maternal=mutations_maternal,
        mutations_paternal=mutations_paternal,
        mother_external_id=mother_external_id,
        father_external_id=father_external_id,
        blueprint=dino_class or None,
        imprinting_quality=imprinting_quality,
        baby_age=baby_age,
        raw_text=text,
    )


def _parse_sections(text: str) -> dict[str, dict[str, str]]:
    sections: dict[str, dict[str, str]] = {}
    current: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1].strip()
            sections.setdefault(current, {})
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if current is None:
            current = ""
            sections.setdefault(current, {})
        sections[current][key] = value
    return sections


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in _candidate_encodings(raw):
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        text = text.lstrip("\ufeff")
        if _looks_valid_export(text):
            return text
    return raw.decode("utf-8", errors="replace")


def _candidate_encodings(raw: bytes) -> Iterable[str]:
    if raw.startswith(b"\xff\xfe"):
        return ["utf-16-le", "utf-8", "cp1252"]
    if raw.startswith(b"\xfe\xff"):
        return ["utf-16-be", "utf-8", "cp1252"]
    return ["utf-8", "utf-8-sig", "utf-16-le", "utf-16-be", "cp1252"]


def _looks_valid_export(text: str) -> bool:
    if "\x00" in text:
        return False
    if "[Dino Data]" in text:
        return True
    if "[DinoData]" in text:
        return True
    return "DinoID1=" in text and "DinoID2=" in text


def _get_section(
    sections: dict[str, dict[str, str]],
    name: str,
) -> dict[str, str]:
    if name in sections:
        return sections[name]
    lowered = {key.lower(): key for key in sections}
    if name.lower() in lowered:
        return sections[lowered[name.lower()]]
    normalized = _normalize_section_name(name)
    if normalized:
        for key in sections:
            if _normalize_section_name(key) == normalized:
                return sections[key]
    return {}


def _normalize_section_name(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


def _parse_sex(value: str | None) -> str:
    if value is None:
        return "Unknown"
    lowered = value.strip().lower()
    if lowered in {"true", "1", "yes"}:
        return "Female"
    if lowered in {"false", "0", "no"}:
        return "Male"
    return "Unknown"


def _parse_int(value: str | None, default: int | None = None) -> int | None:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    text = value.strip()
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text and "." not in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _extract_species(dino_class: str) -> str | None:
    if not dino_class:
        return None
    if "/" in dino_class:
        parts = [part for part in dino_class.split("/") if part]
        if len(parts) >= 2:
            return parts[-2]
        return parts[-1] if parts else None
    if "." in dino_class:
        return dino_class.split(".", 1)[0]
    return dino_class


def _first_value(section: dict[str, str]) -> str:
    if not section:
        return ""
    return next(iter(section.values()))


def _parse_ancestor_line(line: str) -> tuple[str | None, str | None]:
    if not line:
        return None, None
    male_id = _extract_id_pair(line, "MaleDinoID1", "MaleDinoID2")
    female_id = _extract_id_pair(line, "FemaleDinoID1", "FemaleDinoID2")
    return female_id, male_id


def _extract_id_pair(line: str, key1: str, key2: str) -> str | None:
    try:
        parts = [segment.strip() for segment in line.split(";") if segment.strip()]
    except Exception:
        return None
    values: dict[str, str] = {}
    for part in parts:
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        values[key.strip()] = value.strip()
    v1 = values.get(key1)
    v2 = values.get(key2)
    if v1 and v2:
        return f"{v1}-{v2}"
    return None


def _normalize_stat_key(key: str) -> str | None:
    cleaned = key.strip()
    if not cleaned:
        return None
    collapsed = "".join(ch for ch in cleaned.lower() if ch.isalnum())
    mapping = {
        "health": "Health",
        "stamina": "Stamina",
        "torpidity": "Torpidity",
        "oxygen": "Oxygen",
        "food": "Food",
        "water": "Water",
        "temperature": "Temperature",
        "weight": "Weight",
        "meleedamage": "MeleeDamageMultiplier",
        "meleedamagemultiplier": "MeleeDamageMultiplier",
        "movementspeed": "MovementSpeed",
        "fortitude": "Fortitude",
        "craftingskill": "CraftingSkill",
    }
    return mapping.get(collapsed, cleaned)
