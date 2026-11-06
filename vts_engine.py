#!/usr/bin/env python3
"""Headless JSON bridge for native VTS clients and future server workers.

The protocol uses JSON requests and responses and intentionally has no GUI
imports. It publishes every current workflow through a versioned schema, offers
read-only media inspection, and safely hands validated queues and settings to
the existing Python workflow views without starting processing.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from typing import Any, TextIO

from finder_jobs import read_workflow_preferences, save_workflow_preferences
from media_tool_paths import (
    get_bundled_exiftool_path,
    get_bundled_ffmpeg_path,
    get_bundled_ffprobe_path,
)
from workflow_schemas import (
    WORKFLOW_SCHEMA_VERSION,
    public_workflow_schemas,
    validate_workflow_options,
)


PROTOCOL_VERSION = 1
VIDEO_EXTENSIONS = {
    ".3gp",
    ".avi",
    ".m2ts",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp4",
    ".mts",
    ".ts",
    ".webm",
}


class EngineRequestError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _tool_command(tool: str) -> str:
    return {
        "ffmpeg": get_bundled_ffmpeg_path,
        "ffprobe": get_bundled_ffprobe_path,
        "exiftool": get_bundled_exiftool_path,
    }[tool]()


def _resolved_executable(command: str) -> str | None:
    expanded = str(Path(command).expanduser())
    if os.path.sep in expanded:
        path = Path(expanded)
        return str(path.resolve()) if path.is_file() and os.access(path, os.X_OK) else None
    return shutil.which(command)


def _first_version_line(executable: str, tool: str) -> str | None:
    arguments = ["-ver"] if tool == "exiftool" else ["-version"]
    try:
        result = subprocess.run(
            [executable, *arguments],
            capture_output=True,
            check=False,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    output = result.stdout.strip() or result.stderr.strip()
    return output.splitlines()[0] if output else None


def tool_capabilities() -> dict[str, dict[str, Any]]:
    tools: dict[str, dict[str, Any]] = {}
    for tool in ("ffmpeg", "ffprobe", "exiftool"):
        command = _tool_command(tool)
        resolved = _resolved_executable(command)
        tools[tool] = {
            "command": command,
            "resolved_path": resolved,
            "available": resolved is not None,
            "version": _first_version_line(resolved, tool) if resolved else None,
        }
    return tools


def capabilities_response() -> dict[str, Any]:
    return {
        "ok": True,
        "protocol_version": PROTOCOL_VERSION,
        "engine": {
            "name": "VTS Python Engine",
            "python_version": platform.python_version(),
            "python_executable": sys.executable,
            "platform": sys.platform,
            "machine": platform.machine(),
            "headless": True,
        },
        "tools": tool_capabilities(),
        "workflow_schema_version": WORKFLOW_SCHEMA_VERSION,
        "workflows": public_workflow_schemas(),
    }


def preferences_response() -> dict[str, Any]:
    try:
        preferences = read_workflow_preferences()
    except (ImportError, OSError, RuntimeError) as error:
        raise EngineRequestError(
            "preferences_unavailable",
            f"VTS could not read its saved settings: {error}",
        ) from error
    return {
        "ok": True,
        "protocol_version": PROTOCOL_VERSION,
        "preferences": preferences,
    }


def save_preferences_response(raw_preferences: Any) -> dict[str, Any]:
    try:
        preferences = save_workflow_preferences(raw_preferences)
    except ValueError as error:
        raise EngineRequestError("invalid_preferences", str(error)) from error
    except (ImportError, OSError, RuntimeError) as error:
        raise EngineRequestError(
            "preferences_unavailable",
            f"VTS could not save its settings: {error}",
        ) from error
    return {
        "ok": True,
        "protocol_version": PROTOCOL_VERSION,
        "preferences": preferences,
    }


def trim_setup_response(paths: Any, raw_options: Any = None) -> dict[str, Any]:
    if not isinstance(paths, list) or not paths or not all(isinstance(path, str) for path in paths):
        raise EngineRequestError("invalid_paths", "Add at least one video or folder for trimming.")
    try:
        options = validate_workflow_options("trim", raw_options)
        from native_trim_bridge import native_trim_setup

        clips = native_trim_setup(paths, options)
    except ValueError as error:
        raise EngineRequestError("invalid_options", str(error)) from error
    return {
        "ok": True,
        "protocol_version": PROTOCOL_VERSION,
        "clips": clips,
    }


def finder_extension_response(*, enable: bool = False, repair: bool = False) -> dict[str, Any]:
    if sys.platform != "darwin":
        raise EngineRequestError(
            "finder_extension_unavailable",
            "The VTS Finder extension is available only on macOS.",
        )
    try:
        from finder_extension import (
            QUICK_ACTION_BUNDLE_IDS,
            enable_finder_extension,
            find_finder_extension,
            find_quick_actions,
            finder_extension_election,
            plugin_election,
            repair_finder_actions,
        )

        if enable:
            extension = enable_finder_extension()
        else:
            if repair:
                repair_finder_actions()
            extension = find_finder_extension()
        election = finder_extension_election()
        actions = find_quick_actions()
        quick_actions = [
            {
                "bundle_id": bundle_id,
                "installed": bundle_id in actions,
                "election": plugin_election(bundle_id) if bundle_id in actions else "unknown",
            }
            for bundle_id in QUICK_ACTION_BUNDLE_IDS
        ]
    except OSError as error:
        raise EngineRequestError("finder_extension_failed", str(error)) from error
    return {
        "ok": True,
        "protocol_version": PROTOCOL_VERSION,
        "installed": extension is not None,
        "enabled": election == "use",
        "election": election,
        "quick_actions": quick_actions,
        "extension_path": str(extension) if extension is not None else None,
    }


def _run_json_command(arguments: list[str], timeout: int = 30) -> Any:
    result = subprocess.run(
        arguments,
        capture_output=True,
        check=False,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        raise RuntimeError(detail)
    return json.loads(result.stdout)


def _probe_video(path: Path, ffprobe: str | None) -> tuple[float | None, str | None, int | None, int | None]:
    if not ffprobe:
        return None, None, None, None
    payload = _run_json_command(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration,format_name:stream=codec_type,width,height",
            "-of",
            "json",
            str(path),
        ]
    )
    format_data = payload.get("format") or {}
    try:
        duration = float(format_data["duration"])
    except (KeyError, TypeError, ValueError):
        duration = None
    format_name = format_data.get("format_name")
    video_stream = next(
        (stream for stream in payload.get("streams", []) if stream.get("codec_type") == "video"),
        {},
    )
    return duration, format_name, video_stream.get("width"), video_stream.get("height")


def _read_media_dates(path: Path, exiftool: str | None) -> dict[str, str]:
    if not exiftool:
        return {}
    payload = _run_json_command(
        [
            exiftool,
            "-j",
            "-DateTimeOriginal",
            "-CreateDate",
            "-MediaCreateDate",
            "-TrackCreateDate",
            "-FileModifyDate",
            str(path),
        ]
    )
    if not isinstance(payload, list) or not payload:
        return {}
    metadata = payload[0]
    return {
        key: str(metadata[key])
        for key in (
            "DateTimeOriginal",
            "CreateDate",
            "MediaCreateDate",
            "TrackCreateDate",
            "FileModifyDate",
        )
        if metadata.get(key) is not None
    }


def inspect_video(path_value: str, tools: dict[str, dict[str, Any]]) -> dict[str, Any]:
    path = Path(path_value).expanduser().resolve()
    result: dict[str, Any] = {
        "path": str(path),
        "name": path.name,
        "extension": path.suffix.lower(),
        "supported_extension": path.suffix.lower() in VIDEO_EXTENSIONS,
        "exists": path.exists(),
        "is_file": path.is_file(),
        "size_bytes": path.stat().st_size if path.is_file() else None,
        "duration_seconds": None,
        "format_name": None,
        "width": None,
        "height": None,
        "dates": {},
        "warnings": [],
    }
    if not path.is_file():
        result["warnings"].append("File does not exist or is not a regular file.")
        return result

    ffprobe = tools["ffprobe"].get("resolved_path")
    exiftool = tools["exiftool"].get("resolved_path")
    try:
        duration, format_name, width, height = _probe_video(path, ffprobe)
        result.update(
            duration_seconds=duration,
            format_name=format_name,
            width=width,
            height=height,
        )
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as error:
        result["warnings"].append(f"FFprobe inspection failed: {error}")
    try:
        result["dates"] = _read_media_dates(path, exiftool)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as error:
        result["warnings"].append(f"ExifTool inspection failed: {error}")
    return result


def inspect_videos_response(paths: Any) -> dict[str, Any]:
    if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
        raise EngineRequestError("invalid_paths", "'paths' must be a JSON array of strings.")
    if len(paths) > 10_000:
        raise EngineRequestError("too_many_paths", "A request may inspect at most 10,000 paths.")
    tools = tool_capabilities()
    return {
        "ok": True,
        "protocol_version": PROTOCOL_VERSION,
        "tools": tools,
        "files": [inspect_video(path, tools) for path in paths],
    }


def handle_request(request: Any) -> dict[str, Any]:
    if not isinstance(request, dict):
        raise EngineRequestError("invalid_request", "A request must be a JSON object.")
    action = request.get("action")
    if action == "capabilities":
        return capabilities_response()
    if action == "inspect_videos":
        return inspect_videos_response(request.get("paths"))
    if action == "preferences":
        return preferences_response()
    if action == "save_preferences":
        return save_preferences_response(request.get("preferences"))
    if action == "trim_setup":
        return trim_setup_response(request.get("paths"), request.get("options"))
    if action == "finder_extension_status":
        return finder_extension_response()
    if action == "enable_finder_extension":
        return finder_extension_response(enable=True)
    if action == "repair_finder_actions":
        return finder_extension_response(repair=True)
    raise EngineRequestError("unknown_action", f"Unknown engine action: {action!r}")


def error_response(error: Exception) -> dict[str, Any]:
    if isinstance(error, EngineRequestError):
        code = error.code
        message = error.message
    elif isinstance(error, json.JSONDecodeError):
        code = "invalid_json"
        message = str(error)
    else:
        code = "engine_error"
        message = str(error)
    return {
        "ok": False,
        "protocol_version": PROTOCOL_VERSION,
        "error": {"code": code, "message": message},
    }


def process_line(line: str) -> dict[str, Any]:
    try:
        return handle_request(json.loads(line))
    except Exception as error:
        return error_response(error)


def run_stdio(input_stream: TextIO, output_stream: TextIO, pretty: bool = False) -> None:
    for line in input_stream:
        if not line.strip():
            continue
        json.dump(process_line(line), output_stream, indent=2 if pretty else None, sort_keys=pretty)
        output_stream.write("\n")
        output_stream.flush()


def main(argv: list[str] | None = None) -> int:
    command_line = list(sys.argv[1:] if argv is None else argv)
    if command_line and command_line[0] == "--job-runner":
        # A packaged app ships one executable for both Python entry points.
        # This is the same process a development build starts as
        # `python3 vts_job_runner.py`, so the job protocol is unchanged.
        from vts_job_runner import main as run_job

        return run_job(command_line[1:])

    parser = argparse.ArgumentParser(description="VTS headless JSON engine")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--request", action="store_true", help="Read one JSON request from stdin")
    mode.add_argument("--stdio", action="store_true", help="Read JSON Lines requests until stdin closes")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    arguments = parser.parse_args(command_line)

    if arguments.stdio:
        run_stdio(sys.stdin, sys.stdout, arguments.pretty)
        return 0

    response = process_line(sys.stdin.read())
    json.dump(response, sys.stdout, indent=2 if arguments.pretty else None, sort_keys=arguments.pretty)
    sys.stdout.write("\n")
    return 0 if response.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
