#!/usr/bin/env bash

set -euo pipefail

# A macOS update can leave xcode-select pointing at Command Line Tools whose
# SDK is newer than its SwiftUI macro plug-ins. Prefer the complete Xcode
# toolchain when it is installed, unless the caller chose a developer directory.
if [[ -z "${DEVELOPER_DIR:-}" && \
      "$(/usr/bin/xcode-select -p)" == "/Library/Developer/CommandLineTools" && \
      -d "/Applications/Xcode.app/Contents/Developer" ]]; then
    export DEVELOPER_DIR="/Applications/Xcode.app/Contents/Developer"
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="$ROOT_DIR/macos/VTSNativePrototype"
OUTPUT_DIR="${VTS_PROTOTYPE_OUTPUT_DIR:-$ROOT_DIR/build/swift-prototype}"
APP_PATH="$OUTPUT_DIR/VTS.app"
CONTENTS_PATH="$APP_PATH/Contents"
PLUGINS_PATH="$CONTENTS_PATH/PlugIns"
ENGINE_TOOLS_PATH="$CONTENTS_PATH/Resources/engine-tools"
ENGINE_PATH="$CONTENTS_PATH/Resources/engine"
MEDIA_PREP_LOG="$OUTPUT_DIR/media-prep.log"
PYTHON_PATH="${VTS_PROTOTYPE_PYTHON:-$(command -v python3)}"

run_media_command() {
    if ! "$@" >>"$MEDIA_PREP_LOG" 2>&1; then
        echo "Media dependency preparation failed: $1" >&2
        echo "Recent output from $MEDIA_PREP_LOG:" >&2
        /usr/bin/tail -n 40 "$MEDIA_PREP_LOG" >&2
        exit 1
    fi
}

# Release mode signs with the Developer ID certificate, notarizes and staples.
# The default stays ad-hoc ("-") so the everyday development loop needs no
# certificate and no network.
RELEASE=0
for arg in "$@"; do
    case "$arg" in
        --release) RELEASE=1 ;;
        *) echo "Unknown option: $arg" >&2; echo "Usage: $0 [--release]" >&2; exit 1 ;;
    esac
done
if [[ "${VTS_PROTOTYPE_RELEASE:-0}" == "1" ]]; then
    RELEASE=1
fi

# Release builds carry their own interpreter and the current engine modules.
EMBED_ENGINE="${VTS_PROTOTYPE_EMBED_ENGINE:-$RELEASE}"
# The floor follows the bundled libraries, not the product. Homebrew builds
# against the running system, so on macOS 27 the vendored ffmpeg stack
# (libcrypto, libssl, liblzma) carries
# minos 27.0; advertising anything lower makes validate_macos_runtime.py
# reject the bundle rather than ship an app that cannot load its own
# dependencies. Lowering this again means rebuilding those libraries against
# the older SDK first.
MINIMUM_MACOS="${VTS_PROTOTYPE_MINIMUM_MACOS:-27.0}"

APP_SIGN_ID="${APP_SIGN_ID:-Developer ID Application: robert webber (F4VUAN3GZ2)}"
TEAM_ID="${TEAM_ID:-F4VUAN3GZ2}"
APPLE_ID="${APPLE_ID:-}"
APPLE_APP_PASSWORD="${APPLE_APP_PASSWORD:-}"
ENTITLEMENTS_FILE="${VTS_PROTOTYPE_ENTITLEMENTS:-$ROOT_DIR/entitlements.plist}"

if [[ "$RELEASE" -eq 1 ]]; then
    SIGN_IDENTITY="${VTS_PROTOTYPE_SIGN_IDENTITY:-$APP_SIGN_ID}"
    if ! security find-identity -v -p codesigning | grep -Fq "$SIGN_IDENTITY"; then
        echo "Missing signing identity: $SIGN_IDENTITY" >&2
        echo "Install and unlock the Developer ID Application certificate, or override APP_SIGN_ID." >&2
        exit 1
    fi
    if [[ -z "${NOTARY_PROFILE:-}" && -z "$APPLE_APP_PASSWORD" ]]; then
        echo "Release notarization needs NOTARY_PROFILE or APPLE_APP_PASSWORD." >&2
        exit 1
    fi
else
    SIGN_IDENTITY="${VTS_PROTOTYPE_SIGN_IDENTITY:--}"
