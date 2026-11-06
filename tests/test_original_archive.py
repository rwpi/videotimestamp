from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import original_archive
from original_archive import (
    ORIGINALS_FOLDER_NAME,
    archive_original,
    archive_original_and_publish,
    is_camera_card_path,
    publish_beside_original,
    replacement_blocked_reason,
    unique_output_path,
)


class OriginalArchiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_one_folder_name_is_shared_by_every_operation(self) -> None:
        from video_transcoder_gui import ORIGINALS_FOLDER_NAME as TRANSCODE
        from video_trimmer_gui import ORIGINALS_FOLDER_NAME as TRIM
        from timestamp import ORIGINALS_FOLDER_NAME as TIMESTAMP

        self.assertEqual(ORIGINALS_FOLDER_NAME, "originals")
        for name in (TRANSCODE, TRIM, TIMESTAMP):
            self.assertEqual(name, ORIGINALS_FOLDER_NAME)

    def test_same_extension_output_replaces_the_original_in_place(self) -> None:
        source = self.root / "clip.mp4"
        source.write_bytes(b"original")
        staged = self.root / ".clip.tmp.mp4"
        staged.write_bytes(b"processed")

        published = publish_beside_original(source, staged, "clip.mp4")

        self.assertEqual(published, source)
        self.assertEqual(source.read_bytes(), b"processed")
        self.assertEqual(
            (self.root / ORIGINALS_FOLDER_NAME / "clip.mp4").read_bytes(), b"original"
        )
        self.assertFalse(staged.exists())

    def test_mp4_output_from_an_mts_source_still_leaves_one_working_clip(self) -> None:
        # Remove Audio always writes MP4, so a .MTS source cannot be replaced
        # at its own name. Archiving it still leaves exactly one copy of that
        # clip in the working folder, which is the point of replacing.
        source = self.root / "clip.MTS"
        source.write_bytes(b"original")
        staged = self.root / ".clip.tmp.mp4"
        staged.write_bytes(b"processed")

        published = publish_beside_original(source, staged, "clip.mp4")

        self.assertEqual(published, self.root / "clip.mp4")
        self.assertFalse(source.exists())
        self.assertEqual(
            (self.root / ORIGINALS_FOLDER_NAME / "clip.MTS").read_bytes(), b"original"
        )
        working = sorted(p.name for p in self.root.iterdir() if p.is_file())
        self.assertEqual(working, ["clip.mp4"])

    def test_a_failed_publish_puts_the_original_back(self) -> None:
        # The one outcome that cannot be undone is losing the original, so a
        # failure between the two moves must restore it.
        source = self.root / "clip.mp4"
        source.write_bytes(b"original")
        staged = self.root / ".clip.tmp.mp4"
        staged.write_bytes(b"processed")

        real_replace = os.replace
        calls = {"n": 0}

        def failing_replace(src, dst):
            calls["n"] += 1
            if calls["n"] == 2:
                raise OSError("publish failed")
            return real_replace(src, dst)

        with mock.patch.object(original_archive.os, "replace", failing_replace):
            with self.assertRaises(OSError):
                archive_original_and_publish(source, staged)

        self.assertTrue(source.exists())
        self.assertEqual(source.read_bytes(), b"original")

    def test_repeated_runs_do_not_overwrite_an_archived_original(self) -> None:
        first = self.root / "clip.mp4"
        first.write_bytes(b"first")
        archive_original(first)
        first.write_bytes(b"second")
        archive_original(first)

        archived = sorted(
            p.name for p in (self.root / ORIGINALS_FOLDER_NAME).iterdir()
        )
        self.assertEqual(archived, ["clip.mp4", "clip_1.mp4"])
        self.assertEqual(
            (self.root / ORIGINALS_FOLDER_NAME / "clip.mp4").read_bytes(), b"first"
        )
        self.assertEqual(
            (self.root / ORIGINALS_FOLDER_NAME / "clip_1.mp4").read_bytes(), b"second"
        )

    def test_unique_output_path_suffixes_only_on_collision(self) -> None:
        self.assertEqual(unique_output_path(self.root, "a.mp4"), self.root / "a.mp4")
        (self.root / "a.mp4").write_bytes(b"")
        self.assertEqual(unique_output_path(self.root, "a.mp4"), self.root / "a_1.mp4")


class CameraCardGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        original_archive._volume_is_removable.cache_clear()

    def tearDown(self) -> None:
        original_archive._volume_is_removable.cache_clear()
        self.temporary_directory.cleanup()

    def _card(self, path: str, *, removable: bool, media_root: str | None):
        volume = Path("/Volumes/TESTCARD")

        def fake_is_dir(self):
            return media_root is not None and self.name == media_root

        return (
            mock.patch.object(Path, "is_dir", fake_is_dir),
            mock.patch.object(
                original_archive, "_volume_is_removable", lambda _root: removable
            ),
            volume,
        )

    def test_a_removable_volume_holding_camera_media_is_a_card(self) -> None:
        is_dir, removable, volume = self._card(
            "x", removable=True, media_root="PRIVATE"
        )
        with is_dir, removable:
            self.assertTrue(is_camera_card_path(volume / "PRIVATE" / "clip.MTS"))

    def test_a_removable_working_drive_without_camera_media_is_not_a_card(self) -> None:
        # An external editing drive is a legitimate place to replace files.
        is_dir, removable, volume = self._card("x", removable=True, media_root=None)
        with is_dir, removable:
            self.assertFalse(is_camera_card_path(volume / "case" / "clip.mp4"))

    def test_a_fixed_volume_holding_dcim_is_not_a_card(self) -> None:
        is_dir, removable, volume = self._card(
            "x", removable=False, media_root="DCIM"
        )
        with is_dir, removable:
            self.assertFalse(is_camera_card_path(volume / "DCIM" / "clip.mp4"))

    def test_a_path_outside_volumes_is_never_a_card(self) -> None:
        self.assertFalse(is_camera_card_path(self.root / "clip.mp4"))

    def test_card_footage_may_not_be_replaced_in_place(self) -> None:
        with mock.patch.object(original_archive, "is_camera_card_path", lambda _p: True):
            reason = replacement_blocked_reason("/Volumes/CARD/PRIVATE/clip.MTS")
        self.assertIsNotNone(reason)
        self.assertIn("camera card", reason)

    def test_ordinary_working_files_may_be_replaced(self) -> None:
        clip = self.root / "clip.mp4"
        clip.write_bytes(b"")
        self.assertIsNone(replacement_blocked_reason(clip))


