import json
from types import SimpleNamespace

import pytest

import study_planner
from study_planner import (
    PlannerError,
    calculate_progress,
    friendly_api_error,
    parse_plan_response,
    set_task_completion,
    validate_inputs,
)


def valid_plan(days=2):
    return {
        "overall_objective": "Build a foundation in Python.",
        "days": [
            {
                "day": i,
                "topic": f"Python topic {i}",
                "tasks": ["Read a short lesson", "Summarize the key idea"],
                "exercises": ["Write a small program"],
                "expected_outcome": "Explain and use the concept.",
                "revision": ["Recall key ideas without notes"],
            }
            for i in range(1, days + 1)
        ],
    }


def test_validate_inputs_trims_and_accepts_valid_values():
    result = validate_inputs("  Python ", "Beginner", 1.5, 5, "  Build a game  ")
    assert result["topic"] == "Python"
    assert result["goal"] == "Build a game"


@pytest.mark.parametrize("values", [
    ("", "Beginner", 1, 5, ""),
    ("Math", "Expert", 1, 5, ""),
    ("Math", "Beginner", 0, 5, ""),
    ("Math", "Beginner", 1, 0, ""),
    ("Math", "Beginner", 1, 1.5, ""),
])
def test_validate_inputs_rejects_invalid_values(values):
    with pytest.raises(ValueError):
        validate_inputs(*values)


def test_parse_and_validate_structured_plan():
    parsed = parse_plan_response(json.dumps(valid_plan()), 2)
    assert len(parsed["days"]) == 2
    assert parsed["days"][0]["exercises"] == ["Write a small program"]


def test_parse_plan_accepts_fenced_json():
    content = "```json\n" + json.dumps(valid_plan(1)) + "\n```"
    assert len(parse_plan_response(content, 1)["days"]) == 1
    wrapped = "Here is the plan:\n" + json.dumps(valid_plan(1)) + "\nEnjoy!"
    assert len(parse_plan_response(wrapped, 1)["days"]) == 1


def test_parse_plan_rejects_malformed_or_wrong_length_response():
    with pytest.raises(PlannerError, match="valid JSON"):
        parse_plan_response("not json", 1)
    with pytest.raises(PlannerError, match="requested number of days"):
        parse_plan_response(json.dumps(valid_plan(2)), 1)
    with pytest.raises(PlannerError, match="empty response"):
        parse_plan_response("   ", 1)


def test_parse_plan_rejects_missing_action_items():
    plan = valid_plan(1)
    plan["days"][0]["tasks"] = []
    with pytest.raises(PlannerError, match="tasks"):
        parse_plan_response(json.dumps(plan), 1)


def test_progress_calculation():
    assert calculate_progress({"a", "b"}, 4) == 0.5
    assert calculate_progress(set(), 0) == 0
    assert calculate_progress({"a", "b", "c"}, 2) == 1


def test_task_completion_can_be_checked_and_unchecked():
    checked = set_task_completion(set(), "day-1-task-1", True)
    assert checked == {"day-1-task-1"}
    unchecked = set_task_completion(checked, "day-1-task-1", False)
    assert unchecked == set()


@pytest.mark.parametrize(("status", "expected"), [
    (401, "rejected the API key"),
    (402, "insufficient credits"),
    (404, "model ID"),
    (429, "rate limit"),
    (503, "could not generate a plan"),
])
def test_api_failures_have_friendly_messages(status, expected):
    error = RuntimeError("request failed")
    error.status_code = status
    assert expected.lower() in friendly_api_error(error).lower()


def test_network_failure_message():
    assert "internet connection" in friendly_api_error(RuntimeError("ConnectError: down"))


class FakeChat:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def send(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


class FakeClient:
    def __init__(self, chat):
        self.chat = chat


def fake_response(content):
    return SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content=content), finish_reason="stop"
    )])


def test_generate_plan_uses_mocked_sdk_response(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "test/model")
    chat = FakeChat(response=fake_response(json.dumps(valid_plan(1))))
    plan = study_planner.generate_study_plan(
        {"topic": "Python", "skill_level": "Beginner", "hours_per_day": 1, "number_of_days": 1},
        client=FakeClient(chat),
    )
    assert plan["days"][0]["day"] == 1
    assert chat.calls[0]["model"] == "test/model"
    assert chat.calls[0]["response_format"]["type"] == "json_schema"
    assert chat.calls[0]["provider"] == {"require_parameters": True}


def test_generate_plan_handles_sdk_failure_without_leaking_raw_error(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "test/model")
    chat = FakeChat(error=RuntimeError("429 rate limit secret-detail"))
    with pytest.raises(PlannerError, match="rate limit") as error:
        study_planner.generate_study_plan(
            {"topic": "Python", "skill_level": "Beginner", "hours_per_day": 1, "number_of_days": 1},
            client=FakeClient(chat),
        )
    assert "secret-detail" not in str(error.value)


def test_generate_plan_explains_truncated_model_response(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "test/model")
    response = fake_response(json.dumps(valid_plan(1)))
    response.choices[0].finish_reason = "length"
    with pytest.raises(PlannerError, match="response limit"):
        study_planner.generate_study_plan(
            {"topic": "Python", "skill_level": "Beginner", "hours_per_day": 1, "number_of_days": 1},
            client=FakeClient(FakeChat(response=response)),
        )


def test_generate_plan_explains_missing_configuration(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    with pytest.raises(PlannerError, match="API key is missing"):
        study_planner.generate_study_plan({})


def test_generate_plan_explains_missing_model(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    with pytest.raises(PlannerError, match="No model is configured"):
        study_planner.generate_study_plan({})
