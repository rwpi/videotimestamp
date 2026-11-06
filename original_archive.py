"""One archive folder for every original a VTS operation displaces.

Timestamping, transcoding and trimming each grew their own version of "put the
new file where the old one was, and keep the old one". They disagreed on the
folder name and on when replacing is safe. This module is the single answer to
both, so an operator who runs three tasks over one folder ends up with one
``originals/`` beside the working files rather than three differently named
piles.

Replacement is refused, never forced, for footage on a camera card, which is
the only copy until it is imported. Callers fall back to writing into a dedicated folder instead.
"""

from __future__ import annotations

import functools
import os
import plistlib
import subprocess
from pathlib import Path
from file_utils import unique_output_path

#: The one folder name. Every operation that displaces an original uses it.
ORIGINALS_FOLDER_NAME = "originals"

#: Folder names that hold displaced originals. Nothing may re-ingest these:
#: an archived original has already been processed, and scanning it again
#: doubles the work and produces a second, conflicting result for one clip.
#: ``untrimmed_clips`` is where trim archived before the names were unified.
ARCHIVE_FOLDER_NAMES = frozenset({ORIGINALS_FOLDER_NAME, "untrimmed_clips"})


def is_archived_original(path: Path | str) -> bool:
    """True when ``path`` sits inside an archive folder."""
    return any(
        part.casefold() in {name.casefold() for name in ARCHIVE_FOLDER_NAMES}
        for part in Path(path).parts
    )


#: Roots that mark a volume as camera media. These mirror the folders
#: ``importtoday.py`` scans and the Finder extension's own card test.
CAMERA_MEDIA_ROOTS = ("DCIM", "PRIVATE", "private")


def originals_folder_for(source: Path) -> Path:
    """The archive folder beside ``source``. Not created."""
    return Path(source).parent / ORIGINALS_FOLDER_NAME


def archive_original(source: Path) -> Path:
    """Move ``source`` into ``originals/`` and return where it landed."""
    source = Path(source)
    originals_dir = originals_folder_for(source)
    originals_dir.mkdir(exist_ok=True)
    archived = unique_output_path(originals_dir, source.name)
    os.replace(source, archived)
    return archived


def archive_original_and_publish(source: Path, staged: Path) -> Path:
    """Move ``source`` into ``originals/`` and put ``staged`` in its place.

    The original is moved away first. Publishing over it instead would destroy
    it if the rename succeeded, which is the one outcome that cannot be undone.
    If the second move fails the original goes straight back.
    """
    source, staged = Path(source), Path(staged)
    archived = archive_original(source)
    try:
        os.replace(staged, source)
    except OSError:
        os.replace(archived, source)
        raise
    return source


def publish_beside_original(source: Path, staged: Path, output_name: str) -> Path:
    """Archive ``source`` and publish ``staged`` beside it under ``output_name``.

    Remove Audio always writes MP4, so a ``.MTS`` source cannot be replaced at
    its own name. Archiving the original and publishing the new file next to it
    still leaves exactly one working copy of that clip in the folder, which is
    what replacing is for. When the names do match this is a plain in-place
    replacement.
    """
    source, staged = Path(source), Path(staged)
    published = source.with_name(output_name)
    if published == source:
        return archive_original_and_publish(source, staged)
    archived = archive_original(source)
    try:
        # The archive step freed the source name, but a previous run may have
        # left the output name taken.
        if published.exists():
            published = unique_output_path(source.parent, output_name)
        os.replace(staged, published)
    except OSError:
        os.replace(archived, source)
        raise
    return published


def _volume_root(path: Path) -> Path | None:
    """``/Volumes/<name>`` for a path on a mounted volume, else ``None``."""
    resolved = Path(path).resolve()
    parts = resolved.parts
    if len(parts) < 3 or parts[1] != "Volumes":
        return None
    return Path(parts[0], parts[1], parts[2])


@functools.lru_cache(maxsize=64)
def _volume_is_removable(volume_root: str) -> bool:
    """Ask diskutil whether a mounted volume is removable or ejectable.

    Cached per volume: a card does not stop being removable while it is
    mounted, and this is consulted once per file in a large selection.
    """
    try:
        completed = subprocess.run(
            ["/usr/sbin/diskutil", "info", "-plist", volume_root],
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if completed.returncode != 0 or not completed.stdout:
        return False
    try:
        info = plistlib.loads(completed.stdout)
    except (plistlib.InvalidFileException, ValueError):
        return False
    # A card in a built-in reader reports as internal, so removability is the
    # test rather than being on an external bus.
    return bool(info.get("Removable") or info.get("Ejectable"))


def is_camera_card_path(path: Path | str) -> bool:
    """True when ``path`` lives on a removable volume holding camera media.

    Deliberately narrower than "removable": an external working drive is a
    legitimate place to edit files, while a card carrying DCIM or PRIVATE is
    the source footage and must only ever be copied from.
    """
    volume_root = _volume_root(Path(path))
    if volume_root is None:
        return False
    if not any(
        (volume_root / media_root).is_dir() for media_root in CAMERA_MEDIA_ROOTS
    ):
        return False
    return _volume_is_removable(str(volume_root))


def replacement_blocked_reason(path: Path | str) -> str | None:
    """Why ``path`` may not be replaced in place, or ``None`` when it may be."""
    if is_camera_card_path(path):
        return (
            "Files on a camera card are never edited in place. Import them "
            "first, then run this task on the imported copies."
        )
    return None


__all__ = [
    "ARCHIVE_FOLDER_NAMES",
    "ORIGINALS_FOLDER_NAME",
    "CAMERA_MEDIA_ROOTS",
    "archive_original",
    "archive_original_and_publish",
    "is_archived_original",
    "is_camera_card_path",
    "originals_folder_for",
    "publish_beside_original",
    "replacement_blocked_reason",
    "unique_output_path",
]