class RemoveAudioOutputModeTests(unittest.TestCase):
    """The complaint that started this: Remove Audio made a folder."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_replacing_is_the_default(self) -> None:
        from audio_remover import (
            REMOVE_AUDIO_REPLACE_AND_ARCHIVE,
            AudioRemovalWorker,
        )

        worker = AudioRemovalWorker([self.root / "clip.mp4"])
        self.assertEqual(worker.output_mode, REMOVE_AUDIO_REPLACE_AND_ARCHIVE)

    def test_an_unknown_mode_falls_back_to_replacing(self) -> None:
        from audio_remover import (
            REMOVE_AUDIO_REPLACE_AND_ARCHIVE,
            AudioRemovalWorker,
        )

        worker = AudioRemovalWorker([self.root / "clip.mp4"], output_mode="nonsense")
        self.assertEqual(worker.output_mode, REMOVE_AUDIO_REPLACE_AND_ARCHIVE)

    def test_the_dedicated_folder_is_still_available(self) -> None:
        from audio_remover import (
            REMOVE_AUDIO_DEDICATED_FOLDER,
            AudioRemovalWorker,
        )

        worker = AudioRemovalWorker(
            [self.root / "clip.mp4"], output_mode=REMOVE_AUDIO_DEDICATED_FOLDER
        )
        self.assertEqual(worker.output_mode, REMOVE_AUDIO_DEDICATED_FOLDER)

    def test_the_schema_default_replaces_and_the_runner_passes_it_through(self) -> None:
        from workflow_schemas import WORKFLOW_SCHEMAS

        options = {
            option["key"]: option["default"]
            for option in WORKFLOW_SCHEMAS["remove-audio"]["options"]
        }
        self.assertEqual(options["output_mode"], "replace_and_archive")

    def test_archived_originals_are_not_reprocessed(self) -> None:
        # Selecting the whole folder now reaches originals/ too, and an
        # archived original is the copy being kept, not new work.
        import audio_remover

        source = self.root / ORIGINALS_FOLDER_NAME / "clip.mp4"
        source.parent.mkdir()
        source.write_bytes(b"kept")
        worker = audio_remover.AudioRemovalWorker([source])
        skipped: list[str] = []
        worker.status.connect(skipped.append)
        worker.finished.connect(lambda outputs: None)
        worker.run()
        self.assertTrue(any("Skipping archived original" in line for line in skipped))
        self.assertEqual(source.read_bytes(), b"kept")


class MergeArchivesItsInputsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_clips_that_fed_the_merge_are_archived_but_the_output_is_not(self) -> None:
        from vts_job_runner import _archive_merged_inputs

        first = self.root / "a.mp4"
        first.write_bytes(b"a")
        second = self.root / "b.mp4"
        second.write_bytes(b"b")
        merged = self.root / "merged.mp4"
        merged.write_bytes(b"merged")

        archived, kept = _archive_merged_inputs(
            [("main", [first, second])], [str(merged)]
        )

        self.assertEqual(len(archived), 2)
        self.assertEqual(kept, [])
        self.assertTrue(merged.exists())
        self.assertFalse(first.exists())
        self.assertFalse(second.exists())
        self.assertEqual(
            sorted(p.name for p in (self.root / ORIGINALS_FOLDER_NAME).iterdir()),
            ["a.mp4", "b.mp4"],
        )

    def test_a_merged_output_listed_as_an_input_is_never_archived(self) -> None:
        from vts_job_runner import _archive_merged_inputs

        merged = self.root / "merged.mp4"
        merged.write_bytes(b"merged")

        archived, _kept = _archive_merged_inputs(
            [("main", [merged])], [str(merged)]
        )

        self.assertEqual(archived, [])
        self.assertTrue(merged.exists())

    def test_clips_that_must_keep_their_place_are_reported_not_moved(self) -> None:
        from vts_job_runner import _archive_merged_inputs

        protected = self.root / "evidence.mp4"
        protected.write_bytes(b"evidence")

        with mock.patch.object(
            original_archive, "is_camera_card_path", lambda _p: True
        ):
            archived, kept = _archive_merged_inputs(
                [("main", [protected])], [str(self.root / "merged.mp4")]
            )

        self.assertEqual(archived, [])
        self.assertEqual(kept, [str(protected)])
        self.assertTrue(protected.exists())


class ArchivedOriginalsAreNeverReingestedTests(unittest.TestCase):
    """Every operation now archives into one folder, so every operation's
    selection has to skip it. Without this a recursive run queues the working
    clip and its archived twin and produces two results for one clip."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        (self.root / "clip.mp4").write_bytes(b"working")
        (self.root / ORIGINALS_FOLDER_NAME).mkdir()
        (self.root / ORIGINALS_FOLDER_NAME / "clip.mp4").write_bytes(b"archived")
        (self.root / "untrimmed_clips").mkdir()
        (self.root / "untrimmed_clips" / "old.mp4").write_bytes(b"legacy")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_a_recursive_folder_scan_skips_the_archive(self) -> None:
        from finder_jobs import resolve_finder_selection

        selection = resolve_finder_selection([str(self.root)], recursive=True)
        self.assertEqual([p.name for p in selection.files], ["clip.mp4"])
        self.assertTrue(
            all(ORIGINALS_FOLDER_NAME not in p.parts for p in selection.files)
        )

    def test_the_legacy_trim_archive_is_skipped_too(self) -> None:
        from finder_jobs import resolve_finder_selection

        selection = resolve_finder_selection([str(self.root)], recursive=True)
        self.assertNotIn("old.mp4", [p.name for p in selection.files])

    def test_an_explicitly_selected_archived_file_still_resolves(self) -> None:
        # Skipping applies to walking a folder, not to a file the operator
        # deliberately picked out of the archive.
        from finder_jobs import resolve_finder_selection

        archived = self.root / ORIGINALS_FOLDER_NAME / "clip.mp4"
        selection = resolve_finder_selection([str(archived)])
        self.assertEqual([p.name for p in selection.files], ["clip.mp4"])

    def test_is_archived_original_matches_nested_paths(self) -> None:
        from original_archive import is_archived_original

        self.assertTrue(is_archived_original(self.root / ORIGINALS_FOLDER_NAME / "a.mp4"))
        self.assertTrue(is_archived_original(self.root / "untrimmed_clips" / "a.mp4"))
        self.assertFalse(is_archived_original(self.root / "a.mp4"))


