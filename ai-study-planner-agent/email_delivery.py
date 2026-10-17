"""Optional plain-text SMTP delivery for an already-generated study plan."""

from __future__ import annotations

import os
import re
import smtplib
import ssl
from email.message import EmailMessage
from typing import Any, Callable

from study_planner import generate_study_plan


class InvalidEmailError(ValueError):
    """The requested recipient address is not a valid email address."""


class EmailDeliveryError(Exception):
    """A safe-to-display SMTP configuration or delivery problem."""


_ADDRESS_RE = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
)
_REQUIRED_SETTINGS = (
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_USERNAME",
    "SMTP_PASSWORD",
    "SMTP_FROM_EMAIL",
)


def validate_email_address(address: str) -> str:
    """Validate and normalize a basic internet email address before model use."""
    if not isinstance(address, str):
        raise InvalidEmailError("Enter a valid email address.")
    normalized = address.strip()
    if len(normalized) > 254 or not _ADDRESS_RE.fullmatch(normalized):
        raise InvalidEmailError("Enter a valid email address.")
    local_part = normalized.split("@", 1)[0]
    if local_part.startswith(".") or local_part.endswith(".") or ".." in local_part:
        raise InvalidEmailError("Enter a valid email address.")
    return normalized


def _smtp_settings() -> dict[str, Any]:
    settings = {
        name: (os.getenv(name, "") if name == "SMTP_PASSWORD" else os.getenv(name, "").strip())
        for name in _REQUIRED_SETTINGS
    }
    missing = [name for name, value in settings.items() if not value.strip()]
    if missing:
        raise EmailDeliveryError(
            "Email was not sent because SMTP configuration is missing: " + ", ".join(missing) + "."
        )
    try:
        settings["port"] = int(settings["SMTP_PORT"])
    except ValueError as exc:
        raise EmailDeliveryError("Email was not sent because SMTP_PORT must be a number.") from exc
    if not 1 <= settings["port"] <= 65535:
        raise EmailDeliveryError("Email was not sent because SMTP_PORT must be between 1 and 65535.")
    use_ssl = os.getenv("SMTP_USE_SSL", "false").strip().lower()
    if use_ssl not in ("true", "false"):
        raise EmailDeliveryError("Email was not sent because SMTP_USE_SSL must be true or false.")
    settings["use_ssl"] = use_ssl == "true"
    try:
        settings["SMTP_FROM_EMAIL"] = validate_email_address(settings["SMTP_FROM_EMAIL"])
    except InvalidEmailError as exc:
        raise EmailDeliveryError("Email was not sent because SMTP_FROM_EMAIL is not a valid email address.") from exc
    return settings


def format_plan_email(inputs: dict[str, Any], plan: dict[str, Any]) -> str:
    """Render the exact validated plan as readable plain text without truncation."""
    day_count = inputs["number_of_days"]
    duration = f"{day_count} study day" if day_count == 1 else f"{day_count} study days"
    lines = [
        "Your Personalized AI Study Plan",
        "=" * 32,
        f"Subject: {inputs['topic']}",
        f"Skill level: {inputs['skill_level']}",
        f"Duration: {duration}",
        f"Study time: {inputs['hours_per_day']:g} hours per day",
        "",
        "Overall learning objective",
        plan["overall_objective"],
    ]
    for day in plan["days"]:
        lines.extend(["", f"DAY {day['day']}: {day['topic']}", "-" * 40, "Tasks:"])
        lines.extend(f"  - {item}" for item in day["tasks"])
        lines.append("Practice exercises:")
        lines.extend(f"  - {item}" for item in day["exercises"])
        lines.append(f"Expected outcome: {day['expected_outcome']}")
        lines.append("Revision:")
        lines.extend(f"  - {item}" for item in day["revision"])
    return "\n".join(lines)


def send_study_plan_email(
    recipient: str,
    inputs: dict[str, Any],
    plan: dict[str, Any],
) -> None:
    """Send one plain-text copy over SMTP using STARTTLS or implicit TLS."""
    recipient = validate_email_address(recipient)
    settings = _smtp_settings()
    message = EmailMessage()
    message["Subject"] = "Your Personalized AI Study Plan"
    message["From"] = settings["SMTP_FROM_EMAIL"]
    message["To"] = recipient
    message.set_content(format_plan_email(inputs, plan))

    connection = None
    try:
        tls_context = ssl.create_default_context()
        if settings["use_ssl"]:
            connection = smtplib.SMTP_SSL(
                settings["SMTP_HOST"], settings["port"], timeout=20, context=tls_context
            )
        else:
            connection = smtplib.SMTP(settings["SMTP_HOST"], settings["port"], timeout=20)
            connection.ehlo()
            connection.starttls(context=tls_context)
            connection.ehlo()
        connection.login(settings["SMTP_USERNAME"], settings["SMTP_PASSWORD"])
        refused = connection.send_message(message)
        if refused:
            raise EmailDeliveryError("The email server rejected the recipient address. Check the address and try again.")
    except smtplib.SMTPAuthenticationError as exc:
        raise EmailDeliveryError("Email was not sent because the SMTP server rejected the username or password.") from exc
    except smtplib.SMTPRecipientsRefused as exc:
        temporary_codes = {421, 450, 451, 452, 454}
        if any(response[0] in temporary_codes for response in exc.recipients.values()):
            raise EmailDeliveryError("The email server temporarily refused delivery or is rate limiting requests. Try again later.") from exc
        raise EmailDeliveryError("The email server rejected the recipient address. Check the address and try again.") from exc
    except smtplib.SMTPResponseException as exc:
        if 400 <= exc.smtp_code < 500:
            raise EmailDeliveryError("The email server temporarily refused delivery or is rate limiting requests. Try again later.") from exc
        raise EmailDeliveryError("The email server could not send the message. Check the SMTP settings and try again.") from exc
    except (smtplib.SMTPException, ssl.SSLError, OSError) as exc:
        raise EmailDeliveryError("Could not connect securely to the email server. Check the SMTP settings and try again.") from exc
    finally:
        if connection is not None:
            try:
                connection.quit()
            except Exception:
                pass


def generate_and_optionally_email(
    inputs: dict[str, Any],
    email_enabled: bool,
    email_address: str = "",
    *,
    planner: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    email_sender: Callable[[str, dict[str, Any], dict[str, Any]], None] | None = None,
) -> tuple[dict[str, Any], str | None]:
    """Generate once, then optionally email that same plan; return an email warning if needed."""
    if email_enabled:
        recipient = validate_email_address(email_address)
    else:
        recipient = ""

    make_plan = planner or generate_study_plan
    send_email = email_sender or send_study_plan_email
    plan = make_plan(inputs)
    if not email_enabled:
        return plan, None
    try:
        send_email(recipient, inputs, plan)
    except EmailDeliveryError as exc:
        return plan, str(exc)
    return plan, None
