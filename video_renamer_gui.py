#!/usr/bin/env python3
import datetime
import subprocess
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
from PyQt5 import QtCore, QtWidgets
from PyQt5.QtCore import QSettings

from timestamp import get_resource_path

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


def strip_existing_prefix_and_tags(stem: str) -> str:
    """
    Mirrors your module behavior:
    - remove leading CLIP#_
    - remove trailing classification tags
    """
    s = re.sub(r"^CLIP\d+_", "", stem, flags=re.IGNORECASE)
    # Strip one or more trailing tags to avoid double-append when re-running.
    s = re.sub(r"(_(INTEGRITY|CLAIMANT|HUMAN|UNKNOWN|PERSON|SUBJECT))+$", "", s, flags=re.IGNORECASE)
    return s


def extract_trailing_tags(stem: str) -> str:
    match = re.search(
        r"(_(INTEGRITY|CLAIMANT|HUMAN|UNKNOWN|PERSON|SUBJECT|COVERT))+$",
        stem,
        flags=re.IGNORECASE,
    )
    return match.group(1) if match else ""


def has_existing_classification_tag(stem: str) -> bool:
    stem_upper = stem.upper()
    return any(
        stem_upper.endswith(f"_{tag}")
        for tag in ("INTEGRITY", "CLAIMANT", "HUMAN", "UNKNOWN", "PERSON", "SUBJECT")
    )


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


class Cancelled(Exception):
    pass


def scan_for_human(model, video_path: Path, conf: float, frame_stride: int, should_stop=None) -> bool | None:
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
            if should_stop and should_stop():
                raise Cancelled()

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
                device=device,
                verbose=False,
            )

            if results and len(results) > 0:
                boxes = results[0].boxes
                if boxes is not None and len(boxes) > 0:
                    return True
    finally:
        cap.release()


def preferred_date_order_from_settings() -> str | None:
    settings = QSettings("VideoTimestamp", "VTS")
    fmt = settings.value("date_format", "%m-%d-%Y")
    if isinstance(fmt, str):
        if fmt.startswith("%d"):
            return "DMY"
        if fmt.startswith("%m") or fmt.startswith("%b"):
            return "MDY"
    return None


def parse_clip_datetime(value: str, preferred_order: str | None = None) -> datetime.datetime | None:
    try:
        date_part, _ = value.split("_", 1)
        a_str, b_str, _ = date_part.split("-", 2)
        a_is_alpha = a_str.isalpha()
        b_is_alpha = b_str.isalpha()
        if not a_is_alpha:
            a = int(a_str)
        else:
            a = None
        if not b_is_alpha:
            b = int(b_str)
        else:
            b = None
    except ValueError:
        a = b = None
        a_is_alpha = b_is_alpha = False

    formats = []
    if a_is_alpha and not b_is_alpha:
        formats.append("%b-%d-%Y_%H-%M-%S")
    elif b_is_alpha and not a_is_alpha:
        formats.append("%d-%b-%Y_%H-%M-%S")
    elif a is not None and b is not None:
        if a > 12 and b <= 12:
            formats.append("%d-%m-%Y_%H-%M-%S")
        elif b > 12 and a <= 12:
            formats.append("%m-%d-%Y_%H-%M-%S")
        elif preferred_order == "DMY":
            formats.append("%d-%m-%Y_%H-%M-%S")
        elif preferred_order == "MDY":
            formats.append("%m-%d-%Y_%H-%M-%S")

    fallback_formats = [
        "%m-%d-%Y_%H-%M-%S",
        "%d-%m-%Y_%H-%M-%S",
        "%b-%d-%Y_%H-%M-%S",
        "%d-%b-%Y_%H-%M-%S",
    ]
    if not formats:
        formats = fallback_formats
    else:
        for fmt in fallback_formats:
            if fmt not in formats:
                formats.append(fmt)

    for fmt in formats:
        try:
            return datetime.datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


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
    if sys.platform == "darwin" and getattr(sys, "frozen", False):
        exiftool_path = str(Path(sys._MEIPASS) / "exiftool" / "exiftool")
    else:
        exiftool_path = get_resource_path("exiftool")
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
    if sys.platform == "darwin" and getattr(sys, "frozen", False):
        exiftool_path = str(Path(sys._MEIPASS) / "exiftool" / "exiftool")
    else:
        exiftool_path = get_resource_path("exiftool")
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
) -> None:
    for vp in videos:
        if vp.suffix.lower() not in {".mov", ".mp4"}:
            continue
        dt = get_lawmate_exif_datetime(vp)
        if not dt:
            log(f"Lawmate: no EXIF timestamp for {vp.name}")
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
        if "_COVERT" not in tag_suffix.upper():
            tag_suffix = f"{tag_suffix}_COVERT"
        dst = vp.with_name(f"{date_label}_{time_label}{tag_suffix}{vp.suffix}")
        if vp.name == dst.name:
            log(f"Lawmate: OK {vp.name}")
            continue
        safe_rename(vp, dst, dry_run=dry_run, log=log)


