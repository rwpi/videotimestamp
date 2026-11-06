"""Versioned, UI-independent workflow descriptions for VTS clients.

The schema is intentionally plain Python data.  Swift, a future web client, and
the current PyQt handoff all consume the same option keys and validation rules.
"""

from __future__ import annotations

import datetime as _datetime
from typing import Any


WORKFLOW_SCHEMA_VERSION = 8


SETTINGS_SECTIONS_BY_KEY = {
    "use_hwaccel": "Encoding & Performance",
    "remove_audio": "Encoding & Performance",
    "vrn/clip_numbers": "File Organization",
    "auto_populate_file_queues": "File Organization",
    "skip_panasonic_vx3_timestamp": "Camera Rules",
    "skip_viofo_timestamp": "Camera Rules",
    "skip_lawmate_timestamp": "Camera Rules",
    "retain_originals": "Import & Originals",
    "skip_duplicates": "Import & Originals",
    "manually_adjusted_for_dst": "Time Correction",
    "add_hour": "Time Correction",
    "subtract_hour": "Time Correction",
    "date_format": "Date & Naming",
    "merge/target_resolution": "Editing & Delivery",
    "merge/target_fps": "Editing & Delivery",
    "merge/aspect_ratio_handling": "Editing & Delivery",
    "merge/by_type": "Editing & Delivery",
}


def _choice(value: Any, label: str) -> dict[str, Any]:
    return {"value": value, "label": label}


def _option(
    key: str,
    label: str,
    kind: str,
    default: Any,
    *,
    qsettings_key: str | None = None,
    help_text: str = "",
    choices: list[dict[str, Any]] | None = None,
    minimum: float | None = None,
    maximum: float | None = None,
    step: float | None = None,
    required: bool = False,
    path_mode: str | None = None,
    hidden: bool = False,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "kind": kind,
        "default": default,
        "qsettings_key": qsettings_key,
        "help": help_text,
        "choices": choices or [],
        "minimum": minimum,
        "maximum": maximum,
        "step": step,
        "required": required,
        "path_mode": path_mode,
        # Hidden means "not offered", never "not valid": the option is kept
        # out of the public schema so no client renders or sends it, while
        # validation still accepts it -- an already-running app or a saved
        # request from before the hiding must not start failing.
        "hidden": hidden,
    }


