from __future__ import annotations

from pathlib import Path
import configparser


def parse_ini_file(path: Path) -> dict[str, dict[str, str]]:
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    try:
        parser.read(path, encoding="utf-8")
        return {section: dict(parser.items(section)) for section in parser.sections()}
    except configparser.MissingSectionHeaderError:
        return _parse_without_sections(path)


def _parse_without_sections(path: Path) -> dict[str, dict[str, str]]:
    data: dict[str, dict[str, str]] = {"": {}}
    text = path.read_text(encoding="utf-8", errors="replace")
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", ";", "//")):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key:
            data[""][key] = value
    return data
