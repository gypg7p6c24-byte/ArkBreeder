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


def test_parse_creature_file_uses_dino_name_tag_when_tamed_name_is_empty(tmp_path: Path) -> None:
    sample = tmp_path / "creature_no_tamed_name.ini"
    sample.write_text(
        "[Dino Data]\n"
        "TamedName=\n"
        "DinoNameTag=Ptero\n"
        "DinoClass=/Game/PrimalEarth/Dinos/Ptero/Ptero_Character_BP.Ptero_Character_BP_C\n"
        "bIsFemale=true\n"
        "CharacterLevel=150\n"
        "\n"
        "[Max Character Status Values]\n"
        "Health=800\n",
        encoding="utf-8",
    )

    parsed = parse_creature_file(sample)

    assert parsed.name == "Ptero"
    assert parsed.species == "Ptero"
    assert parsed.level == 150
