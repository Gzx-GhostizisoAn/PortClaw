#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_PATH="${1:-$HOME/Applications/PortClaw.app}"
RUNTIME_DIR="$HOME/Library/Application Support/PortClaw/app"
LAUNCHER_DIR="$PROJECT_DIR/launchers/macos"

if [[ ! -f "$PROJECT_DIR/desktop_app.py" || ! -f "$PROJECT_DIR/app.py" ]]; then
  echo "This script must be run from a complete PortClaw source checkout." >&2
  exit 1
fi

if [[ ! -f "$LAUNCHER_DIR/Info.plist" || ! -f "$LAUNCHER_DIR/PortClaw" ]]; then
  echo "Missing macOS launcher files under launchers/macos." >&2
  exit 1
fi

mkdir -p "$(dirname "$APP_PATH")"
mkdir -p "$RUNTIME_DIR"

rsync -a --delete \
  --exclude '.git/' \
  --exclude '.venv/' \
  --exclude 'venv/' \
  --exclude 'env/' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude '.DS_Store' \
  --exclude '.cache/' \
  --exclude '.pytest_cache/' \
  --exclude '.mypy_cache/' \
  --exclude '.ruff_cache/' \
  --exclude 'config/local_config.json' \
  --exclude 'data/portfolio.local.json' \
  --exclude 'data/trades.local.jsonl' \
  --exclude 'audit_runs/' \
  --exclude 'messages/' \
  --exclude 'outputs/' \
  --exclude 'dist/' \
  --exclude 'decks/' \
  --exclude 'videos/' \
  --exclude 'experiments/' \
  "$PROJECT_DIR/" "$RUNTIME_DIR/"

rm -rf "$APP_PATH"
mkdir -p "$APP_PATH/Contents/MacOS" "$APP_PATH/Contents/Resources"

cp "$LAUNCHER_DIR/Info.plist" "$APP_PATH/Contents/Info.plist"
cp "$LAUNCHER_DIR/PortClaw" "$APP_PATH/Contents/MacOS/PortClaw"
chmod +x "$APP_PATH/Contents/MacOS/PortClaw"

if [[ -f "$LAUNCHER_DIR/PortClaw.icns" ]]; then
  cp "$LAUNCHER_DIR/PortClaw.icns" "$APP_PATH/Contents/Resources/PortClaw.icns"
fi

/usr/bin/touch "$APP_PATH"
/usr/bin/xattr -dr com.apple.quarantine "$APP_PATH" 2>/dev/null || true

cat <<EOF
PortClaw.app installed:
  $APP_PATH

Runtime copied to:
  $RUNTIME_DIR

Open it with:
  open "$APP_PATH"
EOF
