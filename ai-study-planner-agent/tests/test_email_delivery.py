import smtplib

import pytest

import email_delivery
from email_delivery import (
    EmailDeliveryError,
    InvalidEmailError,
    generate_and_optionally_email,
    send_study_plan_email,
    validate_email_address,
)
from study_planner import PlannerError


def example_inputs():
    return {
        "topic": "Python",
        "skill_level": "Beginner",
        "hours_per_day": 1.5,
        "number_of_days": 1,
        "goal": "Write a small program",
    }


def example_plan():
    return {
        "overall_objective": "Write and explain a small Python program.",
        "days": [{
            "day": 1,
            "topic": "Variables",
            "tasks": ["Read a short lesson", "Summarize the key idea"],
            "exercises": ["Write a small program"],
            "expected_outcome": "Use variables in a basic script.",
            "revision": ["Recall the key ideas without notes"],
        }],
    }


def configured_smtp(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USERNAME", "smtp-user")
    monkeypatch.setenv("SMTP_PASSWORD", "smtp-password")
    monkeypatch.setenv("SMTP_FROM_EMAIL", "planner@example.test")
    monkeypatch.setenv("SMTP_USE_SSL", "false")


class FakeSMTP:
    instances = []

    def __init__(self, host, port, **kwargs):
        self.host = host
        self.port = port
        self.kwargs = kwargs
        self.started_tls = False
        self.logged_in = None
        self.sent_message = None
        self.quit_called = False
        self.__class__.instances.append(self)

    def ehlo(self):
        return 250, b"ok"

    def starttls(self, context):
        self.started_tls = context is not None
        return 220, b"ready"

    def login(self, username, password):
        self.logged_in = (username, password)

    def send_message(self, message):
        self.sent_message = message
        return {}

    def quit(self):
        self.quit_called = True
        return 221, b"bye"


def test_email_disabled_generates_once_and_never_sends():
    calls = {"plan": 0, "email": 0}
    plan = example_plan()

    def planner(inputs):
        calls["plan"] += 1
        return plan

    def sender(*args):
        calls["email"] += 1

    returned_plan, warning = generate_and_optionally_email(
        example_inputs(), False, planner=planner, email_sender=sender
    )
    assert returned_plan is plan
    assert warning is None
    assert calls == {"plan": 1, "email": 0}


def test_enabled_email_sends_the_same_plan_after_single_generation():
    calls = {"plan": 0, "email": 0}
    plan = example_plan()
    received = {}

    def planner(inputs):
        calls["plan"] += 1
        return plan

    def sender(address, inputs, emailed_plan):
        calls["email"] += 1
        received.update(address=address, inputs=inputs, plan=emailed_plan)

    returned_plan, warning = generate_and_optionally_email(
        example_inputs(), True, " learner@example.com ", planner=planner, email_sender=sender
    )
    assert returned_plan is plan
    assert warning is None
    assert calls == {"plan": 1, "email": 1}
    assert received == {"address": "learner@example.com", "inputs": example_inputs(), "plan": plan}


def test_invalid_email_stops_before_plan_generation_or_email():
    calls = {"plan": 0, "email": 0}

    def planner(inputs):
        calls["plan"] += 1
        return example_plan()

    def sender(*args):
        calls["email"] += 1

    with pytest.raises(InvalidEmailError, match="valid email"):
        generate_and_optionally_email(
            example_inputs(), True, "not-an-email", planner=planner, email_sender=sender
        )
    assert calls == {"plan": 0, "email": 0}


def test_generation_failure_never_sends_email():
    calls = {"plan": 0, "email": 0}

    def planner(inputs):
        calls["plan"] += 1
        raise PlannerError("model unavailable")

    def sender(*args):
        calls["email"] += 1

    with pytest.raises(PlannerError, match="model unavailable"):
        generate_and_optionally_email(
            example_inputs(), True, "learner@example.com", planner=planner, email_sender=sender
        )
    assert calls == {"plan": 1, "email": 0}


def test_missing_smtp_configuration_returns_plan_and_warning(monkeypatch):
    for name in email_delivery._REQUIRED_SETTINGS:
        monkeypatch.delenv(name, raising=False)
    plan = example_plan()
    calls = []

    def planner(inputs):
        calls.append("plan")
        return plan

    returned_plan, warning = generate_and_optionally_email(
        example_inputs(), True, "learner@example.com", planner=planner
    )
    assert returned_plan is plan
    assert "SMTP_HOST" in warning
    assert "SMTP_PASSWORD" in warning
    assert calls == ["plan"]


def test_smtp_sends_professional_plain_text_with_existing_plan(monkeypatch):
    configured_smtp(monkeypatch)
    FakeSMTP.instances = []
    monkeypatch.setattr(email_delivery.smtplib, "SMTP", FakeSMTP)
    inputs, plan = example_inputs(), example_plan()

    send_study_plan_email("learner@example.com", inputs, plan)

    smtp = FakeSMTP.instances[0]
    assert smtp.started_tls
    assert smtp.logged_in == ("smtp-user", "smtp-password")
    assert smtp.sent_message["Subject"] == "Your Personalized AI Study Plan"
    assert smtp.sent_message["To"] == "learner@example.com"
    assert smtp.sent_message.get_content_type() == "text/plain"
    body = smtp.sent_message.get_content()
    for expected in ("Python", "Beginner", "1 study day", "Variables", "Read a short lesson", "Write a small program", "Use variables in a basic script"):
        assert expected in body
    assert smtp.quit_called


def test_smtp_authentication_failure_is_safe_and_keeps_generated_plan(monkeypatch):
    configured_smtp(monkeypatch)

    class AuthFailureSMTP(FakeSMTP):
        def login(self, username, password):
            raise smtplib.SMTPAuthenticationError(535, b"sensitive provider detail")

    monkeypatch.setattr(email_delivery.smtplib, "SMTP", AuthFailureSMTP)
    plan = example_plan()
    returned_plan, warning = generate_and_optionally_email(
        example_inputs(), True, "learner@example.com", planner=lambda inputs: plan
    )
    assert returned_plan is plan
    assert "rejected the username or password" in warning
    assert "sensitive provider detail" not in warning


def test_recipient_rejection_is_reported_without_provider_details(monkeypatch):
    configured_smtp(monkeypatch)

    class RecipientFailureSMTP(FakeSMTP):
        def send_message(self, message):
            return {"learner@example.com": (550, b"private server response")}

    monkeypatch.setattr(email_delivery.smtplib, "SMTP", RecipientFailureSMTP)
    with pytest.raises(EmailDeliveryError, match="rejected the recipient") as error:
        send_study_plan_email("learner@example.com", example_inputs(), example_plan())
    assert "private server response" not in str(error.value)


@pytest.mark.parametrize("address", ["", "x", "x@", "a..b@example.com", ".a@example.com", "a@example"])
def test_invalid_addresses_are_rejected(address):
    with pytest.raises(InvalidEmailError):
        validate_email_address(address)


def test_valid_email_is_trimmed():
    assert validate_email_address(" learner@example.com ") == "learner@example.com"
