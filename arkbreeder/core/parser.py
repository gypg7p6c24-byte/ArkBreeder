from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict


@dataclass(frozen=True)
class ParsedCreature:
    name: str
    species: str
    level: int
    stats: Dict[str, int]
    raw_text: str


def parse_creature_file(path: Path) -> ParsedCreature:
    '''
    Placeholder parser for exported creature files.
    This implementation reads the file and extracts a few common fields if present.
    '''
    text = path.read_text(encoding="utf-8", errors="replace")
    name = "Unknown"
    species = "Unknown"
    level = 0
    stats: Dict[str, int] = {}

    for line in text.splitlines():
        lower = line.lower().strip()
        if lower.startswith("name"):
            name = _split_field(line, default=name)
        elif lower.startswith("species"):
            species = _split_field(line, default=species)
        elif lower.startswith("level"):
            value = _split_field(line, default="0")
            try:
                level = int(value)
            except ValueError:
                pass

    return ParsedCreature(
        name=name,
        species=species,
        level=level,
        stats=stats,
        raw_text=text,
    )


def _split_field(line: str, default: str) -> str:
    if ":" not in line:
        return default
    return line.split(":", 1)[1].strip() or default
