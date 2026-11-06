#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ "$#" -gt 1 ]]; then
    echo "Usage: $0 [output-parent]" >&2
    exit 2
fi
OUTPUT_PARENT="${1:-$ROOT_DIR/build/quick-actions}"
SOURCE_DIR="$ROOT_DIR/macos/VTSQuickActions"
SIGN_IDENTITY="${QUICK_ACTION_SIGN_IDENTITY:--}"
MODULE_CACHE_PATH="${QUICK_ACTION_MODULE_CACHE:-$ROOT_DIR/build/quick-action-module-cache}"

if [[ -n "${VTS_PROTOTYPE_SDK:-}" ]]; then
    SDK_PATH="$VTS_PROTOTYPE_SDK"
elif [[ -d "/Library/Developer/CommandLineTools/SDKs/MacOSX15.4.sdk" ]]; then
    SDK_PATH="/Library/Developer/CommandLineTools/SDKs/MacOSX15.4.sdk"
else
    SDK_PATH="$(/usr/bin/xcrun --sdk macosx --show-sdk-path)"
fi

case "$(uname -m)" in
    arm64) TARGET="arm64-apple-macosx13.0" ;;
    x86_64) TARGET="x86_64-apple-macosx13.0" ;;
    *) echo "Unsupported macOS architecture: $(uname -m)" >&2; exit 1 ;;
esac

/bin/mkdir -p "$OUTPUT_PARENT" "$MODULE_CACHE_PATH"
BUILD_DIR="$(/usr/bin/mktemp -d "${TMPDIR:-/tmp}/vts-quick-actions.XXXXXX")"
trap '/bin/rm -rf "$BUILD_DIR"' EXIT

# Compile only once. Each copy is sealed in its own bundle with a distinct
# identifier, so macOS can elect all six actions independently.
CLANG_MODULE_CACHE_PATH="$MODULE_CACHE_PATH" /usr/bin/xcrun clang \
    -O2 \
    -fobjc-arc \
    -fapplication-extension \
    -fmodules \
    -isysroot "$SDK_PATH" \
    -target "$TARGET" \
    "$SOURCE_DIR/QuickAction.m" \
    -o "$BUILD_DIR/VTSQuickAction" \
    -framework AppKit \
    -Wl,-e,_NSExtensionMain

SPECS=(
    'timestamp|timestamp|Timestamp Videos'
    'remove-audio|remove-audio|Remove Audio'
    'merge|merge|Merge Clips'
    'transcode|transcode|Transcode Videos'
    'video-minutes|video-minutes|Calculate Runtime'
    'clip-order|clip-order|Order Clips'
)
for SPEC in "${SPECS[@]}"; do
    IFS='|' read -r SLUG ACTION TITLE <<<"$SPEC"
    EXTENSION_PATH="$OUTPUT_PARENT/VTSQuickAction-$SLUG.appex"
    CONTENTS_PATH="$EXTENSION_PATH/Contents"
    /bin/rm -rf "$EXTENSION_PATH"
    /bin/mkdir -p "$CONTENTS_PATH/MacOS"
    /bin/cp "$BUILD_DIR/VTSQuickAction" "$CONTENTS_PATH/MacOS/VTSQuickAction"
    /usr/bin/sed \
        -e "s/__SLUG__/$SLUG/g" \
        -e "s/__ACTION__/$ACTION/g" \
        -e "s/__TITLE__/$TITLE/g" \
        "$SOURCE_DIR/Info.plist" >"$CONTENTS_PATH/Info.plist"
    if [[ "${QUICK_ACTION_RELEASE:-0}" == "1" ]]; then
        /usr/bin/codesign --force --options runtime --timestamp \
            --entitlements "$SOURCE_DIR/entitlements.plist" \
            --sign "$SIGN_IDENTITY" "$EXTENSION_PATH"
    else
        /usr/bin/codesign --force --options runtime \
            --entitlements "$SOURCE_DIR/entitlements.plist" \
            --sign "$SIGN_IDENTITY" "$EXTENSION_PATH"
    fi
    echo "$EXTENSION_PATH"
done
