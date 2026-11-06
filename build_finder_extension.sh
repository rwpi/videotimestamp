#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ "$#" -gt 1 ]]; then
    echo "Usage: $0 [output-parent]" >&2
    exit 2
fi
OUTPUT_PARENT="${1:-$ROOT_DIR/build/finder-extension}"
EXTENSION_PATH="$OUTPUT_PARENT/VTSFinderExtension.appex"
CONTENTS_PATH="$EXTENSION_PATH/Contents"
MACOS_PATH="$CONTENTS_PATH/MacOS"
RESOURCES_PATH="$CONTENTS_PATH/Resources"
SOURCE_PATH="$ROOT_DIR/macos/VTSFinderExtension/FinderSync.m"
INFO_PATH="$ROOT_DIR/macos/VTSFinderExtension/Info.plist"
ENTITLEMENTS_PATH="$ROOT_DIR/macos/VTSFinderExtension/entitlements.plist"
SIGN_IDENTITY="${FINDER_EXTENSION_SIGN_IDENTITY:--}"
MODULE_CACHE_PATH="${FINDER_EXTENSION_MODULE_CACHE:-$ROOT_DIR/build/finder-module-cache}"

if [[ -n "${VTS_PROTOTYPE_SDK:-}" ]]; then
    SDK_PATH="$VTS_PROTOTYPE_SDK"
elif [[ -d "/Library/Developer/CommandLineTools/SDKs/MacOSX15.4.sdk" ]]; then
    SDK_PATH="/Library/Developer/CommandLineTools/SDKs/MacOSX15.4.sdk"
else
    SDK_PATH="$(/usr/bin/xcrun --sdk macosx --show-sdk-path)"
fi

ARCH_FLAGS=()
for arch in ${VTS_ARCHITECTURES:-arm64 x86_64}; do
    ARCH_FLAGS+=(-arch "$arch")
done
MINIMUM_FLAG="-mmacosx-version-min=12.0"

/bin/rm -rf "$EXTENSION_PATH"
/bin/mkdir -p "$MACOS_PATH" "$RESOURCES_PATH" "$MODULE_CACHE_PATH"
/bin/cp "$INFO_PATH" "$CONTENTS_PATH/Info.plist"
/bin/cp "$ROOT_DIR/VTS.icns" "$RESOURCES_PATH/VTS.icns"

CLANG_MODULE_CACHE_PATH="$MODULE_CACHE_PATH" /usr/bin/xcrun clang \
    -O2 \
    -fobjc-arc \
    -fapplication-extension \
    -fmodules \
    -isysroot "$SDK_PATH" \
    "${ARCH_FLAGS[@]}" "$MINIMUM_FLAG" \
    "$SOURCE_PATH" \
    -o "$MACOS_PATH/VTSFinderExtension" \
    -framework AppKit \
    -framework FinderSync \
    -Wl,-e,_NSExtensionMain

/usr/bin/codesign \
    --force \
    --options runtime \
    --entitlements "$ENTITLEMENTS_PATH" \
    --sign "$SIGN_IDENTITY" \
    "$EXTENSION_PATH"

echo "$EXTENSION_PATH"
