#!/usr/bin/env bash
set -euo pipefail

APP_NAME="ark-breeder"
VERSION="${1:-0.1.0}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="$ROOT_DIR/dist/deb"
PKG_DIR="$BUILD_DIR/${APP_NAME}_${VERSION}"

rm -rf "$BUILD_DIR"
mkdir -p "$PKG_DIR/DEBIAN"
mkdir -p "$PKG_DIR/usr/lib/$APP_NAME"
mkdir -p "$PKG_DIR/usr/bin"
mkdir -p "$PKG_DIR/usr/share/applications"
mkdir -p "$PKG_DIR/usr/share/icons/hicolor/scalable/apps"

rsync -a --exclude '__pycache__' "$ROOT_DIR/arkbreeder" "$PKG_DIR/usr/lib/$APP_NAME/"
rsync -a "$ROOT_DIR/README.md" "$ROOT_DIR/LICENSE" "$ROOT_DIR/pyproject.toml" "$PKG_DIR/usr/lib/$APP_NAME/"

cat > "$PKG_DIR/usr/bin/ark-breeder" <<'EOF'
#!/usr/bin/env bash
export PYTHONPATH="/usr/lib/ark-breeder:${PYTHONPATH:-}"
exec /usr/bin/python3 -m arkbreeder.ui.app "$@"
EOF
chmod +x "$PKG_DIR/usr/bin/ark-breeder"

install -m 644 "$ROOT_DIR/packaging/arkbreeder.desktop" "$PKG_DIR/usr/share/applications/arkbreeder.desktop"
install -m 644 "$ROOT_DIR/packaging/arkbreeder.svg" "$PKG_DIR/usr/share/icons/hicolor/scalable/apps/arkbreeder.svg"

cat > "$PKG_DIR/DEBIAN/control" <<EOF
Package: $APP_NAME
Version: $VERSION
Section: utils
Priority: optional
Architecture: all
Depends: python3 (>=3.12), python3-pyside6
Maintainer: ARK Breeder Contributors
Description: Local breeding manager for ARK: Survival Evolved.
 Foundation release with parsing and storage scaffolding.
EOF

dpkg-deb --build "$PKG_DIR" "$BUILD_DIR/${APP_NAME}_${VERSION}_all.deb"
echo "Built $BUILD_DIR/${APP_NAME}_${VERSION}_all.deb"