DATE_FORMAT_CHOICES = [
    _choice("%m-%d-%Y", "MM-DD-YYYY (US)"),
    _choice("%d-%m-%Y", "DD-MM-YYYY (International)"),
    _choice("%b-%d-%Y", "Mon-DD-YYYY"),
    _choice("%d-%b-%Y", "DD-Mon-YYYY"),
]
WORKFLOW_SCHEMAS: dict[str, dict[str, Any]] = {
    "import-files": {
        "title": "Import Camera Media",
        "category": "Get Media Ready",
        "symbol": "square.and.arrow.down",
        "summary": "Copy camcorder and covert-camera footage for the selected recording date.",
        "selection_mode": "none",
        "launch_label": "Import Media",
        "execution_mode": "background",
        "options": [
            _option(
                "import_date",
                "Recording date",
                "date",
                _datetime.date.today().isoformat(),
                help_text="Only camera media recorded on this date is imported.",
            ),
            _option(
                "destination",
                "Save imported footage to",
                "path",
                "",
                qsettings_key="import_destination_base",
                path_mode="folder",
            ),
            _option(
                "skip_duplicates",
                "Skip duplicate or already-processed files",
                "boolean",
                True,
                qsettings_key="skip_duplicates",
            ),
        ],
    },
    "timestamp": {
        "title": "Timestamp Videos",
        "category": "Legacy",
        "symbol": "clock.badge.checkmark",
        "summary": "Prepare camcorder footage, add visible date-and-time overlays where needed, and apply camera-specific clock rules.",
        "selection_mode": "files_or_folder",
        "launch_label": "Timestamp Videos",
        "execution_mode": "background",
        "options": [
            _option("use_hwaccel", "Use hardware acceleration", "boolean", True, qsettings_key="use_hwaccel"),
            _option("remove_audio", "Remove audio", "boolean", False, hidden=True),
            _option("retain_originals", "Keep original files", "boolean", True, qsettings_key="retain_originals"),
            _option("date_format", "Date and filename format", "choice", "%m-%d-%Y", qsettings_key="date_format", choices=DATE_FORMAT_CHOICES),
            _option("dst_fix", "Apply Sony daylight-saving correction", "boolean", False, qsettings_key="manually_adjusted_for_dst"),
            _option("add_hour", "Add one hour", "boolean", False, qsettings_key="add_hour"),
            _option("subtract_hour", "Subtract one hour", "boolean", False, qsettings_key="subtract_hour"),
            _option("skip_panasonic", "Skip overlay for Panasonic HC-VX3", "boolean", False, qsettings_key="skip_panasonic_vx3_timestamp"),
            _option("skip_viofo", "Skip overlay for VIOFO dash cam", "boolean", True, qsettings_key="skip_viofo_timestamp"),
            _option("skip_lawmate", "Skip overlay for LawMate files", "boolean", True, qsettings_key="skip_lawmate_timestamp"),
        ],
    },
    "clip-order": {
        "title": "Order Clips",
        "category": "Legacy",
        "symbol": "list.number",
        "summary": "Rename LawMate clips from embedded recording time and number timestamped clips chronologically, or sort raw Reolink archive files into dated lens and stream folders.",
        "selection_mode": "files_or_folder",
        "launch_label": "Organize Clips",
        "execution_mode": "background",
        "options": [
            _option("clip_numbers", "Add CLIP# prefix", "boolean", True, qsettings_key="vrn/clip_numbers"),
            _option("auto_populate", "Automatically populate from working folder", "boolean", True, qsettings_key="auto_populate_file_queues"),
        ],
    },
    "video-minutes": {
        "title": "Calculate Runtime",
        "category": "Find & Organize",
        "symbol": "sum",
        "summary": "Count selected clips and calculate their total running time without changing any files.",
        "selection_mode": "files_or_folder",
        "launch_label": "Calculate Runtime",
        "execution_mode": "background",
        "options": [],
    },
    "remove-audio": {
        "title": "Remove Audio",
        "category": "Edit & Deliver",
        "symbol": "speaker.slash",
        "summary": "Create verified video-only MP4 copies and archive the originals.",
        "selection_mode": "files_or_folder",
        "launch_label": "Remove Audio",
        "execution_mode": "background",
        "options": [
            _option("output_mode", "Output handling", "choice", "replace_and_archive", qsettings_key="remove_audio/output_mode", choices=[
                _choice("replace_and_archive", "Replace working clips and archive originals"),
                _choice("dedicated_folder", "Save into an Audio Removed folder"),
            ]),
        ],
    },
    "trim": {
        "title": "Trim Clips",
        "category": "Edit & Deliver",
        "symbol": "scissors",
        "summary": "Preview clips in QuickTime and manually choose the exact start and end of each trimmed copy.",
        "selection_mode": "files_or_folder",
        "launch_label": "Trim Selected Clips",
        "execution_mode": "staged_native",
        "options": [
            _option("output_mode", "Output handling", "choice", "replace_and_archive", qsettings_key="trim/output_mode", choices=[
                _choice("replace_and_archive", "Replace working clips and archive originals"),
                _choice("dedicated_folder", "Save into a Trimmed Clips folder"),
            ]),
            _option("use_hwaccel", "Use hardware acceleration", "boolean", True, qsettings_key="use_hwaccel"),
            _option("include_audio", "Keep audio when present", "boolean", True, qsettings_key="trim/include_audio"),
            _option("remove_audio", "Remove audio", "boolean", True, hidden=True),
        ],
        "interactive_note": "QuickTime playback, frame stepping, and manual per-clip range handles are available above.",
    },
    "transcode": {
        "title": "Prepare Videos for Delivery",
        "category": "Edit & Deliver",
        "symbol": "shippingbox.and.arrow.backward",
        "summary": "Create client-ready copies at a chosen quality, splitting only when needed to stay below a delivery limit.",
        "selection_mode": "files_or_folder",
        "launch_label": "Prepare for Delivery",
        "execution_mode": "background",
        "options": [
            _option("output_mode", "Output handling", "choice", "replace_and_archive", qsettings_key="transcode/output_mode", choices=[
                _choice("replace_and_archive", "Replace working videos and archive originals"),
                _choice("dedicated_folder", "Save into a Transcoded Videos folder"),
            ]),
            _option("quality", "Quality", "choice", "balanced", qsettings_key="transcode/quality_preset", choices=[
                _choice("high", "High Quality"),
                _choice("balanced", "Balanced (Recommended)"),
                _choice("compact", "Compact"),
                _choice("hevc", "Smallest (HEVC)"),
            ]),
            _option("resolution", "Resolution", "choice", "original", qsettings_key="transcode/resolution", choices=[
                _choice("original", "Keep original (Recommended)"),
                _choice("1080p", "1080p maximum"),
                _choice("720p", "720p maximum"),
            ]),
            _option("include_audio", "Include audio when present", "boolean", True, qsettings_key="transcode/include_audio"),
            _option("max_size_enabled", "Keep every delivered file under a size limit", "boolean", True, qsettings_key="transcode/max_size_enabled"),
            _option("max_size_gb", "Delivery size limit (GB)", "number", 4.5, qsettings_key="transcode/max_size_gb", minimum=0.25, maximum=100.0, step=0.25),
            _option("size_strategy", "When a video is still too large", "choice", "preserve_quality", qsettings_key="transcode/size_strategy", choices=[
                _choice("preserve_quality", "Preserve quality and split into parts (Recommended)"),
                _choice("single_file", "Reduce bitrate to keep one file"),
            ], help_text="The recommended mode encodes once at the selected quality, then divides only oversized results without re-encoding them."),
        ],
    },
    "merge": {
        "title": "Combine Video Clips",
        "category": "Edit & Deliver",
        "symbol": "rectangle.3.group",
        "summary": "Chronologically combine clips from one or several same-clock cameras.",
        "selection_mode": "files_or_folder",
        "launch_label": "Combine Clips",
        "execution_mode": "background",
        "options": [
            _option("output_mode", "Merged clip handling", "choice", "replace_and_archive", qsettings_key="merge/output_mode", choices=[
                _choice("replace_and_archive", "Archive the clips that were merged"),
                _choice("dedicated_folder", "Leave the merged clips in place"),
            ]),
            _option("by_type", "Separate merged videos by SUBJECT and INTEGRITY tag", "boolean", False, qsettings_key="merge/by_type"),
            _option("resolution", "Target resolution", "choice", "", qsettings_key="merge/target_resolution", choices=[
                _choice("", "Automatic (most common)"),
                _choice("1920x1080", "1920 × 1080"),
                _choice("2560x1080", "2560 × 1080"),
                _choice("2560x1440", "2560 × 1440"),
                _choice("3840x2160", "3840 × 2160 (4K)"),
            ]),
            _option("fps", "Target frame rate", "choice", "", qsettings_key="merge/target_fps", choices=[
                _choice("", "Automatic (most common)"),
                *[_choice(str(value), f"{value:g} fps") for value in (20.0, 24.0, 25.0, 29.97, 30.0, 50.0, 59.94, 60.0)],
            ]),
            _option("aspect", "Aspect-ratio handling", "choice", "letterbox", qsettings_key="merge/aspect_ratio_handling", choices=[
                _choice("letterbox", "Letterbox with black bars"),
                _choice("stretch", "Stretch to fit"),
            ]),
            _option("client_delivery", "Create a smaller client-ready file while merging", "boolean", False, qsettings_key="merge/client_delivery_enabled"),
            _option("client_quality", "Client-delivery quality", "choice", "balanced", qsettings_key="merge/client_delivery_quality", choices=[
                _choice("high", "High Quality"),
                _choice("balanced", "Balanced (Recommended)"),
                _choice("compact", "Compact"),
            ]),
            _option("client_max_size_gb", "Maximum client file size (GB)", "number", 4.5, qsettings_key="merge/client_delivery_max_size_gb", minimum=0.5, maximum=100.0, step=0.5),
            _option("use_hwaccel", "Use hardware acceleration", "boolean", True, qsettings_key="use_hwaccel"),
            _option("remove_audio", "Remove audio", "boolean", True, qsettings_key="remove_audio"),
            # Where the merged file is written. Empty writes beside the queued clips.
            _option("output_folder", "Merged output folder", "path", "", qsettings_key="merge/output_folder", path_mode="folder"),
        ],
    },
}


