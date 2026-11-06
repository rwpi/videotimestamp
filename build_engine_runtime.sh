#!/usr/bin/env bash

# Freeze the VTS JSON engine into a relocatable directory the native app can
# carry. Prints the directory on success; everything else goes to the log.
#
#   ./build_engine_runtime.sh
#
# `build_swift_prototype.sh` calls this for release (and for any embedded
# build) and copies the result into Contents/Resources/engine. Set
# PYINSTALLER_CODESIGN_IDENTITY to have PyInstaller sign every collected binary
# with the hardened runtime, which notarization requires.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_DIR="${VTS_ENGINE_RUNTIME_OUTPUT_DIR:-$ROOT_DIR/build/engine-runtime}"
DIST_DIR="$OUTPUT_DIR/dist"
WORK_DIR="$OUTPUT_DIR/work"
LOG_FILE="$OUTPUT_DIR/pyinstaller.log"
ENGINE_DIR="$DIST_DIR/vts-engine"
PYTHON_BIN="${VTS_ENGINE_RUNTIME_PYTHON:-$(command -v python3)}"

if [[ -z "$PYTHON_BIN" ]]; then
    echo "No python3 found to freeze the engine with." >&2
    exit 1
fi
if ! "$PYTHON_BIN" -c 'import PyInstaller' >/dev/null 2>&1; then
    echo "PyInstaller is required to package the engine:" >&2
    echo "  $PYTHON_BIN -m pip install pyinstaller" >&2
    exit 1
fi

/bin/mkdir -p "$OUTPUT_DIR"

# The cached analysis makes a rebuild minutes faster, so only discard it when
# the caller asks for a clean build.
PYINSTALLER_ARGS=(--noconfirm)
if [[ "${VTS_ENGINE_RUNTIME_CLEAN:-0}" == "1" ]]; then
    PYINSTALLER_ARGS+=(--clean)
fi

if ! "$PYTHON_BIN" -m PyInstaller "${PYINSTALLER_ARGS[@]}" \
    --distpath "$DIST_DIR" \
    --workpath "$WORK_DIR" \
    "$ROOT_DIR/VTS_Engine.spec" >"$LOG_FILE" 2>&1; then
    echo "Freezing the VTS engine failed." >&2
    echo "Recent output from $LOG_FILE:" >&2
    /usr/bin/tail -n 40 "$LOG_FILE" >&2
    exit 1
fi

if [[ ! -x "$ENGINE_DIR/vts-engine" ]]; then
    echo "PyInstaller produced no executable at $ENGINE_DIR/vts-engine." >&2
    exit 1
fi

# Answer one request from outside the checkout before anything embeds this. A
# frozen engine that only works next to its source tree is the bug this exists
# to prevent, and it is far cheaper to catch here than after notarization.
if ! (cd / && /bin/echo '{"action": "capabilities"}' |
        "$ENGINE_DIR/vts-engine" --request) >>"$LOG_FILE" 2>&1; then
    echo "The frozen engine could not answer a capabilities request." >&2
    echo "Recent output from $LOG_FILE:" >&2
    /usr/bin/tail -n 40 "$LOG_FILE" >&2
    exit 1
fi

echo "$ENGINE_DIR"
