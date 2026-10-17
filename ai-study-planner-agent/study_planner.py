"""Small planning workflow: validate inputs, ask OpenRouter, validate its JSON."""

from __future__ import annotations

import json
import os
import re
from typing import Any

from dotenv import load_dotenv

load_dotenv()

SKILL_LEVELS = ("Beginner", "Intermediate", "Advanced")


class PlannerError(Exception):
    """An actionable, safe-to-display error from the planning workflow."""


def validate_inputs(
    topic: str, skill_level: str, hours_per_day: float, number_of_days: int, goal: str = ""
) -> dict[str, Any]:
    topic = topic.strip()
    goal = goal.strip()
    if not topic:
        raise ValueError("Enter a subject or topic to study.")
    if len(topic) > 160:
        raise ValueError("Keep the subject or topic under 160 characters.")
    if skill_level not in SKILL_LEVELS:
        raise ValueError("Choose Beginner, Intermediate, or Advanced.")
    if not 0.25 <= float(hours_per_day) <= 12:
        raise ValueError("Daily study time must be between 0.25 and 12 hours.")
    try:
        parsed_days = int(number_of_days)
        whole_number_of_days = float(number_of_days) == parsed_days
    except (TypeError, ValueError, OverflowError):
        whole_number_of_days = False
        parsed_days = 0
    if not whole_number_of_days or not 1 <= parsed_days <= 60:
        raise ValueError("Choose between 1 and 60 study days.")
    if len(goal) > 500:
        raise ValueError("Keep the learning goal under 500 characters.")
    return {
        "topic": topic,
        "skill_level": skill_level,
        "hours_per_day": float(hours_per_day),
        "number_of_days": parsed_days,
        "goal": goal,
    }


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PlannerError(f"The AI response is missing a valid '{field}' value. Please try again.")
    return value.strip()


def _string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise PlannerError(f"The AI response is missing a non-empty '{field}' list. Please try again.")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise PlannerError(f"The AI response contains an invalid item in '{field}'. Please try again.")
    return [item.strip() for item in value]


def validate_plan(data: Any, expected_days: int) -> dict[str, Any]:
    """Validate the model's response shape before any part is rendered."""
    if not isinstance(data, dict):
        raise PlannerError("The AI returned a response that was not a JSON object. Please try again.")
    objective = _required_text(data.get("overall_objective"), "overall_objective")
    days = data.get("days")
    if not isinstance(days, list) or len(days) != expected_days:
        raise PlannerError("The AI plan did not contain the requested number of days. Please try again.")
    clean_days = []
    for index, day in enumerate(days, start=1):
        if not isinstance(day, dict):
            raise PlannerError(f"Day {index} in the AI response is invalid. Please try again.")
        day_number = day.get("day")
        if not isinstance(day_number, int) or isinstance(day_number, bool) or day_number != index:
            raise PlannerError("The AI plan has invalid day numbers. Please try again.")
        clean_days.append({
            "day": day_number,
            "topic": _required_text(day.get("topic"), "topic"),
            "tasks": _string_list(day.get("tasks"), "tasks"),
            "exercises": _string_list(day.get("exercises"), "exercises"),
            "expected_outcome": _required_text(day.get("expected_outcome"), "expected_outcome"),
            "revision": _string_list(day.get("revision"), "revision"),
        })
    return {"overall_objective": objective, "days": clean_days}


def parse_plan_response(content: Any, expected_days: int) -> dict[str, Any]:
    if not isinstance(content, str) or not content.strip():
        raise PlannerError("The AI returned an empty response. Please try again.")
    text = content.strip()
    # Models sometimes add prose or a markdown fence despite JSON response mode.
    candidates = [text]
    candidates.extend(
        match.group(1)
        for match in re.finditer(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.IGNORECASE | re.DOTALL)
    )
    candidates.extend(_json_objects_in_text(text))
    data = None
    for candidate in candidates:
        try:
            data = json.loads(candidate.strip())
            break
        except json.JSONDecodeError:
            continue
    if data is None:
        raise PlannerError(
            "The AI response was incomplete or not valid JSON. Try fewer study days and generate the plan again."
        )
    return validate_plan(data, expected_days)


def _json_objects_in_text(text: str) -> list[str]:
    """Find complete top-level JSON objects embedded in explanatory text."""
    results = []
    start = None
    depth = 0
    in_string = False
    escaped = False
    for index, char in enumerate(text):
        if start is None:
            if char == "{":
                start = index
                depth = 1
            continue
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                results.append(text[start : index + 1])
                start = None
    return results


