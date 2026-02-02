#!/usr/bin/env bash
set -euo pipefail

PYTHON="$(command -v python3)"
if [[ -x ".venv/bin/python" ]]; then
  PYTHON=".venv/bin/python"
fi
RUFF="$(command -v ruff || true)"
if [[ -z "$RUFF" && -x ".venv/bin/ruff" ]]; then
  RUFF=".venv/bin/ruff"
fi
TY="$(command -v ty || true)"
if [[ -z "$TY" && -x ".venv/bin/ty" ]]; then
  TY=".venv/bin/ty"
fi

LOG_FILE="quality.txt"
STATUS=0
: > "${LOG_FILE}"

run_cmd() {
  local label="$1"
  shift
  echo "== ${label} =="
  if ! "$@" ; then
    STATUS=1
  fi
}

{
  if [[ -n "$RUFF" ]]; then
    run_cmd "ruff check (auto-fix)" "$RUFF" check --fix .
    run_cmd "ruff check" "$RUFF" check .
  else
    echo "skipping ruff (not found in PATH or .venv/bin)"
    STATUS=1
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
    STATUS=1
  fi

  echo
  PREV_PYTEST_ADDOPTS="${PYTEST_ADDOPTS-__UNSET__}"
  export PYTEST_ADDOPTS="--no-cov"
  run_cmd "pytest smoke" "$PYTHON" -m pytest -m smoke --maxfail=1
  if [[ "${PREV_PYTEST_ADDOPTS}" = "__UNSET__" ]]; then
    unset PYTEST_ADDOPTS
  else
    export PYTEST_ADDOPTS="$PREV_PYTEST_ADDOPTS"
  fi
  echo
  export PYTEST_ADDOPTS="--cov-fail-under=0"
  run_cmd "pytest coverage" "$PYTHON" -m pytest --cov=ofti --cov-report=term-missing
  unset PYTEST_ADDOPTS
} 2>&1 | tee -a "${LOG_FILE}"

exit "${STATUS}"
