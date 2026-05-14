#!/usr/bin/env bash
set -euo pipefail

PYTHON="$(command -v python3)"
if [[ -x ".venv/bin/python" ]]; then
  PYTHON=".venv/bin/python"
fi
if [[ -x ".venv/bin/ruff" ]]; then
  RUFF=".venv/bin/ruff"
else
  RUFF="$(command -v ruff || true)"
fi
if [[ -x ".venv/bin/ty" ]]; then
  TY=".venv/bin/ty"
else
  TY="$(command -v ty || true)"
fi

LOG_FILE="quality.txt"
STATUS=0
: > "${LOG_FILE}"
STRICT_TOOLS="${QUALITY_STRICT_TOOLS:-0}"

PYTEST_COV_AVAILABLE="$("$PYTHON" - <<'PY'
import importlib.util
print("1" if importlib.util.find_spec("pytest_cov") else "0")
PY
)"

run_cmd() {
  local label="$1"
  shift
  echo "== ${label} =="
  if ! "$@" ; then
    STATUS=1
  fi
}

run_pytest_smoke() {
  echo "== pytest smoke =="
  set +e
  "$PYTHON" -m pytest -o addopts='' -m smoke --maxfail=1
  local code="$?"
  set -e
  if [[ "$code" = "5" ]]; then
    echo "no smoke tests selected; skipping"
    return 0
  fi
  return "$code"
}

{
  if [[ -n "$RUFF" ]]; then
    run_cmd "ruff check (auto-fix)" "$RUFF" check --fix .
    run_cmd "ruff check" "$RUFF" check .
  else
    echo "skipping ruff (not found in PATH or .venv/bin)"
    if [[ "$STRICT_TOOLS" = "1" ]]; then
      STATUS=1
    fi
  fi

  echo
  if [[ -n "$TY" ]]; then
    run_cmd "ty check" "$TY" check \
      ofti/app/menus/mesh.py \
      ofti/app/menus/physics.py \
      ofti/app/menus/postprocessing.py \
      tests/test_help_manager.py \
      tests/test_menu_utils.py
  else
    echo "skipping ty (not found in PATH or .venv/bin)"
    if [[ "$STRICT_TOOLS" = "1" ]]; then
      STATUS=1
    fi
  fi

  echo
  if ! run_pytest_smoke; then
    STATUS=1
  fi
  echo
  if [[ "$PYTEST_COV_AVAILABLE" = "1" ]]; then
    run_cmd "pytest coverage" "$PYTHON" -m pytest -o addopts='' --cov=ofti --cov-report=term-missing --cov-fail-under=0
  else
    echo "skipping pytest coverage (pytest-cov not installed)"
    if [[ "$STRICT_TOOLS" = "1" ]]; then
      STATUS=1
    fi
  fi
  exit "${STATUS}"
} 2>&1 | tee -a "${LOG_FILE}"

exit "${PIPESTATUS[0]}"
