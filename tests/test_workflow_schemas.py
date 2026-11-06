from __future__ import annotations

import datetime

import pytest

from workflow_schemas import WORKFLOW_SCHEMAS, preference_definitions, public_workflow_schemas, qsettings_values, validate_preference_values, validate_workflow_options


EXPECTED_WORKFLOWS = {
    "import-files",
    "timestamp",
    "remove-audio",
    "clip-order",
    "video-minutes",
    "trim",
    "transcode",
    "merge",
}


def test_schema_covers_every_current_vts_module_with_unique_option_keys():
    assert set(WORKFLOW_SCHEMAS) == EXPECTED_WORKFLOWS
    for action, workflow in WORKFLOW_SCHEMAS.items():
        keys = [option["key"] for option in workflow["options"]]
        assert len(keys) == len(set(keys)), action
        assert workflow["title"]
        assert workflow["category"]
        assert workflow["symbol"]
        assert workflow["launch_label"]


def test_every_workflow_default_payload_validates():
    for action, workflow in WORKFLOW_SCHEMAS.items():
        required_values = {
            option["key"]: "/tmp"
            for option in workflow["options"]
            if option["required"] and option["kind"] == "path"
        }
        values = validate_workflow_options(action, required_values)
        assert set(values) == {
            option["key"] for option in workflow["options"]
        }


def test_required_path_and_date_validation():
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        validate_workflow_options(
            "import-files",
            {
                "import_date": "08/14/2026",
                "destination": "/tmp/archive",
            },
        )

    values = validate_workflow_options(
        "import-files",
        {
            "import_date": datetime.date(2026, 8, 14).isoformat(),
            "destination": "/tmp/archive",
        },
    )
    assert values["skip_duplicates"] is True


def test_choice_number_and_unknown_option_validation():
    with pytest.raises(ValueError, match="Unsupported value for quality"):
        validate_workflow_options("transcode", {"quality": "lossless-ish"})
    with pytest.raises(ValueError, match="at most 100"):
        validate_workflow_options("transcode", {"max_size_gb": 101})
    with pytest.raises(ValueError, match="Unsupported trim option"):
        validate_workflow_options("trim", {"start_processing": True})


def test_public_schema_hides_python_preference_keys():
    workflows = public_workflow_schemas()
    assert {workflow["id"] for workflow in workflows} == EXPECTED_WORKFLOWS
    assert all(
        "qsettings_key" not in option
        for workflow in workflows
        for option in workflow["options"]
    )


def test_public_schema_separates_settings_defaults_from_job_controls():
    workflows = {workflow["id"]: workflow for workflow in public_workflow_schemas()}
    timestamp = {option["key"]: option for option in workflows["timestamp"]["options"]}

    assert workflows["trim"]["execution_mode"] == "staged_native"
    assert timestamp["use_hwaccel"]["placement"] == "settings"
    assert timestamp["use_hwaccel"]["settings_section"] == "Encoding & Performance"
    assert timestamp["use_hwaccel"]["preference_id"] == "use_hwaccel"
    delivery = {option["key"]: option for option in workflows["transcode"]["options"]}
    assert delivery["size_strategy"]["placement"] == "workflow"


def test_preference_definitions_are_deduplicated_and_allowlisted():
    definitions = preference_definitions()

    assert definitions["use_hwaccel"]["qsettings_key"] == "use_hwaccel"
    assert definitions["date_format"]["kind"] == "choice"
    assert validate_preference_values({"use_hwaccel": False}) == {"use_hwaccel": False}
    with pytest.raises(ValueError, match="Unsupported preference"):
        validate_preference_values({"shell.command": "anything"})
