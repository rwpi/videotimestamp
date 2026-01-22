#!/usr/bin/env python3
import argparse
import re
import sys
from pathlib import Path
import datetime

import cv2


# ----------------------------
# Helpers
# ----------------------------
def pick_device():
    # Ultralytics accepts "mps" on Apple Silicon if torch supports it.
    try:
        import torch
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
        if hasattr(torch, "cuda") and torch.cuda.is_available():
            return 0
    except Exception:
        pass
    return "cpu"


def safe_rename(src: Path, dst: Path, dry_run: bool) -> Path:
    """Rename without overwriting: if target exists, add _1, _2, ..."""
    if src == dst:
        return src

    candidate = dst
    i = 1
    while candidate.exists():
        candidate = dst.with_name(f"{dst.stem}_{i}{dst.suffix}")
        i += 1

    if dry_run:
        print(f"DRY-RUN rename: {src.name} -> {candidate.name}")
        return candidate

    src.rename(candidate)
    print(f"Renamed: {src.name} -> {candidate.name}")
    return candidate


def prompt_folder() -> Path:
    raw = input("Enter folder containing videos: ").strip().strip('"').strip("'")
    return Path(raw).expanduser().resolve()


def strip_existing_prefix_and_tags(stem: str) -> str:
    """
    Mirrors your module behavior:
    - remove leading CLIP#_
    - remove trailing classification tags
    """
    s = re.sub(r"^CLIP\d+_", "", stem, flags=re.IGNORECASE)
    s = re.sub(r"_(INTEGRITY|CLAIMANT|HUMAN|UNKNOWN|PERSON)$", "", s, flags=re.IGNORECASE)
    return s


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


def scan_for_human(model, video_path: Path, conf: float, frame_stride: int, imgsz: int) -> bool | None:
    """
    Returns:
      True  -> human detected (early exit)
      False -> scanned full clip, no human
      None  -> detection unavailable / cannot open video
    """
    if model is None:
        return None

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return None

    device = pick_device()
    idx = 0

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                return False  # EOF, no human detected

            idx += 1
            if frame_stride > 1 and (idx % frame_stride) != 0:
                continue

            results = model.predict(
                source=frame,
                conf=conf,
                classes=[0],      # COCO "person"
                imgsz=imgsz,
                device=device,
                verbose=False,
            )

            if results and len(results) > 0:
                boxes = results[0].boxes
                if boxes is not None and len(boxes) > 0:
                    return True
    finally:
        cap.release()


def parse_clip_datetime(value: str) -> datetime.datetime | None:
    try:
        date_part, _ = value.split("_", 1)
        a_str, b_str, _ = date_part.split("-", 2)
        a = int(a_str)
        b = int(b_str)
    except ValueError:
        a = b = None

    formats = []
    if a is not None and b is not None:
        if a > 12 and b <= 12:
            formats.append("%d-%m-%Y_%H-%M-%S")
        elif b > 12 and a <= 12:
            formats.append("%m-%d-%Y_%H-%M-%S")

    if not formats:
        formats = ["%m-%d-%Y_%H-%M-%S", "%d-%m-%Y_%H-%M-%S"]
    elif formats[0].startswith("%m"):
        formats.append("%d-%m-%Y_%H-%M-%S")
    else:
        formats.append("%m-%d-%Y_%H-%M-%S")

    for fmt in formats:
        try:
            return datetime.datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def cliporder_rename(directory: Path, dry_run: bool) -> None:
    """
    Same approach as your module:
    - looks for MM-DD-YYYY_HH-MM-SS or DD-MM-YYYY_HH-MM-SS anywhere in filename
    - sorts by that datetime
    - renames to CLIP#_<original> (after stripping any existing CLIP#_)
    """
    pattern = re.compile(r"(\d{2}-\d{2}-\d{4}_\d{2}-\d{2}-\d{2})")
    items: list[tuple[datetime.datetime, Path]] = []

    for p in directory.iterdir():
        if not p.is_file():
            continue
        m = pattern.search(p.name)
        if not m:
            continue
        dt = parse_clip_datetime(m.group(1))
        if not dt:
            continue
        items.append((dt, p))

    items.sort(key=lambda x: x[0])

    for i, (_, p) in enumerate(items, start=1):
        base_no_clip = re.sub(r"^CLIP\d+_", "", p.stem, flags=re.IGNORECASE)
        target = p.with_name(f"CLIP{i}_{base_no_clip}{p.suffix}")
        safe_rename(p, target, dry_run=dry_run)