def cliporder_rename(directory: Path, dry_run: bool, log, only_vts_outputs: bool = False) -> None:
    """
    Same approach as your module:
    - looks for MM-DD-YYYY_HH-MM-SS, DD-MM-YYYY_HH-MM-SS, or Mon-DD-YYYY_HH-MM-SS anywhere in filename
    - sorts by that datetime
    - renames to CLIP#_<original> (after stripping any existing CLIP#_)
    """
    pattern = re.compile(
        r"((?:\d{2}|[A-Za-z]{3})-(?:\d{2}|[A-Za-z]{3})-\d{4}_\d{2}-\d{2}-\d{2})",
        re.IGNORECASE,
    )
    items: list[tuple[datetime.datetime, Path]] = []

    for p in directory.iterdir():
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


def format_hhmmss(total_seconds: float) -> str:
    secs = int(round(total_seconds))
    h = secs // 3600
    m = (secs % 3600) // 60
    s = secs % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def summarize_totals(folder: Path, exts: set[str], human_tag: str) -> tuple[float, float, int, int, int]:
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

        is_human = stem_up.endswith(f"_{human_tag.upper()}")
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

    return human_seconds, covert_seconds, human_files, covert_files, unknown_durations


def build_duration_summary_message(
    folder: Path,
    exts: set[str],
    human_tag: str,
    prefix: str = "",
) -> str:
    human_seconds, covert_seconds, human_files, covert_files, unknown_durations = summarize_totals(
        folder, exts, human_tag
    )
    human_minutes = human_seconds / 60.0
    tag_label = human_tag.lower()

    if prefix:
        message = f"{prefix} {human_minutes:.2f} minutes of {tag_label} video"
    else:
        message = f"{human_minutes:.2f} minutes of {tag_label} video"

    if covert_files:
        covert_minutes = covert_seconds / 60.0
        message += f", {covert_minutes:.2f} minutes of covert video"
    if unknown_durations:
        message += f". {unknown_durations} file(s) had unknown duration"
    if human_files == 0 and covert_files == 0 and unknown_durations == 0:
        message += f". No tagged {tag_label}/covert files found"
    return message


@dataclass
class TaggerConfig:
    folder: Path
    model: str
    conf: float
    frame_stride: int
    integrity_seconds: float
    extensions: str
    dry_run: bool
    use_clip_numbers: bool
    use_ai_detection: bool
    respect_existing_tags: bool
    human_tag: str
    rename_lawmate_files: bool
    only_vts_outputs: bool


