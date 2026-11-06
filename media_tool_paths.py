"""Portable resolution of the media tools used by VTS.

This module deliberately depends only on the Python standard library.  Both the
existing PyQt application and headless engine entry points can therefore use the
same bundled-tool rules without importing a GUI toolkit.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat
import sys


_TOOL_ENVIRONMENT_VARIABLES = {
    "ffmpeg": "VTS_FFMPEG_PATH",
    "ffprobe": "VTS_FFPROBE_PATH",
    "exiftool": "VTS_EXIFTOOL_PATH",
}


def _executable_name(tool: str) -> str:
    suffix = ".exe" if sys.platform == "win32" else ""
    return f"{tool}{suffix}"


def _resource_roots() -> list[Path]:
    """Every directory that may hold bundled media tools, best first."""

    roots: list[Path] = []
    configured_root = os.environ.get("VTS_ENGINE_RESOURCE_ROOT")
    if configured_root:
        roots.append(Path(configured_root).expanduser().resolve())
    if getattr(sys, "frozen", False):
        if hasattr(sys, "_MEIPASS"):
            roots.append(Path(sys._MEIPASS))
        # The engine embedded in the native app lives at
        # Contents/Resources/engine/vts-engine, beside Contents/Resources/
        # engine-tools. Finding that without being told means the engine stays
        # portable no matter which process starts it.
        sibling = Path(sys.executable).resolve().parent.parent / "engine-tools"
        if sibling.is_dir():
            roots.append(sibling)
    return roots


def _candidate_paths(tool: str) -> list[Path]:
    executable_name = _executable_name(tool)
    candidates: list[Path] = []
    for resource_root in _resource_roots():
        if tool == "exiftool" and sys.platform != "win32":
            candidates.append(resource_root / "exiftool" / executable_name)
        candidates.append(resource_root / executable_name)

    # This covers development checkouts and a future Linux service checkout.
    repository_root = Path(__file__).resolve().parent
    if tool == "exiftool" and sys.platform != "win32":
        candidates.append(repository_root / "exiftool-12.70" / "exiftool")
    candidates.append(repository_root / executable_name)
    return candidates


def resolve_media_tool(tool: str) -> str:
    """Return the best executable path for ``tool``.

    Resolution order is: explicit environment override, packaged resources,
    repository-local resources, then PATH.  If no executable exists, the bare
    command name is returned so callers receive the operating system's normal
    not-found error and existing VTS behavior is preserved.
    """

    if tool not in _TOOL_ENVIRONMENT_VARIABLES:
        raise ValueError(f"Unsupported VTS media tool: {tool}")

    override = os.environ.get(_TOOL_ENVIRONMENT_VARIABLES[tool])
    if override:
        return str(Path(override).expanduser())

    for candidate in _candidate_paths(tool):
        if candidate.is_file():
            if tool == "exiftool" and sys.platform != "win32":
                try:
                    candidate.chmod(candidate.stat().st_mode | stat.S_IEXEC)
                except OSError:
                    pass
            return str(candidate)

    executable_name = _executable_name(tool)
    return shutil.which(executable_name) or executable_name


def get_bundled_exiftool_path() -> str:
    return resolve_media_tool("exiftool")


def get_bundled_ffmpeg_path() -> str:
    return resolve_media_tool("ffmpeg")


def get_bundled_ffprobe_path() -> str:
    return resolve_media_tool("ffprobe")
