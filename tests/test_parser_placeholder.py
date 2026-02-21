    from pathlib import Path

    from arkbreeder.core.parser import parse_creature_file


    def test_parse_creature_file(tmp_path: Path) -> None:
        sample = tmp_path / "creature.txt"
        sample.write_text("Name: Rex
Species: Rex
Level: 10
", encoding="utf-8")
        parsed = parse_creature_file(sample)
        assert parsed.name == "Rex"
        assert parsed.species == "Rex"
        assert parsed.level == 10
