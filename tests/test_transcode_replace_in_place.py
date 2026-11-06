"""Transcode replaces the working video by default and keeps the original.

The dangerous half of this workflow is not the encode, it is the swap. These
cover the swap and the refusals around it; the encode itself is exercised by
tests/test_video_transcoder.py.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from video_transcoder_gui import (
    ORIGINALS_FOLDER_NAME,
    TRANSCODE_OUTPUT_DEDICATED_FOLDER,
    TRANSCODE_OUTPUT_REPLACE_AND_ARCHIVE,
    archive_original_and_publish,
    replacement_is_forbidden,
    staging_output_path,
)
from workflow_schemas import WORKFLOW_SCHEMAS, validate_workflow_options


class ArchiveAndPublishTests(unittest.TestCase):
    def test_the_original_survives_under_its_own_name(self) -> None:
        with TemporaryDirectory() as raw:
            folder = Path(raw)
            source = folder / "clip.mp4"
            source.write_bytes(b"original")
            staged = folder / ".clip.vts-transcode-tmp-1-0.mp4"
            staged.write_bytes(b"transcoded")

            published = archive_original_and_publish(source, staged)

            self.assertEqual(published, source)
            self.assertEqual(source.read_bytes(), b"transcoded")
            archived = folder / ORIGINALS_FOLDER_NAME / "clip.mp4"
            self.assertEqual(archived.read_bytes(), b"original")
            self.assertFalse(staged.exists())

    def test_a_second_run_does_not_overwrite_the_first_original(self) -> None:
        with TemporaryDirectory() as raw:
            folder = Path(raw)
            originals = folder / ORIGINALS_FOLDER_NAME
            originals.mkdir()
            (originals / "clip.mp4").write_bytes(b"first original")
            source = folder / "clip.mp4"
            source.write_bytes(b"second original")
            staged = folder / ".clip.vts-transcode-tmp-1-0.mp4"
            staged.write_bytes(b"transcoded")

            archive_original_and_publish(source, staged)

            self.assertEqual((originals / "clip.mp4").read_bytes(), b"first original")
            survivors = sorted(p.read_bytes() for p in originals.iterdir())
            self.assertIn(b"second original", survivors)
            self.assertEqual(len(survivors), 2)

    def test_staging_is_a_hidden_sibling_so_the_publish_stays_atomic(self) -> None:
        with TemporaryDirectory() as raw:
            source = Path(raw) / "clip.mp4"
            source.write_bytes(b"original")

            staged = staging_output_path(source)

            self.assertEqual(staged.parent, source.parent)
            self.assertTrue(staged.name.startswith("."))
            self.assertFalse(staged.exists())


class RefusalTests(unittest.TestCase):


    def test_an_ordinary_folder_is_not_forbidden(self) -> None:
        with TemporaryDirectory() as raw:
            clip = Path(raw) / "clip.mp4"
            clip.write_bytes(b"footage")

            self.assertFalse(replacement_is_forbidden(clip))


class SchemaTests(unittest.TestCase):
    def test_replacing_is_the_default_and_the_folder_remains_available(self) -> None:
        options = validate_workflow_options("transcode", {})

        self.assertEqual(options["output_mode"], TRANSCODE_OUTPUT_REPLACE_AND_ARCHIVE)
        choices = {
            choice["value"]
            for option in WORKFLOW_SCHEMAS["transcode"]["options"]
            if option["key"] == "output_mode"
            for choice in option["choices"]
        }
        self.assertEqual(
            choices,
            {TRANSCODE_OUTPUT_REPLACE_AND_ARCHIVE, TRANSCODE_OUTPUT_DEDICATED_FOLDER},
        )


if __name__ == "__main__":
    unittest.main()
