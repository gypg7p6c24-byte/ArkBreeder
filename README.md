# ARK Breeder

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
arkbreeder
```

## Logs
```bash
ARKBREEDER_LOG_LEVEL=DEBUG arkbreeder
```

## Project layout
- `arkbreeder/core`: parsing and breeding domain logic
- `arkbreeder/storage`: SQLite persistence and repositories
- `arkbreeder/ui`: PySide6 desktop UI

## Packaging
```bash
packaging/build_deb.sh 0.1.0
```
