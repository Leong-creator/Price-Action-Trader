#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SDK_VENV="${ROOT}/local_runtime/tools/longbridge-official-4.5.0"

python3 -m venv "$SDK_VENV"
"$SDK_VENV/bin/python" -m pip install --disable-pip-version-check "longbridge==4.5.0"
"$SDK_VENV/bin/python" -c 'from importlib.metadata import version; assert version("longbridge") == "4.5.0"'

echo "official_sdk_python=${SDK_VENV}/bin/python"