fi
MODULE_CACHE_PATH="${VTS_PROTOTYPE_MODULE_CACHE:-$OUTPUT_DIR/module-cache}"
OPTIMIZATION_LEVEL="${VTS_PROTOTYPE_OPTIMIZATION:--O}"

case "$OPTIMIZATION_LEVEL" in
    -Onone|-O|-Osize) ;;
    *) echo "Unsupported Swift optimization level: $OPTIMIZATION_LEVEL" >&2; exit 1 ;;
esac

if [[ -n "${VTS_PROTOTYPE_SDK:-}" ]]; then
    SDK_PATH="$VTS_PROTOTYPE_SDK"
elif [[ -d "/Library/Developer/CommandLineTools/SDKs/MacOSX15.4.sdk" ]]; then
    # The macOS 26.2 Command Line Tools SDK can temporarily be newer than the
    # installed Swift frontend after an OS update. The 15.4 SDK still carries
    # every API this app deploys against.
    SDK_PATH="/Library/Developer/CommandLineTools/SDKs/MacOSX15.4.sdk"
else
    SDK_PATH="$(/usr/bin/xcrun --sdk macosx --show-sdk-path)"
fi

# The menu bar agent suppresses its window at launch, which is a macOS 15 API.
# This is the floor the compiled binary needs; the bundle advertises its own,
# higher minimum for the media stack it carries.
SWIFT_DEPLOYMENT_TARGET="${VTS_PROTOTYPE_SWIFT_TARGET:-15.0}"
case "$(uname -m)" in
    arm64) TARGET="arm64-apple-macosx$SWIFT_DEPLOYMENT_TARGET" ;;
    x86_64) TARGET="x86_64-apple-macosx$SWIFT_DEPLOYMENT_TARGET" ;;
    *) echo "Unsupported macOS architecture: $(uname -m)" >&2; exit 1 ;;
esac

compile_native_app() {
    CLANG_MODULE_CACHE_PATH="$MODULE_CACHE_PATH" /usr/bin/xcrun swiftc \
        "$OPTIMIZATION_LEVEL" \
        -parse-as-library \
        -module-name VTS \
        -sdk "$SDK_PATH" \
        -target "$TARGET" \
        "$SOURCE_DIR/VTSNativePrototype.swift" \
        -o "$1" \
        -framework AppKit \
        -framework AVFoundation \
        -framework AVKit \
        -framework SwiftUI
}

swift_source_digests() {
    (cd "$ROOT_DIR" && /usr/bin/shasum -a 256 \
        macos/VTSNativePrototype/VTSNativePrototype.swift)
}

# The Swift executable can be compiled on another Mac and carried in, so the Mac
# holding the signing key does not have to compile it.
if [[ -n "${VTS_SWIFT_BINARIES_OUTPUT_DIR:-}" ]]; then
    /bin/mkdir -p "$VTS_SWIFT_BINARIES_OUTPUT_DIR" "$MODULE_CACHE_PATH"
    compile_native_app "$VTS_SWIFT_BINARIES_OUTPUT_DIR/VTS"
    swift_source_digests >"$VTS_SWIFT_BINARIES_OUTPUT_DIR/swift-sources.sha256"
    echo "$VTS_SWIFT_BINARIES_OUTPUT_DIR"
    exit 0
fi

# Binaries from any other source would ship old behaviour under this commit's
# stamp, so they are refused before anything is touched.
PREBUILT_SWIFT_DIR="${VTS_PREBUILT_SWIFT_DIR:-}"
if [[ -n "$PREBUILT_SWIFT_DIR" ]] && \
    ! swift_source_digests | /usr/bin/cmp -s - "$PREBUILT_SWIFT_DIR/swift-sources.sha256"; then
    echo "The Swift binaries in $PREBUILT_SWIFT_DIR were compiled from different sources." >&2
    exit 1
fi

/bin/rm -rf "$APP_PATH"
/bin/mkdir -p "$CONTENTS_PATH/MacOS" "$CONTENTS_PATH/Resources" "$PLUGINS_PATH" "$ENGINE_TOOLS_PATH" "$MODULE_CACHE_PATH"
: >"$MEDIA_PREP_LOG"
/bin/cp "$SOURCE_DIR/Info.plist" "$CONTENTS_PATH/Info.plist"
if [[ "$EMBED_ENGINE" -eq 0 ]]; then
    /usr/libexec/PlistBuddy -c "Add :VTSDevelopmentRoot string $ROOT_DIR" "$CONTENTS_PATH/Info.plist"
    /usr/libexec/PlistBuddy -c "Add :VTSDevelopmentPython string $PYTHON_PATH" "$CONTENTS_PATH/Info.plist"
