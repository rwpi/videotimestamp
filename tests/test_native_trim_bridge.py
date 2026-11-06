from pathlib import Path

import native_trim_bridge
import pytest
import video_trimmer_gui
from finder_jobs import resolve_finder_selection


def test_explicit_native_selection_ignores_legacy_subject_filter(tmp_path):
    clip = tmp_path / "08-16-2026_14-33-50.mp4"
    clip.write_bytes(b"video")

    result = native_trim_bridge.native_trim_files(
        [str(clip)],
        {
            "trim_mode": "selection",
            "subject_only": True,
            "source": "subject",
        },
    )

    assert result == [clip.resolve()]


def test_native_selection_run_resolves_the_same_nested_set_as_preview(tmp_path):
    top_level = tmp_path / "08-14-2026_12-00-00.mp4"
    nested = tmp_path / "Camera" / "Events" / "08-14-2026_12-05-00.mp4"
    nested.parent.mkdir(parents=True)
    top_level.write_bytes(b"top")
    nested.write_bytes(b"nested")

    preview = resolve_finder_selection([str(tmp_path)], recursive=True)
    run = native_trim_bridge.native_trim_files(
        [str(tmp_path)],
        {"trim_mode": "selection", "subject_only": True, "source": "subject"},
    )

    assert run == list(preview.files)
    assert run == [top_level.resolve(), nested.resolve()]
