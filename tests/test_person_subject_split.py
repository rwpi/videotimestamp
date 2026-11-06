import unittest
from pathlib import Path

from merge_clips_gui import classify_merge_group


class PersonSubjectSplitTests(unittest.TestCase):
    def test_person_tag_is_not_subject_merge_group(self):
        self.assertEqual(
            classify_merge_group(Path("07-05-2026_09-00-00_PERSON.mp4")),
            "main",
        )

    def test_subject_tag_is_subject_merge_group(self):
        self.assertEqual(
            classify_merge_group(Path("07-05-2026_09-00-00_SUBJECT.mp4")),
            "subject",
        )


if __name__ == "__main__":
    unittest.main()
