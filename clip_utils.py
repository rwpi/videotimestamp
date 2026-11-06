"""Clip naming and duration helpers shared by the processing workflows."""
from __future__ import annotations

import datetime
import re
import subprocess
import sys
from pathlib import Path

import cv2
from PyQt5.QtCore import QSettings

from classification_tags import extract_trailing_tags
from date_settings import preferred_date_order_from_settings
from file_utils import natural_sort_key, parse_clip_datetime
from timestamp import get_bundled_exiftool_path


def safe_rename(src: Path, dst: Path, dry_run: bool, log) -> Path:
    """Rename without overwriting: if target exists, add _1, _2, ..."""
    if src == dst:
        return src

    candidate = dst
    i = 1
    while candidate.exists():
        candidate = dst.with_name(f"{dst.stem}_{i}{dst.suffix}")
        i += 1

    if dry_run:
        log(f"DRY-RUN rename: {src.name} -> {candidate.name}")
        return candidate

    src.rename(candidate)
    log(f"Renamed: {src.name} -> {candidate.name}")
    return candidate


def get_duration_seconds(video_path: Path) -> float | None:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return None
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
        frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0
        if fps > 0 and frames > 0:
            return float(frames / fps)
        return None
    finally:
        cap.release()


def is_vts_processed_stem(stem: str) -> bool:
    stem = re.sub(r"^CLIP\d+_", "", stem, flags=re.IGNORECASE)
    match = re.match(
        r"^((?:\d{2}|[A-Za-z]{3})-(?:\d{2}|[A-Za-z]{3})-\d{4}_\d{2}-\d{2}-\d{2})(?:_.*)?$",
        stem,
        flags=re.IGNORECASE,
    )
    if not match:
        return False
    return parse_clip_datetime(match.group(1), preferred_order=preferred_date_order_from_settings()) is not None


def parse_exif_datetime(value: str) -> datetime.datetime | None:
    value = value.strip()
    if not value:
        return None
    value = value.replace(" DST", "")
    for fmt in ("%Y:%m:%d %H:%M:%S%z", "%Y:%m:%d %H:%M:%S"):
        try:
            return datetime.datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def get_lawmate_exif_datetime(video_path: Path) -> datetime.datetime | None:
    exiftool_path = get_bundled_exiftool_path()
    result = subprocess.run(
        [
            exiftool_path,
            "-s",
            "-s",
            "-s",
            "-DateTimeOriginal",
            "-CreateDate",
            "-MediaCreateDate",
            "-TrackCreateDate",
            "-ModifyDate",
            str(video_path),
        ],
        capture_output=True,
        text=True,
        creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0),
    )
    if not result.stdout:
        return None
    for line in result.stdout.splitlines():
        dt = parse_exif_datetime(line)
        if dt:
            return dt
    return None


def is_lawmate_file(video_path: Path) -> bool:
    # Fast path for common LawMate naming on SD cards.
    if video_path.suffix.lower() == ".mov" and re.match(r"^RECO\d+$", video_path.stem, flags=re.IGNORECASE):
        return True

    # Metadata check is required to avoid tagging regular camcorder MP4 files as LawMate.
    exiftool_path = get_bundled_exiftool_path()
    result = subprocess.run(
        [
            exiftool_path,
            "-s",
            "-s",
            "-s",
            "-Make",
            "-CameraModelName",
            "-Model",
            "-Format",
            "-Information",
            str(video_path),
        ],
        capture_output=True,
        text=True,
        creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0),
    )
    identity = " ".join(
        line.strip() for line in (result.stdout or "").splitlines() if line.strip()
    ).upper()
    if "NVT-IM" in identity or "CARDV-TURNKEY" in identity:
        return True
    return False


