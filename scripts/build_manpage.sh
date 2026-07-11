#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
SOURCE="$ROOT_DIR/man/ofti.1.scd"
OUTPUT="$ROOT_DIR/man/ofti.1"

command -v scdoc >/dev/null 2>&1 || {
  echo "ERROR: scdoc is required to regenerate $OUTPUT" >&2
  exit 127
}

temporary="$(mktemp "$OUTPUT.XXXXXX")"
trap 'rm -f "$temporary"' EXIT
scdoc < "$SOURCE" > "$temporary"
chmod 0644 "$temporary"
mv "$temporary" "$OUTPUT"
trap - EXIT
