from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from finder_jobs import resolve_finder_selection


class FinderJobTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self):
        self.temporary_directory.cleanup()


    def test_folder_selection_collects_only_immediate_supported_videos(self):
        first = self.root / "one.mp4"
        second = self.root / "two.MTS"
        ignored = self.root / "notes.txt"
        nested = self.root / "nested"
        nested.mkdir()
        for path in (first, second, ignored, nested / "three.mov"):
            path.touch()

        selection = resolve_finder_selection([self.root])

        self.assertEqual(set(selection.files), {first.resolve(), second.resolve()})
        self.assertEqual(selection.directories, (self.root.resolve(),))
        self.assertEqual(selection.working_folder, self.root.resolve())

    def test_recursive_folder_selection_collects_nested_supported_videos(self):
        first = self.root / "day-one" / "Zoom" / "Main" / "one.mp4"
        second = self.root / "day-two" / "Zoom" / "Main" / "two.MTS"
        ignored = self.root / "day-two" / "notes.txt"
        for path in (first, second, ignored):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()

        selection = resolve_finder_selection([self.root], recursive=True)

        self.assertEqual(set(selection.files), {first.resolve(), second.resolve()})
        self.assertEqual(selection.directories, (self.root.resolve(),))
        self.assertEqual(selection.working_folder, self.root.resolve())


if __name__ == "__main__":
    unittest.main()
