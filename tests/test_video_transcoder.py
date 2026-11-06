from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5 import QtWidgets

import video_transcoder_gui as transcoder


class _MemorySettings:
    values: dict[str, object] = {}

    def __init__(self, *_args, **_kwargs):
        pass

    def value(self, key, default=None, type=None):
        value = self.values.get(key, default)
        if type is None or value is None:
            return value
        return type(value)

    def setValue(self, key, value):
        self.values[key] = value


class _PreviewPanel(QtWidgets.QWidget):
    def set_video(self, _path):
        pass


class TranscodeCommandTests(unittest.TestCase):
    def test_balanced_preset_uses_constant_quality_h264(self):
        command = transcoder.build_transcode_command(
            "ffmpeg",
            Path("input.mp4"),
            Path("output.mp4"),
            "balanced",
            "original",
            True,
        )

        self.assertIn("libx264", command)
        self.assertEqual(command[command.index("-crf") + 1], "23")
        self.assertNotIn("-b:v", command)
        self.assertEqual(command[command.index("-b:a") + 1], "128k")
        self.assertIn("+faststart", command)

    def test_size_limit_reserves_headroom_below_requested_file_size(self):
        max_bytes = 4_500_000_000
        duration = 6_670.630633
        bitrate = transcoder.calculate_video_bitrate_limit(
            duration,
            max_bytes,
            False,
        )
        command = transcoder.build_transcode_command(
            "ffmpeg",
            Path("input.mp4"),
            Path("output.mp4"),
            "balanced",
            "original",
            False,
            max_bytes,
            duration,
        )

        self.assertLess(bitrate * duration / 8, max_bytes)
        self.assertEqual(command[command.index("-maxrate") + 1], str(bitrate))
        self.assertEqual(command[command.index("-bufsize") + 1], str(bitrate * 2))

    def test_hevc_preset_marks_mp4_for_apple_compatibility(self):
        args = transcoder.transcode_video_args("hevc", "original")

        self.assertIn("libx265", args)
        self.assertEqual(args[args.index("-tag:v") + 1], "hvc1")

    def test_720p_option_never_upscales_and_keeps_even_dimensions(self):
        args = transcoder.transcode_video_args("balanced", "720p")
        filter_value = args[args.index("-vf") + 1]

        self.assertIn("min(1280,iw)", filter_value)
        self.assertIn("min(720,ih)", filter_value)
        self.assertIn("force_divisible_by=2", filter_value)


if __name__ == "__main__":
    unittest.main()
