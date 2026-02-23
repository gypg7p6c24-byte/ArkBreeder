from pathlib import Path

from arkbreedingtool.core.parser import parse_creature_file


def test_parse_creature_file(tmp_path: Path) -> None:
    sample = tmp_path / "creature.ini"
    sample.write_text(
        "[Dino Data]\n"
        "TamedName=Rex\n"
        "DinoClass=Rex_Character_BP_C\n"
        "bIsFemale=false\n"
        "CharacterLevel=10\n"
        "\n"
        "[Max Character Status Values]\n"
        "Health=1100\n",
        encoding="utf-8",
    )
    parsed = parse_creature_file(sample)
    assert parsed.name == "Rex"
    assert parsed.species == "Rex_Character_BP_C"
    assert parsed.level == 10