def _preference_identifier(settings_key: str) -> str:
    return settings_key.replace("/", ".")


for _workflow in WORKFLOW_SCHEMAS.values():
    for _definition in _workflow["options"]:
        _settings_key = _definition.get("qsettings_key")
        _definition["preference_id"] = (
            _preference_identifier(_settings_key) if _settings_key else None
        )
        _definition["placement"] = (
            "settings" if _settings_key in SETTINGS_SECTIONS_BY_KEY else "workflow"
        )
        _definition["settings_section"] = SETTINGS_SECTIONS_BY_KEY.get(_settings_key)


def public_workflow_schemas() -> list[dict[str, Any]]:
    result = []
    for action, schema in WORKFLOW_SCHEMAS.items():
        public_schema = {
            key: value
            for key, value in schema.items()
            if key != "options"
        }
        public_schema["id"] = action
        public_schema["bridge_status"] = "available"
        public_schema["options"] = [
            {key: value for key, value in option.items() if key != "qsettings_key"}
            for option in schema["options"]
            if not option.get("hidden")
        ]
        result.append(public_schema)
    return result


def preference_definitions() -> dict[str, dict[str, Any]]:
    """Return one canonical definition for every persisted workflow setting."""
    definitions: dict[str, dict[str, Any]] = {}
    for workflow in WORKFLOW_SCHEMAS.values():
        for option in workflow["options"]:
            preference_id = option.get("preference_id")
            if not preference_id:
                continue
            existing = definitions.get(preference_id)
            if existing is not None:
                for field in ("kind", "default", "choices", "minimum", "maximum"):
                    if existing[field] != option[field]:
                        raise ValueError(
                            f"Conflicting definitions for preference {preference_id}: {field}"
                        )
                continue
            definitions[preference_id] = option
    return definitions


