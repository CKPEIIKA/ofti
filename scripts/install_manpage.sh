#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
SOURCE="$ROOT_DIR/man/ofti.1"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
DESTINATION="${1:-$DATA_HOME/man/man1}"

install -d "$DESTINATION"
install -m 0644 "$SOURCE" "$DESTINATION/ofti.1"
echo "Installed $DESTINATION/ofti.1"
