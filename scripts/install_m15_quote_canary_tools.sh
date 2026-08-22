#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SDK_VENV="${ROOT}/local_runtime/tools/longbridge-official-4.5.0"
CLI_VERSION="${LONGBRIDGE_CLI_VERSION:-0.28.2}"
CLI_ROOT="${ROOT}/local_runtime/tools/longbridge-terminal-${CLI_VERSION}"

python3 -m venv "$SDK_VENV"
"$SDK_VENV/bin/python" -m pip install --disable-pip-version-check "longbridge==4.5.0"

case "$(uname -m)" in
  x86_64|amd64) arch="amd64" ;;
  aarch64|arm64) arch="arm64" ;;
  *) echo "unsupported architecture: $(uname -m)" >&2; exit 3 ;;
esac
archive="longbridge-terminal-linux-${arch}.tar.gz"
base_url="https://github.com/longbridge/longbridge-terminal/releases/download/v${CLI_VERSION}"
mkdir -p "$CLI_ROOT"
curl -fsSL "${base_url}/${archive}" -o "${CLI_ROOT}/${archive}"
curl -fsSL "${base_url}/${archive}.sha256" -o "${CLI_ROOT}/${archive}.sha256"
(
  cd "$CLI_ROOT"
  expected_sha="$(tr -d '[:space:]' < "${archive}.sha256")"
  actual_sha="$(sha256sum "$archive" | awk '{print $1}')"
  [[ "$actual_sha" == "$expected_sha" ]] || {
    echo "longbridge archive checksum mismatch" >&2
    exit 3
  }
  tar -xzf "$archive"
)
cli_binary="$(find "$CLI_ROOT" -type f -name longbridge -perm -u+x | head -1)"
if [[ -z "$cli_binary" ]]; then
  echo "longbridge binary missing after extraction" >&2
  exit 3
fi
"$cli_binary" --version
"$cli_binary" serve --help >/dev/null

echo "official_sdk_python=${SDK_VENV}/bin/python"
echo "longbridge_serve_binary=${cli_binary}"
