#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SDK_REPOSITORY="https://github.com/longbridge/openapi.git"
SDK_COMMIT="266d9230c05208e2b9b6f0e1ebba7eb34fc7e8a2"
PATCH_FILE="$ROOT_DIR/patches/longbridge-4.5.0-disable-subscribe-first-push.patch"
PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"
BUILD_ROOT="${BUILD_ROOT:-$(mktemp -d /tmp/m15-longbridge-sdk.XXXXXX)}"
SOURCE_DIR="$BUILD_ROOT/openapi"
MARKER_FILE="$ROOT_DIR/.venv/.m15-longbridge-sdk-no-first-push.json"

cleanup() {
  if [[ "${KEEP_BUILD_ROOT:-false}" != "true" ]]; then
    rm -rf "$BUILD_ROOT"
  fi
}
trap cleanup EXIT

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Project virtualenv Python is unavailable: $PYTHON_BIN" >&2
  exit 1
fi
if ! command -v cargo >/dev/null 2>&1 && [[ -x "$HOME/.cargo/bin/cargo" ]]; then
  export PATH="$HOME/.cargo/bin:$PATH"
fi
if ! command -v cargo >/dev/null 2>&1; then
  echo "cargo is required to build the pinned Longbridge SDK patch" >&2
  exit 1
fi
if ! "$PYTHON_BIN" -m maturin --version >/dev/null 2>&1; then
  echo "maturin must be installed in the project virtualenv" >&2
  exit 1
fi

git clone --quiet "$SDK_REPOSITORY" "$SOURCE_DIR"
git -C "$SOURCE_DIR" checkout --quiet "$SDK_COMMIT"
git -C "$SOURCE_DIR" apply --check "$PATCH_FILE"
git -C "$SOURCE_DIR" apply "$PATCH_FILE"

"$PYTHON_BIN" -m maturin build \
  --release \
  --manifest-path "$SOURCE_DIR/python/Cargo.toml" \
  --interpreter "$PYTHON_BIN" \
  --out "$BUILD_ROOT/wheels"

WHEEL_FILE="$(find "$BUILD_ROOT/wheels" -maxdepth 1 -type f -name 'longbridge-4.5.0-*.whl' -print -quit)"
if [[ -z "$WHEEL_FILE" ]]; then
  echo "Patched Longbridge wheel was not produced" >&2
  exit 1
fi
"$PYTHON_BIN" -m pip install --force-reinstall --no-deps "$WHEEL_FILE"

PATCH_SHA256="$(sha256sum "$PATCH_FILE" | awk '{print $1}')"
cat >"$MARKER_FILE" <<EOF
{
  "sdk_version": "4.5.0",
  "upstream_commit": "$SDK_COMMIT",
  "patch_sha256": "$PATCH_SHA256",
  "patch": "m15_confirmed_candlestick_trade_aggregation_and_load_shedding",
  "installed_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF

"$PYTHON_BIN" - <<'PY'
from importlib.metadata import version
import longbridge.openapi as sdk

assert version("longbridge") == "4.5.0"
assert sdk.QuoteContext and sdk.TradeContext and sdk.PortfolioContext
print("M15 patched Longbridge SDK installed:", version("longbridge"))
PY
