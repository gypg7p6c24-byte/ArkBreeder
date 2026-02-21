from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Dict


@dataclass(frozen=True)
class ParsedCreature:
    name: str
    species: str
    sex: str
    level: int
    stats: Dict[str, int]
    external_id: str | None
    mutations_maternal: int | None
    mutations_paternal: int | None
    raw_text: str


def parse_creature_file(path: Path) -> ParsedCreature:
    """
    Placeholder parser for exported creature files.
    This implementation reads the file and extracts a few common fields if present.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    name = "Unknown"
    species = "Unknown"
    sex = "Unknown"
    level = 0
    stats: Dict[str, int] = {}
    external_id: str | None = None
    mutations_maternal: int | None = None
    mutations_paternal: int | None = None
    dino_id_1: str | None = None
    dino_id_2: str | None = None

    for line in text.splitlines():
        lower = line.lower().strip()
        normalized = lower.replace(" ", "")
        if normalized.startswith("name"):
            name = _split_field(line, default=name)
        elif normalized.startswith("species"):
            species = _split_field(line, default=species)
        elif normalized.startswith("sex"):
            sex = _split_field(line, default=sex)
        elif normalized.startswith("level"):
            value = _split_field(line, default="0")
            try:
                level = int(value)
            except ValueError:
                pass
        elif "dinoid1" in normalized:
            dino_id_1 = _extract_digits(line) or dino_id_1
        elif "dinoid2" in normalized:
            dino_id_2 = _extract_digits(line) or dino_id_2
        elif "dinoid" in normalized and external_id is None:
            external_id = _extract_digits(line)
        elif "mutation" in normalized and (mutations_maternal is None or mutations_paternal is None):
            maternal, paternal = _extract_mutations(line)
            if maternal is not None:
                mutations_maternal = maternal
            if paternal is not None:
                mutations_paternal = paternal

    if dino_id_1 and dino_id_2:
        external_id = f"{dino_id_1}-{dino_id_2}"
    elif dino_id_1 and external_id is None:
        external_id = dino_id_1

    return ParsedCreature(
        name=name,
        species=species,
        sex=sex,
        level=level,
        stats=stats,
        external_id=external_id,
        mutations_maternal=mutations_maternal,
        mutations_paternal=mutations_paternal,
        raw_text=text,
    )


def _split_field(line: str, default: str) -> str:
    if ":" not in line:
        return default
    return line.split(":", 1)[1].strip() or default


_DIGITS = re.compile(r"(\d+)")


def _extract_digits(line: str) -> str | None:
    match = _DIGITS.search(line)
    if not match:
        return None
    return match.group(1)


def _extract_mutations(line: str) -> tuple[int | None, int | None]:
    match = re.search(r"(\d+)\s*[/,:-]\s*(\d+)", line)
    if not match:
        return None, None
    try:
        return int(match.group(1)), int(match.group(2))
    except ValueError:
        return None, None