def friendly_api_error(error: Exception) -> str:
    """Map SDK/network failures to useful messages without exposing raw errors or keys."""
    status = getattr(error, "status_code", None) or getattr(error, "status", None)
    try:
        status = int(status)
    except (TypeError, ValueError):
        status = None
    message = str(error).lower()
    if status == 401 or "unauthorized" in message or "invalid api key" in message:
        return "OpenRouter rejected the API key. Check OPENROUTER_API_KEY and try again."
    if status == 402 or "insufficient" in message or "credits" in message or "payment required" in message:
        return "OpenRouter reports insufficient credits for this request. Check your account balance and model pricing."
    if status == 404 or "model not found" in message or "no endpoints found" in message:
        return "That model ID was not found or is unavailable to your account. Check OPENROUTER_MODEL against the model catalog."
    if status == 429 or "rate limit" in message or "too many requests" in message:
        return "OpenRouter rate limit reached. Wait a little, then try again."
    if any(word in message for word in ("connecterror", "timeoutexception", "network", "connection", "timed out")):
        return "Could not reach OpenRouter. Check your internet connection and try again."
    if status in (400, 422):
        return "OpenRouter could not accept this request. Confirm the model supports chat completions and try again."
    return "OpenRouter could not generate a plan right now. Please try again later."


def generate_study_plan(inputs: dict[str, Any], client: Any = None) -> dict[str, Any]:
    """Call the documented OpenRouter Python SDK, then validate its JSON result."""
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    model = os.getenv("OPENROUTER_MODEL", "").strip()
    if not api_key:
        raise PlannerError("OpenRouter API key is missing. Add OPENROUTER_API_KEY to your .env file and restart Streamlit.")
    if not model:
        raise PlannerError("No model is configured. Set OPENROUTER_MODEL to an available model ID in your .env file.")

    safe_inputs = validate_inputs(
        inputs["topic"], inputs["skill_level"], inputs["hours_per_day"], inputs["number_of_days"], inputs.get("goal", "")
    )
    prompt = {
        "topic": safe_inputs["topic"],
        "skill_level": safe_inputs["skill_level"],
        "hours_per_day": safe_inputs["hours_per_day"],
        "number_of_days": safe_inputs["number_of_days"],
        "learning_goal": safe_inputs["goal"] or "Choose a sensible goal for this learner.",
    }
    messages = [
        {"role": "system", "content": (
            "You are a careful study planning assistant. Return only a JSON object with keys "
            "overall_objective (string) and days (array). Each day must have day (1-based integer), "
            "topic (string), tasks (array with exactly 2 short actionable strings), exercises (array with "
            "exactly 1 short practice string), expected_outcome (short string), and revision (array with exactly "
            "1 short review string). Keep every activity under 18 words and the topic/outcome under 20 words. "
            "Make the plan practical for the requested daily hours and skill level. Do not add markdown or commentary."
        )},
        {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
    ]
    try:
        if client is None:
            from openrouter import OpenRouter
            with OpenRouter(api_key=api_key, x_open_router_title="AI Study Planner Agent") as openrouter:
                response = openrouter.chat.send(
                    model=model,
                    messages=messages,
                    stream=False,
                    temperature=0.3,
                    max_completion_tokens=max(3500, safe_inputs["number_of_days"] * 220),
                    response_format=_study_plan_response_format(),
                    provider={"require_parameters": True},
                )
        else:
            response = client.chat.send(
                model=model,
                messages=messages,
                stream=False,
                temperature=0.3,
                max_completion_tokens=max(3500, safe_inputs["number_of_days"] * 220),
                response_format=_study_plan_response_format(),
                provider={"require_parameters": True},
            )
    except Exception as exc:
        raise PlannerError(friendly_api_error(exc)) from exc

    try:
        content = response.choices[0].message.content
        finish_reason = response.choices[0].finish_reason
    except (AttributeError, IndexError, TypeError, KeyError) as exc:
        raise PlannerError("OpenRouter returned an unexpected response. Please try again.") from exc
    if str(finish_reason).lower() in ("length", "finishreason.length"):
        raise PlannerError(
            "The model reached its response limit before finishing the plan. Try fewer study days and submit again."
        )
    return parse_plan_response(content, safe_inputs["number_of_days"])


def _study_plan_response_format() -> dict[str, Any]:
    """Use OpenRouter's JSON Schema response mode to constrain model output."""
    day_schema = {
        "type": "object",
        "properties": {
            "day": {"type": "integer"},
            "topic": {"type": "string"},
            "tasks": {"type": "array", "items": {"type": "string"}},
            "exercises": {"type": "array", "items": {"type": "string"}},
            "expected_outcome": {"type": "string"},
            "revision": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["day", "topic", "tasks", "exercises", "expected_outcome", "revision"],
        "additionalProperties": False,
    }
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "study_plan",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "overall_objective": {"type": "string"},
                    "days": {"type": "array", "items": day_schema},
                },
                "required": ["overall_objective", "days"],
                "additionalProperties": False,
            },
        },
    }


def calculate_progress(completed: set[str] | list[str], total: int) -> float:
    """Return progress from 0.0 to 1.0; an empty plan has zero progress."""
    if total <= 0:
        return 0.0
    return min(max(len(completed), 0), total) / total


def set_task_completion(completed: set[str], task_id: str, is_complete: bool) -> set[str]:
    """Return a copy of completion state with one activity checked or unchecked."""
    updated = set(completed)
    if is_complete:
        updated.add(task_id)
    else:
        updated.discard(task_id)
    return updated
