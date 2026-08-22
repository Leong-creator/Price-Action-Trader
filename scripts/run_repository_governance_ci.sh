#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON_BIN="${PYTHON_BIN:-python}"

"$PYTHON_BIN" -m py_compile \
  scripts/m15_deployment_governance_lib.py \
  scripts/run_m15_deployment_gate.py \
  scripts/m15_opening_trade_readiness_lib.py \
  scripts/run_m15_longbridge_sdk_runtime.py
"$PYTHON_BIN" -m unittest tests.unit.test_m15_deployment_governance

if git grep -I -n -E \
  '(BEGIN (RSA|EC|OPENSSH|PRIVATE) KEY|client[_-]?secret[[:space:]]*[:=]|access[_-]?token[[:space:]]*[:=])' \
  -- ':!tests/**'; then
  echo "repository governance failed: possible secret material" >&2
  exit 3
fi

large_files="$(git ls-files -z | xargs -0 -r du -b | awk '$1 > 52428800 {print $2}')"
if [[ -n "$large_files" ]]; then
  echo "repository governance failed: tracked files exceed 50 MiB" >&2
  printf '%s\n' "$large_files" >&2
  exit 3
fi

git diff --check
echo "repository_governance=passed"