class VideoTaggerWorker(QtCore.QObject):
    log = QtCore.pyqtSignal(str)
    progress = QtCore.pyqtSignal(int, int)
    finished = QtCore.pyqtSignal()
    failed = QtCore.pyqtSignal(str)

    def __init__(self, config: TaggerConfig):
        super().__init__()
        self.config = config
        self._stop = False

    def stop(self):
        self._stop = True

    def _should_stop(self):
        return self._stop

    def run(self):
        try:
            self._run_impl()
        except Cancelled:
            self.log.emit("Cancelled.")
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()

    def _run_impl(self):
        cfg = self.config
        folder = cfg.folder

        if not folder.is_dir():
            self.failed.emit(f"Error: not a folder: {folder}")
            return

        exts = {("." + e.strip().lower().lstrip(".")) for e in cfg.extensions.split(",") if e.strip()}
        videos = sorted([p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in exts])

        if cfg.rename_lawmate_files:
            settings = QSettings("VideoTimestamp", "VTS")
            date_format = settings.value("date_format", "%m-%d-%Y")
            if not isinstance(date_format, str) or not date_format:
                date_format = "%m-%d-%Y"
            manually_adjusted_for_dst = settings.value("manually_adjusted_for_dst", False, type=bool)
            add_hour = settings.value("add_hour", False, type=bool)
            subtract_hour = settings.value("subtract_hour", False, type=bool)
            self.log.emit("Organizing detected unprocessed LawMate files from metadata timestamps...")
            lawmate_candidates = [
                p for p in videos
                if p.suffix.lower() in {".mov", ".mp4"}
                and not is_vts_processed_stem(p.stem)
                and is_lawmate_file(p)
            ]
            non_lawmate_skipped = len([
                p for p in videos
                if p.suffix.lower() in {".mov", ".mp4"}
                and not is_vts_processed_stem(p.stem)
            ]) - len(lawmate_candidates)
            if non_lawmate_skipped > 0:
                self.log.emit(
                    f"Skipped {non_lawmate_skipped} non-LawMate raw MOV/MP4 file(s)."
                )
            try:
                lawmate_rename(
                    videos=lawmate_candidates,
                    date_format=date_format,
                    manually_adjusted_for_dst=manually_adjusted_for_dst,
                    add_hour=add_hour,
                    subtract_hour=subtract_hour,
                    dry_run=cfg.dry_run,
                    log=self.log.emit,
                )
            except Exception as exc:
                self.log.emit(f"Warning: Lawmate rename failed ({exc}).")
            if not cfg.dry_run:
                videos = sorted([p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in exts])

        total_videos_found = len(videos)
        if cfg.only_vts_outputs:
            videos = [p for p in videos if is_vts_processed_stem(p.stem)]
            skipped = total_videos_found - len(videos)
            if skipped > 0:
                self.log.emit(f"Skipped {skipped} unprocessed original file(s).")

        if not videos:
            if cfg.only_vts_outputs:
                self.log.emit("No eligible processed videos found after excluding unprocessed originals.")
            else:
                self.log.emit("No videos found.")
            return

        yolo_model = None
        if cfg.use_ai_detection:
            # YOLO is optional; if missing, skip tagging.
            try:
                from ultralytics import YOLO
                yolo_model = YOLO(cfg.model)
            except Exception as e:
                yolo_model = None
                self.log.emit(f"Warning: YOLO unavailable ({e}). Skipping tagging.")

        self.log.emit(f"Folder: {folder}")
        self.log.emit(f"Videos: {len(videos)}")
        if cfg.use_ai_detection:
            self.log.emit(f"Model:  {cfg.model if yolo_model else '(none)'}")
            self.log.emit(f"Conf:   {cfg.conf}")
            self.log.emit(f"Stride: {cfg.frame_stride}")
        if cfg.use_ai_detection and yolo_model is not None:
            self.log.emit("Labeling rule (only if NO human detected):")
            self.log.emit(f"  duration < {cfg.integrity_seconds}s  => _INTEGRITY")
            self.log.emit(f"  duration >= {cfg.integrity_seconds}s => _UNKNOWN")
            self.log.emit("")

            # 1) Apply HUMAN/INTEGRITY/UNKNOWN tagging (for files in the extension set)
            total = len(videos)
            for i, vp in enumerate(videos, start=1):
                if self._should_stop():
                    raise Cancelled()

                self.log.emit(f"Analyzing file {i}/{total}")
                if cfg.respect_existing_tags and has_existing_classification_tag(vp.stem):
                    self.log.emit(f"Respecting existing tag: {vp.name}")
                    self.progress.emit(i, total)
                    continue
                if vp.stem.upper().endswith("_COVERT"):
                    self.log.emit(f"Preserving covert tag: {vp.name}")
                    self.progress.emit(i, total)
                    continue
                stem_clean = strip_existing_prefix_and_tags(vp.stem)
                duration = get_duration_seconds(vp)

                found = scan_for_human(
                    model=yolo_model,
                    video_path=vp,
                    conf=cfg.conf,
                    frame_stride=max(1, cfg.frame_stride),
                    should_stop=self._should_stop,
                )

                if found is True:
                    tag = cfg.human_tag
                else:
                    if duration is None:
                        tag = "UNKNOWN"
                    elif duration < float(cfg.integrity_seconds):
                        tag = "INTEGRITY"
                    else:
                        tag = "UNKNOWN"

                dst = vp.with_name(f"{stem_clean}_{tag}{vp.suffix}")
                if vp.name == dst.name:
                    self.log.emit(f"OK: {vp.name}")
                else:
                    safe_rename(vp, dst, dry_run=cfg.dry_run, log=self.log.emit)

                self.progress.emit(i, total)
        else:
            self.log.emit("AI tagging disabled; skipping HUMAN/INTEGRITY tagging.")

        if cfg.use_clip_numbers:
            self.log.emit("Applying CLIP# ordering...")
            cliporder_rename(
                folder,
                dry_run=cfg.dry_run,
                log=self.log.emit,
                only_vts_outputs=cfg.only_vts_outputs,
            )

        if not cfg.dry_run:
            self.log.emit("Renaming complete.")
        else:
            self.log.emit("Dry run complete. No files were renamed.")


