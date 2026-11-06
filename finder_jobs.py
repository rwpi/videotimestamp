from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from original_archive import is_archived_original
from workflow_schemas import (
    preference_definitions,
    qsettings_values,
    validate_preference_values,
    validate_workflow_options,
)


VIDEO_EXTENSIONS = frozenset(
    {".3gp", ".avi", ".m2ts", ".m4v", ".mkv", ".mov", ".mp4", ".mts", ".ts", ".webm"}
)


@dataclass(frozen=True)
class FinderSelection:
    files: tuple[Path, ...]
    directories: tuple[Path, ...]
    working_folder: Path


def apply_workflow_settings(action: str, raw_options: Any) -> dict[str, Any]:
    """Validate workflow options and persist ONLY what the caller sent.

    Validation fills every unsent option with its schema default. Persisting
    that filled map wrote defaults over the user's stored preferences whenever
    a client launched a job with a partial option map. A default the user never
    chose is not a setting; it is never stored.
    """
    options = validate_workflow_options(action, raw_options)
    sent_keys = set(raw_options) if isinstance(raw_options, dict) else set()
    explicitly_sent = {
        key: value for key, value in options.items() if key in sent_keys
    }
    from PyQt5.QtCore import QSettings

    settings = QSettings("VideoTimestamp", "VTS")
    for key, value in qsettings_values(action, explicitly_sent).items():
        settings.setValue(key, value)
    settings.sync()
    return options


def read_workflow_preferences() -> dict[str, Any]:
    """Read existing VTS settings without constructing a GUI window."""
    from PyQt5.QtCore import QSettings

    settings = QSettings("VideoTimestamp", "VTS")
    values: dict[str, Any] = {}
    for preference_id, definition in preference_definitions().items():
        settings_key = definition["qsettings_key"]
        default = definition["default"]
        kind = definition["kind"]
        try:
            if kind == "boolean":
                value = settings.value(settings_key, default, type=bool)
            elif kind == "number":
                value_type = int if isinstance(default, int) else float
                value = settings.value(settings_key, default, type=value_type)
            elif kind == "choice" and isinstance(default, int):
                value = settings.value(settings_key, default, type=int)
            else:
                value = settings.value(settings_key, default)
            values[preference_id] = validate_preference_values(
                {preference_id: value}
            )[preference_id]
        except (TypeError, ValueError):
            values[preference_id] = default
    return values


def save_workflow_preferences(raw_preferences: Any) -> dict[str, Any]:
    """Persist an allowlisted subset of settings shared by Swift and PyQt."""
    from PyQt5.QtCore import QSettings

    values = validate_preference_values(raw_preferences)
    definitions = preference_definitions()
    settings = QSettings("VideoTimestamp", "VTS")
    for preference_id, value in values.items():
        settings.setValue(definitions[preference_id]["qsettings_key"], value)
    settings.sync()
    return values


def resolve_finder_selection(
    paths: Iterable[Path | str],
    *,
    recursive: bool = False,
) -> FinderSelection:
    """Resolve files and folders into a stable video queue.

    Most legacy tools intentionally operate on one working folder at a time.
    Callers such as AI Detection can opt into ``recursive`` discovery so a
    camera archive root behaves exactly like a manually selected group of its
    nested day folders.
    """
    files: list[Path] = []
    directories: list[Path] = []
    seen_files: set[Path] = set()
    seen_directories: set[Path] = set()

    for raw_path in paths:
        path = Path(raw_path).expanduser()
        if not path.exists():
            continue
        resolved = path.resolve()
        if resolved.is_dir():
            if resolved not in seen_directories:
                directories.append(resolved)
                seen_directories.add(resolved)
            children = resolved.rglob("*") if recursive else resolved.iterdir()
            for child in sorted(children, key=lambda item: str(item).casefold()):
                # Walking a folder must never pick up originals that a previous
                # run displaced: they have already been processed, and queueing
                # them again produces a second result for the same clip. An
                # explicitly selected file below still goes through.
                if is_archived_original(child):
                    continue
                if (
                    child.is_file()
                    and child.suffix.lower() in VIDEO_EXTENSIONS
                    and child.resolve() not in seen_files
                ):
                    files.append(child.resolve())
                    seen_files.add(child.resolve())
        elif (
            resolved.is_file()
            and resolved.suffix.lower() in VIDEO_EXTENSIONS
            and resolved not in seen_files
        ):
            files.append(resolved)
            seen_files.add(resolved)

    folder_candidates = [*directories, *(path.parent for path in files)]
    if not folder_candidates:
        raise ValueError("The Finder selection contains no folder or supported video files.")
    if len(folder_candidates) == 1:
        working_folder = folder_candidates[0]
    else:
        try:
            common_folder = Path(os.path.commonpath([str(path) for path in folder_candidates]))
        except ValueError:
            common_folder = folder_candidates[0]
        working_folder = (
            folder_candidates[0]
            if common_folder == Path(common_folder.anchor)
            else common_folder
        )

    return FinderSelection(
        files=tuple(files),
        directories=tuple(directories),
        working_folder=working_folder,
    )
