"""UI-independent queue preparation for native trim clients."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from clip_utils import get_duration_seconds
from finder_jobs import resolve_finder_selection


def native_trim_files(paths: list[str], _options: dict[str, Any]) -> list[Path]:
    """Resolve the native trim queue. A selected folder is walked recursively."""
    selection = resolve_finder_selection(paths, recursive=True)
    return list(dict.fromkeys(path.resolve() for path in selection.files if path.is_file()))


def native_trim_setup(paths: list[str], options: dict[str, Any]) -> list[dict[str, Any]]:
    """Return durations for the native app's manual trim controls."""
    result = []
    for path in native_trim_files(paths, options):
        duration = get_duration_seconds(path) or 0.0
        result.append(
            {
                "path": str(path),
                "duration": duration,
                "suggested_start": 0.0,
                "suggested_end": duration,
            }
        )
    return result
