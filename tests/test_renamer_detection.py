import unittest

from renamer_detection import (
    DETECTION_SETTINGS_VERSION,
    DETECTION_SETTINGS_VERSION_KEY,
    confidence_percent_for_sensitivity_index,
    frame_stride_for_confidence_percent,
    frame_stride_for_sensitivity_index,
    migrate_detection_settings,
    sensitivity_index_from_confidence_percent,
    should_sample_detection_frame,
)


class FakeSettings:
    def __init__(self, values):
        self.values = dict(values)
        self.synced = False

    def value(self, key, default=None, type=None):
        value = self.values.get(key, default)
        if type is not None and value is not None:
            return type(value)
        return value

    def setValue(self, key, value):
        self.values[key] = value

    def sync(self):
        self.synced = True


class RenamerDetectionTests(unittest.TestCase):
    def test_sensitivity_thresholds_improve_recall_as_label_increases(self):
        self.assertEqual(confidence_percent_for_sensitivity_index(0), 65)
        self.assertEqual(confidence_percent_for_sensitivity_index(1), 55)
        self.assertEqual(confidence_percent_for_sensitivity_index(2), 45)

        self.assertEqual(frame_stride_for_sensitivity_index(0), 10)
        self.assertEqual(frame_stride_for_sensitivity_index(1), 5)
        self.assertEqual(frame_stride_for_sensitivity_index(2), 3)

    def test_confidence_maps_back_to_sensitivity(self):
        self.assertEqual(sensitivity_index_from_confidence_percent(65), 0)
        self.assertEqual(sensitivity_index_from_confidence_percent(55), 1)
        self.assertEqual(sensitivity_index_from_confidence_percent(45), 2)

        self.assertEqual(frame_stride_for_confidence_percent(65), 10)
        self.assertEqual(frame_stride_for_confidence_percent(55), 5)
        self.assertEqual(frame_stride_for_confidence_percent(45), 3)

    def test_sampling_includes_first_and_last_frame(self):
        sampled = [
            frame
            for frame in range(1, 13)
            if should_sample_detection_frame(frame, frame_stride=5, total_frames=12)
        ]
        self.assertEqual(sampled, [1, 6, 11, 12])

    def test_stride_one_samples_every_frame(self):
        sampled = [
            frame
            for frame in range(1, 6)
            if should_sample_detection_frame(frame, frame_stride=1)
        ]
        self.assertEqual(sampled, [1, 2, 3, 4, 5])

    def test_migration_preserves_old_sensitivity_label_intent(self):
        old_high = FakeSettings({"vrn/ai_confidence": 65})
        migrate_detection_settings(old_high)
        self.assertEqual(old_high.values["vrn/ai_confidence"], 45)
        self.assertEqual(
            old_high.values[DETECTION_SETTINGS_VERSION_KEY],
            DETECTION_SETTINGS_VERSION,
        )
        self.assertTrue(old_high.synced)

        old_low = FakeSettings({"vrn/ai_confidence": 45})
        migrate_detection_settings(old_low)
        self.assertEqual(old_low.values["vrn/ai_confidence"], 65)


if __name__ == "__main__":
    unittest.main()
