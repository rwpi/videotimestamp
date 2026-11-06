#!/usr/bin/env python3
"""Seal collected framework bundles before their containing app is signed.

PyInstaller's individual Mach-O signatures do not necessarily seal the completed
framework's resources. Run only after collection/copying and load-command edits.
This helper never signs the outer app and does not use codesign --deep to sign.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys
import time

MAGICS = {bytes.fromhex(value) for value in (
    "feedface", "cefaedfe", "feedfacf", "cffaedfe",
    "cafebabe", "bebafeca", "cafebabf", "bfbafeca",
)}
MAX_ENTRIES = 50_000
MAX_FRAMEWORKS = 200
MAX_MACHOS = 2_000


class SigningError(RuntimeError):
    pass


def run_codesign(arguments: list[str], deadline: float) -> None:
    remaining = min(60.0, deadline - time.monotonic())
    if remaining <= 0:
        raise SigningError("Framework signing deadline exceeded")
    try:
        result = subprocess.run(
            ["/usr/bin/codesign", *arguments], capture_output=True, text=True,
            timeout=remaining, cwd="/", check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise SigningError("codesign exceeded its time bound") from error
    if result.returncode:
        detail = (result.stdout + result.stderr)[-2_000:]
        raise SigningError(f"codesign exited {result.returncode}: {detail}")


def discover_frameworks(root: Path) -> dict[Path, list[Path]]:
    """Preflight the entire plan without following directory or file aliases."""
    if root.is_symlink() or not root.is_dir():
        raise SigningError("Collection root must be a real directory, not a symlink")
    root = root.resolve(strict=True)
    frameworks: dict[Path, list[Path]] = {}
    entries = 0
    machos = 0
    def failed_walk(error):
        raise SigningError(f"Cannot enumerate framework collection: {error}")
    for base, directories, filenames in os.walk(root, followlinks=False, onerror=failed_walk):
        directory = Path(base)
        if directory.name.endswith(".framework"):
            frameworks[directory] = []
            if len(frameworks) > MAX_FRAMEWORKS:
                raise SigningError("Too many frameworks")
        owner = next((path for path in (directory, *directory.parents)
                      if path in frameworks), None)
        with os.scandir(directory) as listing:
            actual_entries = list(listing)
        entries += len(actual_entries)
        if entries > MAX_ENTRIES:
            raise SigningError("Collection entry limit exceeded")
        for entry in actual_entries:
            path = Path(entry.path)
            if entry.is_symlink() and owner is not None:
                try:
                    target = path.resolve(strict=True)
                except (OSError, RuntimeError) as error:
                    raise SigningError(f"Broken or cyclic framework alias: {path}") from error
                if not target.is_relative_to(owner):
                    raise SigningError(f"Framework alias escapes its bundle: {path}")
        directories[:] = sorted(name for name in directories
                                 if not (directory / name).is_symlink())
        if owner is None:
            continue
        for name in sorted(filenames):
            path = directory / name
            if path.is_symlink():
                continue
            if not path.is_file():
                raise SigningError(f"Unsupported framework file: {path}")
            with path.open("rb") as stream:
                magic = stream.read(4)
            if magic in MAGICS:
                frameworks[owner].append(path)
                machos += 1
                if machos > MAX_MACHOS:
                    raise SigningError("Framework Mach-O limit exceeded")
    if not frameworks:
        raise SigningError("No physical framework bundles found in collection")
    for framework, binaries in frameworks.items():
        info_path = framework / "Resources/Info.plist"
        if not info_path.is_file() or info_path.stat().st_size > 1_048_576:
            raise SigningError(f"Missing or oversized framework Info.plist: {framework}")
        if not info_path.resolve(strict=True).is_relative_to(framework):
            raise SigningError(f"Framework Info.plist escapes its bundle: {framework}")
        try:
            info = plistlib.loads(info_path.read_bytes())
        except (ValueError, plistlib.InvalidFileException) as error:
            raise SigningError(f"Invalid framework Info.plist: {framework}") from error
        executable = info.get("CFBundleExecutable") if isinstance(info, dict) else None
        if not isinstance(executable, str) or not executable or executable in {".", ".."} \
                or "/" in executable or "\0" in executable or len(executable) > 255:
            raise SigningError(f"Invalid framework executable name: {framework}")
        main = framework / executable
        if not main.is_file() or main.resolve(strict=True) not in binaries:
            raise SigningError(f"Framework main executable is not a physical bundled Mach-O: {framework}")
    return dict(sorted(frameworks.items(), key=lambda item: (-len(item[0].parts), str(item[0]))))


def process_frameworks(root: Path, *, sign: bool, identity: str | None = None,
                       release: bool = True,
                       entitlements: Path | None = None, timeout: float = 600,
                       runner=run_codesign) -> dict:
    if not 0 < timeout <= 1_800:
        raise SigningError("Timeout must be between zero and 1800 seconds")
    started = time.monotonic()
    deadline = started + timeout
    if sign:
        if not isinstance(identity, str) or not identity or "\0" in identity:
            raise SigningError("An explicit signing identity is required")
        if release and not (re.fullmatch(r"[0-9a-fA-F]{40}", identity)
                or identity.startswith("Developer ID Application: ")):
            raise SigningError("A Developer ID Application identity or its 40-digit hash is required")
        if release:
            if entitlements is None or not entitlements.is_file() \
                    or entitlements.stat().st_size > 1_048_576:
                raise SigningError("A bounded entitlements plist is required for release signing")
            entitlements = entitlements.resolve(strict=True)
            if not isinstance(plistlib.loads(entitlements.read_bytes()), dict):
                raise SigningError("Entitlements must be a plist dictionary")
    plan = discover_frameworks(root)
    root = root.resolve(strict=True)
    records = [{"framework": str(path.relative_to(root)),
                "machos": [str(binary.relative_to(root)) for binary in binaries]}
               for path, binaries in plan.items()]
    if sign:
        for framework in plan:
            arguments = ["--force", "--all-architectures", "--sign", identity]
            if release:
                arguments += ["--options", "runtime", "--timestamp", "--entitlements", str(entitlements)]
            runner([*arguments, str(framework)], deadline)
    # Verify every completed bundle AND every physical Mach-O; outer --deep
    # verification alone missed this failure under Contents/Resources/engine.
    for framework, binaries in plan.items():
        for path in (framework, *binaries):
            runner(["--verify", "--strict", "--all-architectures", "--verbose=2", str(path)], deadline)
    return {"schema_version": 1, "mode": "sign" if sign else "verify_only", "release": release,
            "framework_count": len(plan), "macho_count": sum(map(len, plan.values())),
            "signed_frameworks": len(plan) if sign else 0, "all_verified": True,
            "outer_app_signed": False, "notarization_verified": False,
            "elapsed_seconds": round(time.monotonic() - started, 3), "frameworks": records}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("collection", type=Path, help="Fully copied engine collection directory")
    parser.add_argument("--verify-only", action="store_true", help="Read-only verification; never sign")
    parser.add_argument("--identity", default="-", help="Signing identity; defaults to ad hoc for development")
    parser.add_argument("--entitlements", type=Path)
    parser.add_argument("--release", action="store_true", help="Require Developer ID, hardened runtime, timestamp, and entitlements")
    parser.add_argument("--timeout", type=float, default=600)
    args = parser.parse_args(argv)
    try:
        result = process_frameworks(args.collection, sign=not args.verify_only, identity=args.identity,
                                    release=args.release, entitlements=args.entitlements, timeout=args.timeout)
    except (SigningError, OSError, ValueError, plistlib.InvalidFileException) as error:
        print(json.dumps({"all_verified": False, "error": str(error)[:2_000],
                          "partial_signatures_possible": not args.verify_only}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