class CardSourcesAreRefusedBeforeAnyWorkTests(unittest.TestCase):
    """Falling back to a dedicated folder is not enough on a card: that folder
    would be created on the card. The job has to stop before it writes."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.clip = self.root / "oncard.MTS"
        self.clip.write_bytes(b"evidence")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _selection(self):
        from types import SimpleNamespace

        return SimpleNamespace(files=[self.clip])

    def test_a_card_source_raises_before_anything_is_created(self) -> None:
        from vts_job_runner import JobRequestError, _reject_camera_card_sources

        with mock.patch.object(
            original_archive, "is_camera_card_path", lambda _p: True
        ):
            with self.assertRaises(JobRequestError) as raised:
                _reject_camera_card_sources(self._selection())

        message = str(raised.exception)
        self.assertIn("camera card", message)
        self.assertIn("Import them first", message)
        self.assertIn("oncard.MTS", message)
        # Nothing was created beside the clip.
        self.assertEqual([p.name for p in self.root.iterdir()], ["oncard.MTS"])
        self.assertEqual(self.clip.read_bytes(), b"evidence")

    def test_ordinary_sources_pass_straight_through(self) -> None:
        from vts_job_runner import _reject_camera_card_sources

        self.assertIsNone(_reject_camera_card_sources(self._selection()))


    def _selection_merge_options(self) -> dict:
        return {
            "merge_mode": "selection",
            "output_mode": "dedicated_folder",
            "output_folder": "",
            "client_delivery": False,
            "client_quality": "high",
            "client_max_size_gb": 2.0,
        }

    def test_selection_merge_refuses_a_card_clip(self) -> None:
        from types import SimpleNamespace

        import vts_job_runner

        with (
            mock.patch.object(
                original_archive, "is_camera_card_path", lambda _p: True
            ),
            mock.patch.object(
                vts_job_runner,
                "_selection",
                lambda _paths: SimpleNamespace(
                    files=[self.clip], working_folder=self.root
                ),
            ),
            mock.patch("merge_clips_gui.MergeWorker") as worker,
        ):
            with self.assertRaises(vts_job_runner.JobRequestError) as raised:
                vts_job_runner._run_merge(
                    mock.Mock(),
                    [str(self.clip)],
                    self._selection_merge_options(),
                )

        self.assertIn("camera card", str(raised.exception))
        worker.assert_not_called()
        self.assertEqual([p.name for p in self.root.iterdir()], ["oncard.MTS"])


if __name__ == "__main__":
    unittest.main()
