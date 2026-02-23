# Ark Breeding Tool

Local breeding manager for ARK: Survival Evolved.

This application parses exported creature files (no OCR) and helps track
stats, mutations, and pedigrees, then suggests optimal breeding pairs.

## Status
Foundation only. Core breeding logic is not implemented yet.

## Requirements
- Python 3.12+
- Ubuntu 25.10 (target platform)

## Quick start
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
arkbreedingtool
```

## Logs
```bash
ARKBREEDINGTOOL_LOG_LEVEL=DEBUG arkbreedingtool
```

## Export watcher
By default the app watches:
`~/.steam/steam/steamapps/common/ARK/ShooterGame/Saved/DinoExports`

Override the path if needed:
```bash
ARKBREEDINGTOOL_EXPORT_DIR=/custom/path arkbreedingtool
```

## Project layout
- `arkbreedingtool/core`: parsing and breeding domain logic
- `arkbreedingtool/storage`: SQLite persistence and repositories
- `arkbreedingtool/ui`: PySide6 desktop UI

## Packaging
```bash
packaging/build_deb.sh 0.1.0
```

## Naming
- Product name: **Ark Breeding Tool**
- Technical command/module names stay `arkbreedingtool` for compatibility.

## Credits
- Developed with OpenAI Codex.

## Wiki
Wiki pages are versioned in this repository under:
- `docs/wiki/Home.md`
- `docs/wiki/Getting-Started.md`
- `docs/wiki/Creature-Import.md`
- `docs/wiki/Settings-and-Multipliers.md`
- `docs/wiki/Breeding-Workflow.md`
- `docs/wiki/Troubleshooting.md`
