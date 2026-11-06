#!/usr/bin/env bash
# Wrap a signed, notarized VTS.app in a signed, notarized installer package.
#
#   ./build_swift_prototype.sh --release
#   ./build_pkg.sh [path/to/VTS.app] [output.pkg]
#
# Notarization uses NOTARY_PROFILE, or APPLE_ID, TEAM_ID and APPLE_APP_PASSWORD.
# The installer refuses a Mac below the app's LSMinimumSystemVersion.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_PATH="${1:-$ROOT_DIR/build/swift-prototype/VTS.app}"
OUTPUT="${2:-$ROOT_DIR/build/VTS_macOS_ARM.pkg}"
INSTALLER_SIGN_ID="${INSTALLER_SIGN_ID:-Developer ID Installer: robert webber (F4VUAN3GZ2)}"
TEAM_ID="${TEAM_ID:-F4VUAN3GZ2}"
INFO="$APP_PATH/Contents/Info.plist"

[[ -d "$APP_PATH" ]] || { echo "No app at $APP_PATH" >&2; exit 1; }
/usr/bin/codesign --verify --deep --strict "$APP_PATH"
/usr/bin/xcrun stapler validate "$APP_PATH" >/dev/null
/usr/sbin/spctl --assess --type execute "$APP_PATH"

IDENTIFIER="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$INFO")"
VERSION="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$INFO")"
MINIMUM_MACOS="$(/usr/libexec/PlistBuddy -c 'Print :LSMinimumSystemVersion' "$INFO")"

WORK="$(/usr/bin/mktemp -d)"
trap '/bin/rm -rf "$WORK"' EXIT
/bin/mkdir -p "$WORK/root" "$WORK/packages"
/usr/bin/ditto "$APP_PATH" "$WORK/root/VTS.app"

# Always land in /Applications and replace whatever VTS is there. Left relocatable,
# Installer follows the bundle ID to any other copy on disk and updates that one.
/usr/bin/pkgbuild --analyze --root "$WORK/root" "$WORK/component.plist" >/dev/null
/usr/libexec/PlistBuddy -c "Add :0:BundleIsRelocatable bool false" "$WORK/component.plist"
/usr/libexec/PlistBuddy -c "Set :0:BundleIsVersionChecked false" "$WORK/component.plist"
/usr/libexec/PlistBuddy -c "Set :0:BundleOverwriteAction upgrade" "$WORK/component.plist"

/usr/bin/pkgbuild \
    --root "$WORK/root" \
    --component-plist "$WORK/component.plist" \
    --identifier "$IDENTIFIER" \
    --version "$VERSION" \
    --install-location /Applications \
    "$WORK/packages/VTS.pkg" >/dev/null

/bin/cat >"$WORK/distribution.xml" <<XML
<?xml version="1.0" encoding="utf-8"?>
<installer-gui-script minSpecVersion="2">
    <title>VTS $VERSION</title>
    <options customize="never" require-scripts="false" hostArchitectures="arm64"/>
    <volume-check>
        <allowed-os-versions>
            <os-version min="$MINIMUM_MACOS"/>
        </allowed-os-versions>
    </volume-check>
    <choices-outline>
        <line choice="default"/>
    </choices-outline>
    <choice id="default" title="VTS">
        <pkg-ref id="$IDENTIFIER"/>
    </choice>
    <pkg-ref id="$IDENTIFIER" version="$VERSION" onConclusion="none">VTS.pkg</pkg-ref>
</installer-gui-script>
XML

/bin/mkdir -p "$(/usr/bin/dirname "$OUTPUT")"
/usr/bin/productbuild \
    --distribution "$WORK/distribution.xml" \
    --package-path "$WORK/packages" \
    --sign "$INSTALLER_SIGN_ID" \
    --timestamp \
    "$OUTPUT"

if [[ -n "${NOTARY_PROFILE:-}" ]]; then
    /usr/bin/xcrun notarytool submit "$OUTPUT" --keychain-profile "$NOTARY_PROFILE" --wait
else
    /usr/bin/xcrun notarytool submit "$OUTPUT" \
        --apple-id "$APPLE_ID" --team-id "$TEAM_ID" --password "$APPLE_APP_PASSWORD" --wait
fi
/usr/bin/xcrun stapler staple "$OUTPUT"
/usr/bin/xcrun stapler validate "$OUTPUT"
/usr/sbin/spctl --assess --type install --verbose "$OUTPUT"
/usr/sbin/pkgutil --check-signature "$OUTPUT"
echo "$OUTPUT"