class MainWindow(QtWidgets.QWidget):
    status_changed = QtCore.pyqtSignal(str)
    progress_changed = QtCore.pyqtSignal(int)
    run_started = QtCore.pyqtSignal()
    run_finished = QtCore.pyqtSignal()
    SENSITIVITY_THRESHOLDS = (65, 55, 45)  # Low, Medium, High sensitivity
    SENSITIVITY_LABELS = ("Low", "Medium", "High")

    def __init__(self, initial_folder: str | None = None):
        super().__init__()
        self.setWindowTitle("Video Renamer")
        self._thread = None
        self._worker = None
        self.folder_path = None

        self.folder_label = QtWidgets.QLabel("No folder selected")
        self.folder_label.setAlignment(QtCore.Qt.AlignCenter)
        self.folder_label.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.folder_btn = QtWidgets.QPushButton("Browse...")
        if initial_folder:
            self._set_folder_path(initial_folder)

        default_model = "yolov8n.pt"
        bundled_model = Path(__file__).with_name(default_model)
        if bundled_model.exists():
            default_model = str(bundled_model)
        self.model_edit = QtWidgets.QLineEdit(default_model)

        self.sensitivity_combo = QtWidgets.QComboBox()
        self.sensitivity_combo.addItems(list(self.SENSITIVITY_LABELS))
        self.sensitivity_combo.setCurrentIndex(1)

        self.stride_spin = QtWidgets.QSpinBox()
        self.stride_spin.setRange(1, 10_000)
        self.stride_spin.setValue(10)

        self.integrity_spin = QtWidgets.QDoubleSpinBox()
        self.integrity_spin.setRange(0.1, 36000.0)
        self.integrity_spin.setValue(30.0)

        self.extensions_edit = QtWidgets.QLineEdit("mp4,mov,mkv,avi,m4v")

        self.ai_detection_check = QtWidgets.QCheckBox("Detect and Tag Humans")
        self.ai_detection_check.setChecked(True)

        self.respect_existing_tags_check = QtWidgets.QCheckBox("Respect Existing Tags")
        self.respect_existing_tags_check.setChecked(True)

        self.clip_numbers_check = QtWidgets.QCheckBox("Label Clip Number")
        self.clip_numbers_check.setChecked(True)

        self.human_tag_combo = QtWidgets.QComboBox()
        self.human_tag_combo.addItems(["HUMAN", "CLAIMANT", "SUBJECT"])

        self.run_btn = QtWidgets.QPushButton("Rename Files")

        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)

        self.status_label = QtWidgets.QLabel("Idle.")
        self.status_label.setStyleSheet("color: grey; font-size: 10px;")
        self.status_label.setAlignment(QtCore.Qt.AlignCenter)
        self.status_label.setWordWrap(False)
        self.status_label.setFixedHeight(self.status_label.sizeHint().height())
        self.status_label.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed)
        status_font = self.status_label.font()
        status_font.setPointSize(10)
        self.status_label.setFont(status_font)
        form = QtWidgets.QFormLayout()
        folder_row = QtWidgets.QHBoxLayout()
        folder_row.addWidget(self.folder_label)
        folder_row.addWidget(self.folder_btn)
        form.addRow("Folder", folder_row)

        form.addRow("", self.clip_numbers_check)
        form.addRow("", self.ai_detection_check)
        form.addRow("", self.respect_existing_tags_check)
        sensitivity_row = QtWidgets.QHBoxLayout()
        sensitivity_row.addStretch(1)
        sensitivity_row.addWidget(QtWidgets.QLabel("Detection Sensitivity"))
        sensitivity_row.addWidget(self.sensitivity_combo)
        sensitivity_row.addStretch(1)
        form.addRow("", sensitivity_row)
        human_tag_row = QtWidgets.QHBoxLayout()
        human_tag_row.addWidget(QtWidgets.QLabel("Tag Human Clips As"))
        human_tag_row.addWidget(self.human_tag_combo)
        human_tag_row.addStretch(1)
        form.addRow("", human_tag_row)
        # Max integrity video length row hidden for now.
        # integrity_row = QtWidgets.QHBoxLayout()
        # integrity_row.addWidget(self.integrity_spin)
        # integrity_row.addWidget(QtWidgets.QLabel("seconds"))
        # integrity_row.addStretch(1)
        # form.addRow("Max integrity video length", integrity_row)

        button_row = QtWidgets.QHBoxLayout()
        button_row.addWidget(self.run_btn)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addStretch(1)
        layout.addLayout(form)
        layout.addLayout(button_row)
        layout.addStretch(1)

        self.folder_btn.clicked.connect(self._choose_folder)
        self.run_btn.clicked.connect(self._handle_run_button)
        self._load_settings()
        self._wire_settings_saves()

    def _settings(self):
        return QSettings("VideoTimestamp", "VTS")

    def _load_settings(self):
        settings = self._settings()
        self.clip_numbers_check.setChecked(settings.value("vrn/clip_numbers", True, type=bool))
        self.ai_detection_check.setChecked(settings.value("vrn/ai_detection", True, type=bool))
        self.respect_existing_tags_check.setChecked(
            settings.value("vrn/respect_existing_tags", True, type=bool)
        )
        saved_confidence = settings.value("vrn/ai_confidence", 55, type=int)
        self.sensitivity_combo.setCurrentIndex(self._confidence_to_sensitivity_index(int(saved_confidence)))
        tag = settings.value("vrn/human_tag", "HUMAN")
        index = self.human_tag_combo.findText(str(tag).upper())
        if index >= 0:
            self.human_tag_combo.setCurrentIndex(index)

    def _save_settings(self):
        settings = self._settings()
        settings.setValue("vrn/clip_numbers", self.clip_numbers_check.isChecked())
        settings.setValue("vrn/ai_detection", self.ai_detection_check.isChecked())
        settings.setValue("vrn/respect_existing_tags", self.respect_existing_tags_check.isChecked())
        settings.setValue("vrn/ai_confidence", self._current_confidence_percent())
        settings.setValue("vrn/human_tag", self.human_tag_combo.currentText().strip().upper())

    def _wire_settings_saves(self):
        self.clip_numbers_check.toggled.connect(self._save_settings)
        self.ai_detection_check.toggled.connect(self._save_settings)
        self.respect_existing_tags_check.toggled.connect(self._save_settings)
        self.sensitivity_combo.currentIndexChanged.connect(self._save_settings)
        self.human_tag_combo.currentIndexChanged.connect(self._save_settings)

    def _current_confidence_percent(self) -> int:
        return self.SENSITIVITY_THRESHOLDS[self.sensitivity_combo.currentIndex()]

    def _confidence_to_sensitivity_index(self, confidence_percent: int) -> int:
        return min(
            range(len(self.SENSITIVITY_THRESHOLDS)),
            key=lambda idx: abs(self.SENSITIVITY_THRESHOLDS[idx] - confidence_percent),
        )

    def _choose_folder(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Select Folder")
        if path:
            self._set_folder_path(path)

    def _set_folder_path(self, path: str):
        cleaned = path.strip().strip('"').strip("'")
        if not cleaned:
            self.folder_path = None
            self.folder_label.setText("No folder selected")
            return
        resolved = Path(cleaned).expanduser().resolve()
        self.folder_path = resolved
        self.folder_label.setText(resolved.name)

    def _set_running(self, running: bool):
        self.run_btn.setText("Cancel" if running else "Rename Files")
        self.run_btn.setEnabled(True)
        self.folder_btn.setEnabled(not running)

    def _handle_run_button(self):
        if self._worker is not None:
            self._cancel()
        else:
            self._start()

    def _cancel(self):
        if self._worker is None:
            return
        self._append_log("Cancelling...")
        self.run_btn.setText("Cancelling...")
        self.run_btn.setEnabled(False)
        self._worker.stop()

    def _start(self):
        if not self.folder_path:
            QtWidgets.QMessageBox.warning(self, "Missing Folder", "Please select a folder.")
            return

        cfg = TaggerConfig(
            folder=self.folder_path,
            model=self.model_edit.text().strip(),
            conf=float(self._current_confidence_percent()) / 100.0,
            frame_stride=int(self.stride_spin.value()),
            integrity_seconds=float(self.integrity_spin.value()),
            extensions=self.extensions_edit.text().strip(),
            dry_run=False,
            use_clip_numbers=self.clip_numbers_check.isChecked(),
            use_ai_detection=self.ai_detection_check.isChecked(),
            respect_existing_tags=self.respect_existing_tags_check.isChecked(),
            human_tag=self.human_tag_combo.currentText().strip().upper() or "HUMAN",
            rename_lawmate_files=True,
            only_vts_outputs=True,
        )

        self.progress_bar.setValue(0)
        self.status_label.setText("Starting")
        self.status_changed.emit("Starting")
        self.progress_changed.emit(0)
        self.run_started.emit()
        self._set_running(True)

        self._thread = QtCore.QThread()
        self._worker = VideoTaggerWorker(cfg)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.log.connect(self._append_log)
        self._worker.progress.connect(self._set_progress)
        self._worker.failed.connect(self._show_error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._on_worker_finished)

        self._thread.start()

    def _append_log(self, text: str):
        self.status_label.setText(text)
        self.status_changed.emit(text)

    def _set_progress(self, current: int, total: int):
        if total <= 0:
            value = 0
        else:
            value = int((current / total) * 100)
        self.progress_bar.setValue(value)
        self.progress_changed.emit(value)

    def _show_error(self, text: str):
        QtWidgets.QMessageBox.critical(self, "Error", text)
        self._append_log(f"Error: {text}")

    def _on_worker_finished(self):
        self._worker = None
        self._thread = None
        self._set_running(False)
        self.run_finished.emit()


def main():
    app = QtWidgets.QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
