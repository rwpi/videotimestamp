# Building VTS

VTS is a native SwiftUI app. The interface lives in
`macos/VTSNativePrototype/VTSNativePrototype.swift`, and every workflow runs in a
Python engine (`vts_engine.py`, `vts_job_runner.py`) over a newline-JSON bridge.
Some module names end in `_gui` for historical reasons; they hold processing code.

## Requirements

- macOS on Apple silicon with Xcode
- `ffmpeg`, `ffprobe` and Python 3 on your `PATH`
- `python3 -m pip install -r requirements.txt`

## Development build

```sh
VTS_PROTOTYPE_OPTIMIZATION=-Onone ./build_swift_prototype.sh
open build/swift-prototype/VTS.app
```

A development build uses this checkout and your Python. Build one at a time: every
build writes to `build/swift-prototype/` unless `VTS_PROTOTYPE_OUTPUT_DIR` is set.

## Tests

```sh
python3 -m pytest -q
VTS_RELEASE_PACKAGING_TESTS=1 python3 -m pytest tests/test_swift_release_packaging.py
```

The second command builds a release bundle and proves it is self-contained.

## Release

A release freezes the engine into the app, signs it with a Developer ID certificate,
notarizes it and staples the ticket. `build_pkg.sh` wraps that app in a signed,
notarized installer.

```sh
export NOTARY_PROFILE=your-notarytool-profile
export APP_SIGN_ID="Developer ID Application: Your Name (TEAMID)"
export INSTALLER_SIGN_ID="Developer ID Installer: Your Name (TEAMID)"
export TEAM_ID=TEAMID

./build_swift_prototype.sh --release
./build_pkg.sh
```

The Swift executable can come from another Mac. Compile it there with
`VTS_SWIFT_BINARIES_OUTPUT_DIR=/path ./build_swift_prototype.sh`, copy that folder
over, and pass `VTS_PREBUILT_SWIFT_DIR=/path` to the release build. The build refuses
binaries compiled from different sources.