def _validate_option_value(definition: dict[str, Any], value: Any) -> Any:
    key = definition["key"]
    kind = definition["kind"]
    if kind == "boolean":
        if not isinstance(value, bool):
            raise ValueError(f"{key} must be true or false.")
    elif kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{key} must be a number.")
        minimum = definition.get("minimum")
        maximum = definition.get("maximum")
        if minimum is not None and value < minimum:
            raise ValueError(f"{key} must be at least {minimum}.")
        if maximum is not None and value > maximum:
            raise ValueError(f"{key} must be at most {maximum}.")
    elif kind in {"path", "date", "text"}:
        if not isinstance(value, str):
            raise ValueError(f"{key} must be text.")
        if definition.get("required") and not value.strip():
            raise ValueError(f"{definition['label']} is required.")
        if kind == "date" and value:
            try:
                _datetime.date.fromisoformat(value)
            except ValueError as error:
                raise ValueError(f"{key} must use YYYY-MM-DD format.") from error
    elif kind == "choice":
        allowed = [choice["value"] for choice in definition["choices"]]
        allowed += list(definition.get("also_accepts", ()))
        if value not in allowed:
            raise ValueError(f"Unsupported value for {key}: {value!r}")
    else:
        raise ValueError(f"Unsupported option kind: {kind}")
    return value


def validate_workflow_options(action: str, raw_options: Any) -> dict[str, Any]:
    if action not in WORKFLOW_SCHEMAS:
        raise ValueError(f"Unsupported VTS workflow: {action}")
    if raw_options is None:
        raw_options = {}
    if not isinstance(raw_options, dict):
        raise ValueError("Workflow options must be a JSON object.")

    definitions = {option["key"]: option for option in WORKFLOW_SCHEMAS[action]["options"]}
    unknown = sorted(set(raw_options) - set(definitions))
    if unknown:
        raise ValueError(f"Unsupported {action} option(s): {', '.join(unknown)}")

    validated: dict[str, Any] = {}
    for key, definition in definitions.items():
        value = raw_options.get(key, definition["default"])
        validated[key] = _validate_option_value(definition, value)

    return validated


def validate_preference_values(raw_preferences: Any) -> dict[str, Any]:
    if not isinstance(raw_preferences, dict):
        raise ValueError("Preferences must be a JSON object.")
    definitions = preference_definitions()
    unknown = sorted(set(raw_preferences) - set(definitions))
    if unknown:
        raise ValueError(f"Unsupported preference(s): {', '.join(unknown)}")
    return {
        preference_id: _validate_option_value(definitions[preference_id], value)
        for preference_id, value in raw_preferences.items()
    }


def qsettings_values(action: str, options: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    definitions = {option["key"]: option for option in WORKFLOW_SCHEMAS[action]["options"]}
    for key, value in options.items():
        settings_key = definitions[key].get("qsettings_key")
        if settings_key:
            values[settings_key] = value
    return values
