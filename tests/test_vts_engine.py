import json
import os
import tempfile
import unittest
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch


import vts_engine


def test_capabilities_are_headless_and_report_shared_tools():
    response = vts_engine.handle_request({"action": "capabilities"})

    assert response["ok"] is True
    assert response["protocol_version"] == 1
    assert response["engine"]["headless"] is True
    assert set(response["tools"]) == {"ffmpeg", "ffprobe", "exiftool"}
    assert all("available" in status for status in response["tools"].values())


def test_inspect_missing_file_is_a_successful_per_file_result(tmp_path):
    missing = tmp_path / "missing.mp4"

    response = vts_engine.handle_request(
        {"action": "inspect_videos", "paths": [str(missing)]}
    )

    assert response["ok"] is True
    assert response["files"][0]["path"] == str(missing.resolve())
    assert response["files"][0]["exists"] is False
    assert response["files"][0]["warnings"]


def test_inspect_video_collects_probe_and_exif_results(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"placeholder")
    tools = {
        "ffmpeg": {"resolved_path": "/tools/ffmpeg"},
        "ffprobe": {"resolved_path": "/tools/ffprobe"},
        "exiftool": {"resolved_path": "/tools/exiftool"},
    }
    probe_result = {
        "format": {"duration": "12.5", "format_name": "mov,mp4"},
        "streams": [{"codec_type": "video", "width": 1920, "height": 1080}],
    }
    exif_result = [{"CreateDate": "2026:08:14 09:30:00"}]

    with patch("vts_engine._run_json_command", side_effect=[probe_result, exif_result]):
        result = vts_engine.inspect_video(str(video), tools)

    assert result["duration_seconds"] == 12.5
    assert result["format_name"] == "mov,mp4"
    assert (result["width"], result["height"]) == (1920, 1080)
    assert result["dates"]["CreateDate"] == "2026:08:14 09:30:00"


def test_invalid_paths_return_protocol_error():
    response = vts_engine.process_line(
        json.dumps({"action": "inspect_videos", "paths": "not-a-list"})
    )

    assert response["ok"] is False
    assert response["error"]["code"] == "invalid_paths"


def test_request_cli_round_trip():
    engine_path = Path(vts_engine.__file__).resolve()
    completed = subprocess.run(
        [sys.executable, str(engine_path), "--request"],
        input=json.dumps({"action": "capabilities"}),
        text=True,
        capture_output=True,
        check=True,
    )

    response = json.loads(completed.stdout)
    assert response["ok"] is True
    assert response["engine"]["name"] == "VTS Python Engine"


def test_capabilities_publish_full_workflow_schema_without_qsettings_keys():
    response = vts_engine.handle_request({"action": "capabilities"})
    workflows = {workflow["id"]: workflow for workflow in response["workflows"]}

    assert response["workflow_schema_version"] == 8
    assert {
        "import-files",
        "timestamp",
        "remove-audio",
        "clip-order",
        "video-minutes",
        "trim",
        "transcode",
        "merge",
    } == set(workflows)
    assert workflows["transcode"]["selection_mode"] == "files_or_folder"
    assert all(
        "qsettings_key" not in option
        for workflow in workflows.values()
        for option in workflow["options"]
    )


def test_trim_setup_returns_native_cached_ranges(monkeypatch, tmp_path):
    clip = tmp_path / "08-14-2026_12-00-00_SUBJECT.mp4"
    clip.write_bytes(b"video")
    monkeypatch.setattr(
        "native_trim_bridge.native_trim_setup",
        lambda paths, options: [
            {
                "path": str(clip),
                "duration": 60.0,
                "suggested_start": 8.0,
                "suggested_end": 44.0,
                "has_cached_suggestion": True,
                "is_linked_context": False,
            }
        ],
    )

    response = vts_engine.handle_request(
        {"action": "trim_setup", "paths": [str(clip)], "options": {}}
    )

    assert response["ok"] is True
    assert response["clips"][0]["suggested_start"] == 8.0
    assert response["clips"][0]["has_cached_suggestion"] is True


def test_preferences_endpoints_delegate_to_allowlisted_store(monkeypatch):
    monkeypatch.setattr(vts_engine, "read_workflow_preferences", lambda: {"use_hwaccel": True})
    saved = {}

    def save(values):
        saved.update(values)
        return dict(values)

    monkeypatch.setattr(vts_engine, "save_workflow_preferences", save)

    read_response = vts_engine.handle_request({"action": "preferences"})
    write_response = vts_engine.handle_request(
        {"action": "save_preferences", "preferences": {"use_hwaccel": False}}
    )

    assert read_response["preferences"] == {"use_hwaccel": True}
    assert write_response["preferences"] == {"use_hwaccel": False}
    assert saved == {"use_hwaccel": False}


def test_finder_extension_status_and_enable_are_native_engine_actions(monkeypatch):
    import finder_extension

    extension = Path("/Applications/VTS.app/Contents/PlugIns/VTSFinderExtension.appex")
    monkeypatch.setattr(finder_extension, "find_finder_extension", lambda: extension)
    monkeypatch.setattr(finder_extension, "find_quick_actions", lambda: {})
    monkeypatch.setattr(finder_extension, "finder_extension_election", lambda: "use")
    monkeypatch.setattr(finder_extension, "plugin_election", lambda _bundle_id: "unknown")
    monkeypatch.setattr(finder_extension, "enable_finder_extension", lambda: extension)
    repaired = []
    monkeypatch.setattr(finder_extension, "repair_finder_actions", lambda: repaired.append(True))

    status = vts_engine.handle_request({"action": "finder_extension_status"})
    enabled = vts_engine.handle_request({"action": "enable_finder_extension"})
    repair = vts_engine.handle_request({"action": "repair_finder_actions"})

    assert status["installed"] is True
    assert status["enabled"] is True
    assert status["election"] == "use"
    assert len(status["quick_actions"]) == 6
    assert all(not item["installed"] for item in status["quick_actions"])
    assert enabled["extension_path"].endswith("VTSFinderExtension.appex")
    assert repair["enabled"] is True
    assert repaired == [True]