def lawmate_rename(
    videos: list[Path],
    date_format: str,
    manually_adjusted_for_dst: bool,
    add_hour: bool,
    subtract_hour: bool,
    dry_run: bool,
    log,
) -> list[Path]:
    renamed_paths = []
    for vp in videos:
        if vp.suffix.lower() not in {".mov", ".mp4"}:
            renamed_paths.append(vp)
            continue
        dt = get_lawmate_exif_datetime(vp)
        if not dt:
            log(f"Lawmate: no EXIF timestamp for {vp.name}")
            renamed_paths.append(vp)
            continue
        if manually_adjusted_for_dst:
            dt = dt - datetime.timedelta(hours=1)
        if add_hour:
            dt = dt + datetime.timedelta(hours=1)
        if subtract_hour:
            dt = dt - datetime.timedelta(hours=1)
        if dt.tzinfo is not None:
            dt = datetime.datetime.fromtimestamp(int(dt.timestamp()))
        date_label = dt.strftime(date_format)
        time_label = dt.strftime("%H-%M-%S")
        tag_suffix = extract_trailing_tags(vp.stem)
        dst = vp.with_name(f"{date_label}_{time_label}{tag_suffix}{vp.suffix}")
        if vp.name == dst.name:
            log(f"Lawmate: OK {vp.name}")
            renamed_paths.append(vp)
            continue
        renamed_paths.append(safe_rename(vp, dst, dry_run=dry_run, log=log))
    return renamed_paths


def cliporder_rename_files(videos: list[Path], dry_run: bool, log, only_vts_outputs: bool = False) -> None:
    pattern = re.compile(
        r"((?:\d{2}|[A-Za-z]{3})-(?:\d{2}|[A-Za-z]{3})-\d{4}_\d{2}-\d{2}-\d{2})",
        re.IGNORECASE,
    )
    items: list[tuple[datetime.datetime, Path]] = []

    for p in videos:
        if not p.is_file():
            continue
        if only_vts_outputs and not is_vts_processed_stem(p.stem):
            continue
        m = pattern.search(p.name)
        if not m:
            continue
        dt = parse_clip_datetime(m.group(1), preferred_order=preferred_date_order_from_settings())
        if not dt:
            continue
        items.append((dt, p))

    items.sort(key=lambda x: x[0])

    for i, (_, p) in enumerate(items, start=1):
        base_no_clip = re.sub(r"^CLIP\d+_", "", p.stem, flags=re.IGNORECASE)
        target = p.with_name(f"CLIP{i}_{base_no_clip}{p.suffix}")
        safe_rename(p, target, dry_run=dry_run, log=log)


def organize_clips(files: list[Path], *, use_clip_numbers: bool, log) -> None:
    """Normalize raw LawMate names, then number the clips in recording order."""
    videos = sorted(
        [path for path in files if path.is_file()],
        key=lambda item: natural_sort_key(item.name),
    )
    settings = QSettings("VideoTimestamp", "VTS")
    date_format = settings.value("date_format", "%m-%d-%Y")
    if not isinstance(date_format, str) or not date_format:
        date_format = "%m-%d-%Y"
    log("Organizing detected unprocessed LawMate files from metadata timestamps...")
    raw = [
        path for path in videos
        if path.suffix.lower() in {".mov", ".mp4"}
        and not is_vts_processed_stem(path.stem)
    ]
    lawmate_candidates = [path for path in raw if is_lawmate_file(path)]
    if len(raw) > len(lawmate_candidates):
        log(f"Skipped {len(raw) - len(lawmate_candidates)} non-LawMate raw MOV/MP4 file(s).")
    try:
        renamed = lawmate_rename(
            videos=lawmate_candidates,
            date_format=date_format,
            manually_adjusted_for_dst=settings.value("manually_adjusted_for_dst", False, type=bool),
            add_hour=settings.value("add_hour", False, type=bool),
            subtract_hour=settings.value("subtract_hour", False, type=bool),
            dry_run=False,
            log=log,
        )
        lookup = dict(zip(lawmate_candidates, renamed))
        videos = [lookup.get(path, path) for path in videos]
    except Exception as exc:
        log(f"Warning: Lawmate rename failed ({exc}).")

    total_found = len(videos)
    videos = [path for path in videos if is_vts_processed_stem(path.stem)]
    if total_found > len(videos):
        log(f"Skipped {total_found - len(videos)} unprocessed original file(s).")
    if not videos:
        log("No eligible processed videos found after excluding unprocessed originals.")
        return
    if use_clip_numbers:
        log("Applying CLIP# ordering...")
        cliporder_rename_files(videos, dry_run=False, log=log, only_vts_outputs=True)
    log("Renaming complete.")
