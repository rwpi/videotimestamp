# -*- mode: python ; coding: utf-8 -*-
"""Standalone VTS engine runtime for the native SwiftUI app.

``build_engine_runtime.sh`` freezes this and ``build_swift_prototype.sh`` copies
the result into ``VTS.app/Contents/Resources/engine``, so a release carries
its own interpreter and its own copy of the VTS modules.

Everything here resolves from the spec's own directory, so a build input can
never name a path outside this repository.
"""

import os
from pathlib import Path


ROOT = Path(SPECPATH).resolve()

# The app starts workflows through `vts-engine --job-runner`, which nothing
# imports at module scope, so name it here to pull it into the frozen graph.
HIDDEN_IMPORTS = ["vts_job_runner"]

# Keep the attribution beside the frozen code it covers.
NOTICE_DATAS = [(str(ROOT / "THIRD_PARTY_NOTICES.md"), ".")]

# Toolkits VTS does not use, and which drag in a second GUI stack.
UNUSED_TOOLKITS = ["PySide2", "PySide6", "shiboken2", "shiboken6", "tkinter"]

CODESIGN_IDENTITY = os.environ.get("PYINSTALLER_CODESIGN_IDENTITY") or None
# Entitlements only mean anything with a real identity, and passing them to an
# ad-hoc development signature just makes every nested binary noisier.
ENTITLEMENTS_FILE = str(ROOT / "entitlements.plist") if CODESIGN_IDENTITY else None


a = Analysis(
    [str(ROOT / "vts_engine.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=NOTICE_DATAS,
    hiddenimports=HIDDEN_IMPORTS,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=UNUSED_TOOLKITS,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="vts-engine",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=os.environ.get("VTS_ENGINE_TARGET_ARCH") or None,
    codesign_identity=CODESIGN_IDENTITY,
    entitlements_file=ENTITLEMENTS_FILE,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="vts-engine",
)
