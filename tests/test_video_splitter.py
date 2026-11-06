import unittest
from pathlib import Path
from unittest.mock import Mock

from video_splitter_gui import TARGET_PART_BYTES, SplitWorker, calculate_segment_duration, part_name


class VideoSplitterTests(unittest.TestCase):
    def test_segment_duration_targets_four_point_five_gb(self):
        self.assertAlmostEqual(
            calculate_segment_duration(9_000_000_000, 600),
            300.0,
        )

    def test_segment_duration_does_not_exceed_video_duration(self):
        self.assertEqual(
            calculate_segment_duration(TARGET_PART_BYTES // 2, 120),
            120.0,
        )

    def test_part_names_are_sequential_and_keep_extension(self):
        source = Path("client-delivery.MP4")
        self.assertEqual(part_name(source, 1), "client-delivery_Part_1.mp4")
        self.assertEqual(part_name(source, 12), "client-delivery_Part_12.mp4")

    def test_worker_uses_selected_maximum_and_ninety_percent_target(self):
        worker = SplitWorker([], max_part_bytes=6_000_000_000)
        self.assertEqual(worker.max_part_bytes, 6_000_000_000)
        self.assertEqual(worker.target_part_bytes, 5_400_000_000)


if __name__ == "__main__":
    unittest.main()