def format_hhmmss(total_seconds: float) -> str:
    secs = int(round(total_seconds))
    h = secs // 3600
    m = (secs % 3600) // 60
    s = secs % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def summarize_totals(folder: Path, exts: set[str]) -> None:
    human_seconds = 0.0
    covert_seconds = 0.0
    human_files = 0
    covert_files = 0
    unknown_durations = 0

    for p in folder.iterdir():
        if not p.is_file():
            continue
        if p.suffix.lower() not in exts:
            continue

        stem_up = p.stem.upper()

        is_human = stem_up.endswith("_HUMAN")
        is_covert = stem_up.endswith("_COVERT")  # matches your module naming

        if not (is_human or is_covert):
            continue

        dur = get_duration_seconds(p)
        if dur is None:
            unknown_durations += 1
            continue

        if is_human:
            human_seconds += dur
            human_files += 1
        if is_covert:
            covert_seconds += dur
            covert_files += 1

    if human_files or covert_files or unknown_durations:
        print()
        if human_files:
            print(f"Total {human_seconds/60.0:.2f} minutes of HUMAN video "
                  f"({format_hhmmss(human_seconds)} across {human_files} file(s))")
        else:
            print("Total 0.00 minutes of HUMAN video (00:00:00 across 0 file(s))")

        if covert_files:
            print(f"Total {covert_seconds/60.0:.2f} minutes of COVERT video "
                  f"({format_hhmmss(covert_seconds)} across {covert_files} file(s))")
        else:
            print("Total 0.00 minutes of COVERT video (00:00:00 across 0 file(s))")

        if unknown_durations:
            print(f"Note: {unknown_durations} file(s) had unknown duration and were not included in totals.")


def main():
    ap = argparse.ArgumentParser(
        description=(
            "Scan videos in a folder: if human detected append _HUMAN; else "
            "duration < threshold -> _INTEGRITY; duration >= threshold -> _UNKNOWN. "
            "Then apply CLIP# ordering based on MM-DD-YYYY_HH-MM-SS in filename. "
            "Finally, print totals for HUMAN and COVERT runtime."
        )
    )
    ap.add_argument("folder", nargs="?", default=None, help="Folder (optional; prompts if omitted)")
    ap.add_argument("--model", type=str, default="yolov8n.pt", help="YOLO model (default: yolov8n.pt)")
    ap.add_argument("--conf", type=float, default=0.35, help="Confidence threshold (default: 0.35)")
    ap.add_argument("--frame-stride", type=int, default=10, help="Check every Nth frame (default: 10)")
    ap.add_argument("--imgsz", type=int, default=640, help="Inference size (default: 640)")
    ap.add_argument("--integrity-seconds", type=float, default=30.0, help="Threshold seconds (default: 30)")
    ap.add_argument("--extensions", type=str, default="mp4,mov,mkv,avi,m4v", help="Comma-separated extensions")
    ap.add_argument("--dry-run", action="store_true", help="Print renames only; don’t rename")
    args = ap.parse_args()

    folder = prompt_folder() if args.folder is None else Path(args.folder).expanduser().resolve()
    if not folder.is_dir():
        print(f"Error: not a folder: {folder}", file=sys.stderr)
        sys.exit(1)

    exts = {("." + e.strip().lower().lstrip(".")) for e in args.extensions.split(",") if e.strip()}
    videos = sorted([p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in exts])

    if not videos:
        print("No videos found.")
        return

    # YOLO is optional; if missing, we fall back to duration-only classification.
    try:
        from ultralytics import YOLO
        yolo_model = YOLO(args.model)
    except Exception as e:
        yolo_model = None
        print(f"Warning: YOLO unavailable ({e}). Falling back to duration-only tagging.", file=sys.stderr)

    print(f"Folder: {folder}")
    print(f"Videos: {len(videos)}")
    print(f"Model:  {args.model if yolo_model else '(none)'}")
    print(f"Conf:   {args.conf}")
    print(f"Stride: {args.frame_stride}")
    print(f"Labeling rule (only if NO human detected):")
    print(f"  duration < {args.integrity_seconds}s  => _INTEGRITY")
    print(f"  duration >= {args.integrity_seconds}s => _UNKNOWN")
    print()

    # 1) Apply HUMAN/INTEGRITY/UNKNOWN tagging (for files in the extension set)
    for vp in videos:
        stem_clean = strip_existing_prefix_and_tags(vp.stem)
        duration = get_duration_seconds(vp)

        found = scan_for_human(
            model=yolo_model,
            video_path=vp,
            conf=args.conf,
            frame_stride=max(1, args.frame_stride),
            imgsz=args.imgsz,
        )

        if found is True:
            tag = "HUMAN"
        else:
            if duration is None:
                tag = "UNKNOWN"
            elif duration < float(args.integrity_seconds):
                tag = "INTEGRITY"
            else:
                tag = "UNKNOWN"

        dst = vp.with_name(f"{stem_clean}_{tag}{vp.suffix}")
        if vp.name == dst.name:
            print(f"OK: {vp.name}")
        else:
            safe_rename(vp, dst, dry_run=args.dry_run)

    print()
    print("Applying CLIP# ordering...")
    cliporder_rename(folder, dry_run=args.dry_run)

    if not args.dry_run:
        summarize_totals(folder, exts)

    print("Done.")


if __name__ == "__main__":
    main()
