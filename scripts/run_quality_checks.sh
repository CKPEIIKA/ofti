#!/usr/bin/env bash
set -u
set -o pipefail

LOG_FILE="quality.txt"
STATUS=0
: > "${LOG_FILE}"

{
  echo "== ruff check =="
  .venv/bin/ruff check --fix . || STATUS=1
  .venv/bin/ruff check . || STATUS=1
  echo
  echo "== ty check =="
  .venv/bin/ty check . --exclude refs || STATUS=1
  echo
  echo "== pytest =="
  .venv/bin/python -m pytest --cov=ofti --cov-fail-under=40 || STATUS=1
} 2>&1 | tee -a "${LOG_FILE}"

exit "${STATUS}"
