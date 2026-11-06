#!/usr/bin/env python3
"""Reject an app whose bundled Mach-O code needs a newer macOS than it claims."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


_MACHO_MAGICS = {
    b"\xfe\xed\xfa\xce",
    b"\xce\xfa\xed\xfe",
    b"\xfe\xed\xfa\xcf",
    b"\xcf\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe",
    b"\xbe\xba\xfe\xca",
    b"\xca\xfe\xba\xbf",
    b"\xbf\xba\xfe\xca",
}
_MINOS_PATTERN = re.compile(r"^\s*minos\s+([0-9]+(?:\.[0-9]+)*)\s*$", re.MULTILINE)


def version_tuple(value: str) -> tuple[int, ...]:
    """Parse the numeric deployment-target format emitted by vtool."""

    text = str(value).strip()
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", text):
        raise ValueError(f"Invalid macOS version: {value!r}")
    parts = [int(part) for part in text.split(".")]
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def _is_macho(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(4) in _MACHO_MAGICS
    except OSError:
        return False


def macho_minimum_versions(path: Path) -> tuple[str, ...]:
    """Return every architecture's declared minimum macOS version."""

    completed = subprocess.run(
        ["/usr/bin/vtool", "-show-build", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"vtool could not inspect {path}: {completed.stderr.strip()}"
        )
    versions = tuple(_MINOS_PATTERN.findall(completed.stdout))
    if not versions:
        raise RuntimeError(f"vtool reported no macOS deployment target for {path}")
    return versions


def incompatible_machos(
    root: Path,
    advertised_minimum: str,
) -> tuple[int, list[tuple[Path, str]]]:
    """Return the Mach-O count and every target newer than the app minimum."""

    allowed = version_tuple(advertised_minimum)
    checked = 0
    violations: list[tuple[Path, str]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or not _is_macho(path):
            continue
        checked += 1
        for minimum in macho_minimum_versions(path):
            if version_tuple(minimum) > allowed:
                violations.append((path, minimum))
    return checked, violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("minimum_macos")
    arguments = parser.parse_args(argv)
    bundle = arguments.bundle.expanduser().resolve()
    if not bundle.is_dir():
        parser.error(f"bundle is not a directory: {bundle}")

    try:
        checked, violations = incompatible_machos(
            bundle,
            arguments.minimum_macos,
        )
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Could not validate macOS runtime compatibility: {error}", file=sys.stderr)
        return 2

    if violations:
        print(
            f"The bundle advertises macOS {arguments.minimum_macos}, but "
            f"{len(violations)} Mach-O target(s) require a newer system:",
            file=sys.stderr,
        )
        for path, minimum in violations[:20]:
            print(f"  {path.relative_to(bundle)}: macOS {minimum}", file=sys.stderr)
        if len(violations) > 20:
            print(f"  ... and {len(violations) - 20} more", file=sys.stderr)
        print(
            "Use a compatible VTS_ENGINE_RUNTIME_PYTHON and media-tool build, "
            "or explicitly raise VTS_PROTOTYPE_MINIMUM_MACOS.",
            file=sys.stderr,
        )
        return 1

    print(
        f"Validated {checked} Mach-O files for macOS {arguments.minimum_macos}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