else
    /usr/libexec/PlistBuddy -c "Set :LSMinimumSystemVersion $MINIMUM_MACOS" "$CONTENTS_PATH/Info.plist"
fi
# Stamp the exact inputs, including authorized worktree edits, without claiming
# an uncommitted build is identical to HEAD.
"$PYTHON_PATH" - "$ROOT_DIR" "$CONTENTS_PATH/Info.plist" <<'PY_STAMP'
from pathlib import Path
import datetime, hashlib, plistlib, subprocess, sys
root, info_path = map(Path, sys.argv[1:])
def git(*args):
    return subprocess.check_output(['git', '-C', str(root), *args])
commit = git('rev-parse', 'HEAD').decode().strip()
patch = git('diff', '--binary', 'HEAD')
extra = git('ls-files', '--others', '--exclude-standard', '-z').split(b'\0')
digest = hashlib.sha256(commit.encode() + patch)
for raw in sorted(name for name in extra if name):
    path = root / raw.decode()
    if path.is_file():
        digest.update(raw + b'\0' + path.read_bytes())
info = plistlib.loads(info_path.read_bytes())
info['VTSBuildCommit'] = commit
info['VTSBuildSourceState'] = 'worktree' if patch or any(extra) else 'committed'
info['VTSBuildSourceSHA256'] = digest.hexdigest()
info['VTSBuildTimestamp'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
info_path.write_bytes(plistlib.dumps(info))
PY_STAMP
/bin/cp "$ROOT_DIR/VTS.icns" "$CONTENTS_PATH/Resources/VTS.icns"

# The PyQt application that used to donate a prebuilt media stack is gone, so
# the ffmpeg on PATH is the only automatic source; it is vendored below.
# VTS_PROTOTYPE_MEDIA_APP still aims the build at a bundle that carries one.
MEDIA_APP="${VTS_PROTOTYPE_MEDIA_APP:-}"

if [[ -n "$MEDIA_APP" ]]; then
    MEDIA_FRAMEWORKS="$MEDIA_APP/Contents/Frameworks"
    /bin/cp -Lp "$MEDIA_FRAMEWORKS/ffmpeg" "$ENGINE_TOOLS_PATH/ffmpeg"
    /bin/cp -Lp "$MEDIA_FRAMEWORKS/ffprobe" "$ENGINE_TOOLS_PATH/ffprobe"
    while true; do
        COPIED_DEPENDENCY=0
        for MEDIA_BINARY in \
            "$ENGINE_TOOLS_PATH/ffmpeg" \
            "$ENGINE_TOOLS_PATH/ffprobe" \
            "$ENGINE_TOOLS_PATH"/*.dylib; do
            [[ -f "$MEDIA_BINARY" ]] || continue
            while IFS= read -r DEPENDENCY_NAME; do
                [[ -n "$DEPENDENCY_NAME" ]] || continue
                if [[ ! -f "$ENGINE_TOOLS_PATH/$DEPENDENCY_NAME" ]]; then
                    /bin/cp -Lp \
                        "$MEDIA_FRAMEWORKS/$DEPENDENCY_NAME" \
                        "$ENGINE_TOOLS_PATH/$DEPENDENCY_NAME"
                    COPIED_DEPENDENCY=1
                fi
            done < <(
                /usr/bin/otool -L "$MEDIA_BINARY" |
                    /usr/bin/awk '$1 ~ /^@rpath\// { sub(/^@rpath\//, "", $1); print $1 }'
            )
        done
        [[ "$COPIED_DEPENDENCY" -eq 1 ]] || break
    done
else
    # No prebuilt media app. Vendor the ffmpeg on PATH the same way the
    # PyInstaller release does: copy the binaries, pull in every non-system
    # dependency, then rewrite the absolute Homebrew paths to @rpath. Homebrew
    # hardcodes /opt/homebrew/Cellar paths, so copying the binary alone yields
    # an app with no libraries that cannot run anywhere else.
    SOURCE_FFMPEG="$(command -v ffmpeg)"
    /bin/cp -p "$SOURCE_FFMPEG" "$ENGINE_TOOLS_PATH/ffmpeg"
    /bin/cp -p "$(command -v ffprobe)" "$ENGINE_TOOLS_PATH/ffprobe"
    /bin/chmod u+w "$ENGINE_TOOLS_PATH/ffmpeg" "$ENGINE_TOOLS_PATH/ffprobe"

    # Where to look for dependencies named through @rpath. The package's own
    # lib directory comes first, then the package manager's link farm, which is
    # where libraries from sibling formulae resolve.
    SOURCE_FFMPEG_PREFIX="$(cd "$(/usr/bin/dirname "$(/usr/bin/readlink -f "$SOURCE_FFMPEG")")/.." && pwd)"
    MEDIA_LIBRARY_DIRS=("$SOURCE_FFMPEG_PREFIX/lib")
    for LIBRARY_DIR in /opt/homebrew/lib /usr/local/lib; do
        [[ -d "$LIBRARY_DIR" ]] && MEDIA_LIBRARY_DIRS+=("$LIBRARY_DIR")
    done

    while true; do
        COPIED_DEPENDENCY=0
        for MEDIA_BINARY in \
            "$ENGINE_TOOLS_PATH/ffmpeg" \
            "$ENGINE_TOOLS_PATH/ffprobe" \
            "$ENGINE_TOOLS_PATH"/*.dylib; do
            [[ -f "$MEDIA_BINARY" ]] || continue
            while IFS= read -r DEPENDENCY_PATH; do
                [[ -n "$DEPENDENCY_PATH" ]] || continue
                DEPENDENCY_NAME="$(/usr/bin/basename "$DEPENDENCY_PATH")"
                if [[ ! -f "$ENGINE_TOOLS_PATH/$DEPENDENCY_NAME" ]]; then
                    /bin/cp -Lp "$DEPENDENCY_PATH" "$ENGINE_TOOLS_PATH/$DEPENDENCY_NAME"
                    /bin/chmod u+w "$ENGINE_TOOLS_PATH/$DEPENDENCY_NAME"
                    COPIED_DEPENDENCY=1
                fi
            done < <(
                /usr/bin/otool -L "$MEDIA_BINARY" |
                    /usr/bin/awk 'NR>1 && $1 ~ /^\// && $1 !~ /^\/usr\/lib\// && $1 !~ /^\/System\// { print $1 }'
            )

            # Homebrew libraries also reference each other through @rpath, so
            # following only absolute paths silently drops part of the tree.
            # libwebp reaches libsharpyuv this way, and missing it stops ffmpeg
            # from launching at all. Resolve those by name against the library
            # directories that belong to the ffmpeg we are vendoring.
            while IFS= read -r DEPENDENCY_NAME; do
                [[ -n "$DEPENDENCY_NAME" ]] || continue
                [[ -f "$ENGINE_TOOLS_PATH/$DEPENDENCY_NAME" ]] && continue
                for LIBRARY_DIR in "${MEDIA_LIBRARY_DIRS[@]}"; do
                    if [[ -f "$LIBRARY_DIR/$DEPENDENCY_NAME" ]]; then
                        /bin/cp -Lp "$LIBRARY_DIR/$DEPENDENCY_NAME" \
                            "$ENGINE_TOOLS_PATH/$DEPENDENCY_NAME"
                        /bin/chmod u+w "$ENGINE_TOOLS_PATH/$DEPENDENCY_NAME"
                        COPIED_DEPENDENCY=1
                        break
                    fi
                done
            done < <(
                /usr/bin/otool -L "$MEDIA_BINARY" |
                    /usr/bin/awk 'NR>1 && $1 ~ /^@(rpath|loader_path|executable_path)\// {
                        sub(/^@[a-z_]+\//, "", $1); print $1
                    }'
            )
        done
        [[ "$COPIED_DEPENDENCY" -eq 1 ]] || break
    done

    # install_name_tool invalidates any existing signature, so every rewrite
    # has to finish before the signing pass below.
    for MEDIA_BINARY in \
        "$ENGINE_TOOLS_PATH/ffmpeg" \
        "$ENGINE_TOOLS_PATH/ffprobe" \
        "$ENGINE_TOOLS_PATH"/*.dylib; do
        [[ -f "$MEDIA_BINARY" ]] || continue
        MEDIA_BINARY_NAME="$(/usr/bin/basename "$MEDIA_BINARY")"
        if [[ "$MEDIA_BINARY" == *.dylib ]]; then
            run_media_command /usr/bin/install_name_tool \
                -id "@rpath/$MEDIA_BINARY_NAME" "$MEDIA_BINARY"
        fi
        while IFS= read -r DEPENDENCY_PATH; do
            [[ -n "$DEPENDENCY_PATH" ]] || continue
            run_media_command /usr/bin/install_name_tool \
                -change "$DEPENDENCY_PATH" \
                "@rpath/$(/usr/bin/basename "$DEPENDENCY_PATH")" \
                "$MEDIA_BINARY"
        done < <(
            /usr/bin/otool -L "$MEDIA_BINARY" |
                /usr/bin/awk 'NR>1 && $1 ~ /^\// && $1 !~ /^\/usr\/lib\// && $1 !~ /^\/System\// { print $1 }'
        )
        # Already present on a rebuilt binary; a duplicate rpath is not an error.
        /usr/bin/install_name_tool -add_rpath "@loader_path" "$MEDIA_BINARY" \
            >>"$MEDIA_PREP_LOG" 2>&1 || true
    done
fi

# Nested Mach-O code in Resources is hashed by the outer signature but never
# signed by it, so notarization rejects anything left ad-hoc here. Sign the
# media tools explicitly, after every install_name_tool rewrite.
for MEDIA_BINARY in \
    "$ENGINE_TOOLS_PATH/ffmpeg" \
    "$ENGINE_TOOLS_PATH/ffprobe" \
    "$ENGINE_TOOLS_PATH"/*.dylib; do
    [[ -f "$MEDIA_BINARY" ]] || continue
    if [[ "$RELEASE" -eq 1 ]]; then
        run_media_command /usr/bin/codesign --force --options runtime --timestamp \
            --sign "$SIGN_IDENTITY" "$MEDIA_BINARY"
    else
        run_media_command /usr/bin/codesign --force \
            --sign "$SIGN_IDENTITY" "$MEDIA_BINARY"
    fi
done

if [[ -n "$MEDIA_APP" && -d "$MEDIA_APP/Contents/Resources/exiftool" ]]; then
    EXIFTOOL_SOURCE="$MEDIA_APP/Contents/Resources/exiftool"
else
    EXIFTOOL_SOURCE="$ROOT_DIR/exiftool-12.70"
fi
/bin/mkdir -p "$ENGINE_TOOLS_PATH/exiftool"
/bin/cp -p "$EXIFTOOL_SOURCE/exiftool" "$ENGINE_TOOLS_PATH/exiftool/exiftool"
/usr/bin/ditto "$EXIFTOOL_SOURCE/lib" "$ENGINE_TOOLS_PATH/exiftool/lib"

if [[ "$EMBED_ENGINE" -eq 1 ]]; then
    echo "Freezing the VTS engine..."
    if [[ "$RELEASE" -eq 1 ]]; then
        ENGINE_SOURCE="$(VTS_ENGINE_RUNTIME_PYTHON="$PYTHON_PATH" \
            PYINSTALLER_CODESIGN_IDENTITY="$SIGN_IDENTITY" \
            "$ROOT_DIR/build_engine_runtime.sh")"
    else
        ENGINE_SOURCE="$(VTS_ENGINE_RUNTIME_PYTHON="$PYTHON_PATH" \
            "$ROOT_DIR/build_engine_runtime.sh")"
    fi
    /usr/bin/ditto "$ENGINE_SOURCE" "$ENGINE_PATH"
    FRAMEWORK_SIGN_ARGS=(--identity "$SIGN_IDENTITY")
    if [[ "$RELEASE" -eq 1 ]]; then
        FRAMEWORK_SIGN_ARGS+=(--release --entitlements "$ENTITLEMENTS_FILE")
    fi
    "$PYTHON_PATH" "$ROOT_DIR/sign_embedded_frameworks.py" "$ENGINE_PATH" \
        "${FRAMEWORK_SIGN_ARGS[@]}" >"$OUTPUT_DIR/framework-signing.json"
    "$PYTHON_PATH" "$ROOT_DIR/validate_macos_runtime.py" "$APP_PATH" "$MINIMUM_MACOS"
fi

FINDER_EXTENSION_SIGN_IDENTITY="$SIGN_IDENTITY" \
    "$ROOT_DIR/build_finder_extension.sh" "$PLUGINS_PATH"
QUICK_ACTION_SIGN_IDENTITY="$SIGN_IDENTITY" \
QUICK_ACTION_RELEASE="$RELEASE" \
QUICK_ACTION_MODULE_CACHE="$MODULE_CACHE_PATH/quick-actions" \
    "$ROOT_DIR/build_quick_actions.sh" "$PLUGINS_PATH"

if [[ -n "$PREBUILT_SWIFT_DIR" ]]; then
    /bin/cp "$PREBUILT_SWIFT_DIR/VTS" "$CONTENTS_PATH/MacOS/VTS"
else
    compile_native_app "$CONTENTS_PATH/MacOS/VTS"
fi

if [[ "$RELEASE" -eq 1 ]]; then
    # Seal the app around its already-signed extension, with the hardened
    # runtime that notarization requires.
    /usr/bin/codesign \
        --force \
        --options runtime \
        --timestamp \
        --entitlements "$ENTITLEMENTS_FILE" \
        --sign "$SIGN_IDENTITY" \
        "$APP_PATH"

    echo "Verifying signature..."
    /usr/bin/codesign --verify --deep --strict --verbose=2 "$APP_PATH"

    # notarytool only accepts an archive, while the ticket staples to the .app.
    NOTARIZE_ZIP="$OUTPUT_DIR/VTS-notarize.zip"
    /bin/rm -f "$NOTARIZE_ZIP"
    echo "Creating notarization archive..."
    /usr/bin/ditto -c -k --keepParent "$APP_PATH" "$NOTARIZE_ZIP"

    echo "Submitting for notarization..."
    # notarytool exits 0 whenever a submission finishes processing, including
    # when Apple rejects it, so the verdict has to be read from the output.
    # Without this an Invalid result reaches stapler, which then reports a
    # "Record not found" CloudKit error that looks like a propagation delay.
    NOTARY_OUTPUT="$OUTPUT_DIR/notarytool-submit.log"
    if [[ -n "${NOTARY_PROFILE:-}" ]]; then
        /usr/bin/xcrun notarytool submit "$NOTARIZE_ZIP" \
            --keychain-profile "$NOTARY_PROFILE" --wait 2>&1 | /usr/bin/tee "$NOTARY_OUTPUT"
    else
        /usr/bin/xcrun notarytool submit "$NOTARIZE_ZIP" \
            --apple-id "$APPLE_ID" \
            --password "$APPLE_APP_PASSWORD" \
            --team-id "$TEAM_ID" \
            --wait 2>&1 | /usr/bin/tee "$NOTARY_OUTPUT"
    fi

    NOTARY_STATUS="$(/usr/bin/awk '/^ *status:/ { $1=""; sub(/^ /, ""); value=$0 } END { print value }' "$NOTARY_OUTPUT")"
    if [[ "$NOTARY_STATUS" != "Accepted" ]]; then
        NOTARY_ID="$(/usr/bin/awk '/^ *id:/ { print $2; exit }' "$NOTARY_OUTPUT")"
        echo "Notarization did not succeed (status: ${NOTARY_STATUS:-unknown})." >&2
        echo "Fetch the reason with:" >&2
        if [[ -n "${NOTARY_PROFILE:-}" ]]; then
            echo "  xcrun notarytool log $NOTARY_ID --keychain-profile $NOTARY_PROFILE" >&2
        else
            echo "  xcrun notarytool log $NOTARY_ID --apple-id $APPLE_ID --team-id $TEAM_ID --password <app-specific-password>" >&2
        fi
        exit 1
    fi

    echo "Stapling notarization ticket..."
    /usr/bin/xcrun stapler staple "$APP_PATH"

    echo "Verifying stapled app..."
    /usr/bin/xcrun stapler validate "$APP_PATH"
    /usr/sbin/spctl --assess --type execute --verbose "$APP_PATH"

    /bin/rm -f "$NOTARIZE_ZIP"
else
    /usr/bin/codesign \
        --force \
        --sign "$SIGN_IDENTITY" \
        "$APP_PATH"
fi

echo "$APP_PATH"
