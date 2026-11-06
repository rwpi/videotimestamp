import unittest
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QSettings
from PyQt5.QtWidgets import QApplication

from video_trimmer_gui import ORIGINALS_FOLDER_NAME, TRIMMED_CLIPS_FOLDER_NAME, TRIM_OUTPUT_REPLACE_AND_ARCHIVE, TrimWorker, trim_output_directory_for


class VideoTrimmerSettingsTests(unittest.TestCase):

    def test_every_operation_archives_into_the_same_originals_folder(self):
        # One folder, so a clip that gets timestamped, silenced and transcoded
        # leaves one pile of originals rather than three differently named ones.
        from original_archive import ORIGINALS_FOLDER_NAME as SHARED
        from video_transcoder_gui import ORIGINALS_FOLDER_NAME as TRANSCODE

        self.assertEqual(ORIGINALS_FOLDER_NAME, "originals")
        self.assertEqual(ORIGINALS_FOLDER_NAME, SHARED)
        self.assertEqual(TRANSCODE, SHARED)


    def test_hardware_trim_bitrate_tracks_the_source(self):
        worker = TrimWorker(
            Path("/case/work/clip.mp4"),
            0,
            10,
            TRIM_OUTPUT_REPLACE_AND_ARCHIVE,
        )
        worker.use_hwaccel = True
        worker.hwaccel_method = "h264_videotoolbox"
        with patch.object(worker, "_source_video_bitrate", return_value=3_400_000):
            args = worker._encoder_args()

        self.assertEqual(args[args.index("-b:v") + 1], "3740000")
        self.assertNotIn("12M", args)

    def test_trim_output_directory_uses_dedicated_child_folder(self):
        path = Path("/case/work/clip.mp4")
        self.assertEqual(
            trim_output_directory_for(path),
            Path("/case/work") / TRIMMED_CLIPS_FOLDER_NAME,
        )

    def test_trim_output_directory_does_not_nest_dedicated_folder(self):
        path = Path("/case/work") / TRIMMED_CLIPS_FOLDER_NAME / "clip.mp4"
        self.assertEqual(
            trim_output_directory_for(path),
            Path("/case/work") / TRIMMED_CLIPS_FOLDER_NAME,
        )


if __name__ == "__main__":
    unittest.main()
