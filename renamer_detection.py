DEFAULT_SENSITIVITY_INDEX = 1
DETECTION_SETTINGS_VERSION = 2
DETECTION_SETTINGS_VERSION_KEY = "vrn/detection_settings_version"

# Low, Medium, High sensitivity. Lower confidence and lower stride improve recall.
AI_CONFIDENCE_BY_SENSITIVITY = (65, 55, 45)
AI_FRAME_STRIDE_BY_SENSITIVITY = (10, 5, 3)


def clamp_sensitivity_index(index: int) -> int:
    return max(0, min(index, len(AI_CONFIDENCE_BY_SENSITIVITY) - 1))


def confidence_percent_for_sensitivity_index(index: int) -> int:
    return AI_CONFIDENCE_BY_SENSITIVITY[clamp_sensitivity_index(index)]


def frame_stride_for_sensitivity_index(index: int) -> int:
    return AI_FRAME_STRIDE_BY_SENSITIVITY[clamp_sensitivity_index(index)]


def sensitivity_index_from_confidence_percent(confidence_percent: int) -> int:
    if confidence_percent <= 50:
        return 2
    if confidence_percent >= 60:
        return 0
    return 1


def frame_stride_for_confidence_percent(confidence_percent: int) -> int:
    return frame_stride_for_sensitivity_index(
        sensitivity_index_from_confidence_percent(confidence_percent)
    )


def migrate_detection_settings(settings) -> None:
    version = settings.value(DETECTION_SETTINGS_VERSION_KEY, 0, type=int)
    if version >= DETECTION_SETTINGS_VERSION:
        return

    confidence = settings.value(
        "vrn/ai_confidence",
        confidence_percent_for_sensitivity_index(DEFAULT_SENSITIVITY_INDEX),
        type=int,
    )

    # Earlier builds inverted Low and High sensitivity while storing only confidence.
    if confidence <= 50:
        confidence = confidence_percent_for_sensitivity_index(0)
    elif confidence >= 60:
        confidence = confidence_percent_for_sensitivity_index(2)

    settings.setValue("vrn/ai_confidence", confidence)
    settings.setValue(DETECTION_SETTINGS_VERSION_KEY, DETECTION_SETTINGS_VERSION)
    settings.sync()


def should_sample_detection_frame(
    frame_number: int,
    frame_stride: int,
    total_frames: int | None = None,
) -> bool:
    if frame_number <= 0:
        return False
    if frame_number == 1:
        return True
    if total_frames is not None and total_frames > 0 and frame_number >= total_frames:
        return True

    stride = max(1, int(frame_stride))
    return (frame_number - 1) % stride == 0


def sample_frame_numbers_for_detection(
    frame_count: int | float,
    fps: float,
    sample_seconds: float,
    max_frames: int,
) -> list[int]:
    total_frames = max(0, int(frame_count or 0))
    if total_frames <= 0:
        return [0]

    step = max(1, int(round(float(fps or 0.0) * float(sample_seconds or 0.0))))
    frames = list(range(0, total_frames, step))
    last_frame = total_frames - 1
    if not frames or frames[-1] != last_frame:
        frames.append(last_frame)

    limit = max(1, int(max_frames or 1))
    if len(frames) > limit:
        if limit == 1:
            frames = [0]
        else:
            frames = [
                int(round(index * last_frame / (limit - 1)))
                for index in range(limit)
            ]

    return sorted(set(max(0, min(last_frame, frame)) for frame in frames))
