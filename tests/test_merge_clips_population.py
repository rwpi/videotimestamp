import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication, QMessageBox

from merge_clips_gui import MergeWorker, calculate_client_video_bitrate_limit, merge_clip_sort_key
from settings_coercion import optional_positive_float


class MemorySettings:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def value(self, key, default=None, type=None):
        value = self.values.get(key, default)
        if type is None or value is None:
            return value
        return type(value)

    def setValue(self, key, value):
        self.values[key] = value


class MergeClipsPopulationTests(unittest.TestCase):
    def test_automatic_merge_fps_accepts_blank_qsettings_value(self):
        self.assertIsNone(optional_positive_float(""))
        self.assertIsNone(optional_positive_float("   "))
        self.assertIsNone(optional_positive_float(None))
        self.assertIsNone(optional_positive_float("not-a-frame-rate"))
        self.assertIsNone(optional_positive_float(0))
        self.assertEqual(optional_positive_float("29.97"), 29.97)

    def test_client_size_bitrate_reserves_headroom_for_audio_and_container(self):
        duration_seconds = 6_670.630633
        max_output_bytes = 4_500_000_000

        video_bitrate = calculate_client_video_bitrate_limit(
            duration_seconds,
            max_output_bytes,
            include_audio=True,
        )

        projected_bytes = (
            (video_bitrate + 32_000 + 192_000) * duration_seconds / 8
        )
        self.assertLessEqual(projected_bytes, max_output_bytes * 0.96)

    def test_client_delivery_uses_hardware_encoder_and_size_aware_bitrate(self):
        with (
            mock.patch("merge_clips_gui.QSettings", return_value=MemorySettings()),
            mock.patch(
                "merge_clips_gui.filter_hwaccel_methods",
                return_value="h264_videotoolbox",
            ),
        ):
            worker = MergeWorker(
                Path("/tmp"),
                [],
                client_delivery=True,
                client_quality="balanced",
                client_max_output_bytes=4_500_000_000,
            )
        worker.use_hwaccel = True
        worker.hwaccel_method = "h264_videotoolbox"

        args = worker._video_encoder_args(6_670.630633, include_audio=False)

        self.assertEqual(args[:4], ["-c:v", "h264_videotoolbox", "-b:v", "5000000"])
        self.assertIn("-maxrate", args)
        self.assertNotIn("libx264", args)

    def test_client_delivery_software_fallback_keeps_quality_preset_and_cap(self):
        with (
            mock.patch("merge_clips_gui.QSettings", return_value=MemorySettings()),
            mock.patch("merge_clips_gui.filter_hwaccel_methods", return_value=None),
        ):
            worker = MergeWorker(
                Path("/tmp"),
                [],
                client_delivery=True,
                client_quality="balanced",
                client_max_output_bytes=4_500_000_000,
            )
        worker.use_hwaccel = False

        args = worker._video_encoder_args(6_670.630633, include_audio=True)

        self.assertEqual(args[:6], ["-c:v", "libx264", "-preset", "fast", "-crf", "23"])
        self.assertIn("-maxrate", args)
        self.assertNotIn("-b:v", args)


    def test_clip_sort_uses_recording_timestamp_before_clip_number(self):
        august_four_late = Path("CLIP20_08-04-2026_11-00-00.mp4")
        august_five_early = Path("CLIP1_08-05-2026_10-00-00.mp4")

        self.assertEqual(
            sorted(
                [august_five_early, august_four_late],
                key=merge_clip_sort_key,
            ),
            [august_four_late, august_five_early],
        )

    def test_merge_drop_order_is_normalized_to_filename_timestamps(self):
        dropped = [
            Path("08-16-2026_16-22-00.MP4"),
            Path("08-16-2026_14-32-21.mp4"),
            Path("08-16-2026_16-21-00.MP4"),
            Path("08-16-2026_14-19-21.MP4"),
            Path("08-16-2026_14-28-18.mp4"),
        ]

        ordered = sorted(dropped, key=merge_clip_sort_key)

        self.assertEqual(
            [path.name for path in ordered],
            [
                "08-16-2026_14-19-21.MP4",
                "08-16-2026_14-28-18.mp4",
                "08-16-2026_14-32-21.mp4",
                "08-16-2026_16-21-00.MP4",
                "08-16-2026_16-22-00.MP4",
            ],
        )


    def test_merge_worker_refuses_a_folder_on_a_card(self):
        # The merged video is written into the worker's folder. Every runner
        # refuses first; this covers callers that do not check.
        folder = Path("/tmp/2026-07-30")
        clip = folder / "07-30-2026_10-00-00_SUBJECT.mp4"
        with (
            mock.patch("merge_clips_gui.QSettings", return_value=MemorySettings()),
            mock.patch("merge_clips_gui.filter_hwaccel_methods", return_value=None),
        ):
            worker = MergeWorker(folder, [("main", [clip])])
        finished = []
        failures = []
        worker.finished.connect(finished.append)
        worker.failed.connect(failures.append)

        with (
            mock.patch("merge_clips_gui.is_camera_card_path", return_value=True),
            mock.patch.object(worker, "_merge_group") as merge_group,
        ):
            worker.run()

        self.assertEqual(finished, [])
        self.assertEqual(len(failures), 1)
        self.assertIn("camera card", failures[0])
        self.assertIn(folder.name, failures[0])
        merge_group.assert_not_called()


if __name__ == "__main__":
    unittest.main()
