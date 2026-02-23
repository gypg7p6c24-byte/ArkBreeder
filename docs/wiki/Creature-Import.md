# Creature Import

## Expected source
ARK exports creature files in `ShooterGame/Saved/DinoExports`.

## How import works
- The app watches the export folder.
- New or changed files are parsed and stored.
- Deleting a creature from the app also removes matching export files.

## Good practice
- Keep your export folder dedicated to one server profile.
- Re-export a creature after level-up if you need fresh values.
