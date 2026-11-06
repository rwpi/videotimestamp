from pathlib import Path

from timestamp import Worker


def _worker(root: Path, *, retain_originals: bool) -> Worker:
    return Worker(
        [],
        str(root),
        None,
        False,
        False,
        False,
        False,
        "%m-%d-%Y",
        retain_originals=retain_originals,
    )


def test_ungoverned_source_keeps_existing_delete_behavior(tmp_path):
    clip = tmp_path / "source.mp4"
    clip.write_bytes(b"ordinary working copy")

    _worker(tmp_path, retain_originals=False).move_original_file(str(clip))

    assert not clip.exists()
