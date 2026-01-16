#!/usr/bin/env bash
set -u
set -o pipefail

output_file="${1:-qa_output.txt}"
status=0

{
  echo "Quality checks run at $(date)"
  echo "Output file: ${output_file}"
  echo
} > "${output_file}"

run_cmd() {
  local name="$1"
  shift

  echo "==> ${name}" >> "${output_file}"
  echo "Command: $*" >> "${output_file}"
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Result: missing command '$1'" >> "${output_file}"
    echo >> "${output_file}"
    status=1
    return 0
  fi

  "$@" >> "${output_file}" 2>&1
  local rc=$?
  echo "Exit code: ${rc}" >> "${output_file}"
  echo >> "${output_file}"
  if [ "${rc}" -ne 0 ]; then
    status=1
  fi
}

run_cmd "pytest" pytest
run_cmd "ruff" ruff check .
run_cmd "ty" ty check .

if [ "${status}" -ne 0 ]; then
  echo "One or more checks failed." >> "${output_file}"
else
  echo "All checks passed." >> "${output_file}"
fi

exit "${status}"
