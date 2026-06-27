#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_DIR"

python -m PyInstaller --noconfirm --clean PortClaw.spec
/usr/bin/xattr -dr com.apple.quarantine "$PROJECT_DIR/dist/PortClaw.app" 2>/dev/null || true

cat <<EOF
PyInstaller app built:
  $PROJECT_DIR/dist/PortClaw.app

Open it with:
  open "$PROJECT_DIR/dist/PortClaw.app"
EOF
