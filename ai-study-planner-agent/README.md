# AI Study Planner Agent

A small, standalone Streamlit app that asks an OpenRouter model for a personalized study plan and lets you track its activities during your browser session.

## What each part does

- **Language model:** the selected model creates the learning plan from your topic, skill level, time, schedule, and goal. It can return imperfect output, so the app does not trust it automatically.
- **Planning logic (`study_planner.py`):** checks the form values, builds the instructions, calls the OpenRouter Python SDK with strict JSON Schema output, parses the response, validates every required field, and calculates progress. This is the simple agent workflow: input, instructions, model, checked result.
- **Application state:** Streamlit session state remembers checked activities while that session is open. It is temporary; there are no accounts or database.
- **User interface (`app.py`):** displays the form, plan, completion boxes, progress bar, and actionable errors.

## Requirements

- Python 3.10 or newer
- An OpenRouter account and API key
- A model ID currently available to your account

The model is deliberately not preselected. Model availability, capabilities, and prices change; choose a current ID from the [OpenRouter model catalog](https://openrouter.ai/models). Choose a model endpoint that supports structured outputs; the app asks OpenRouter to route only to endpoints supporting the requested parameters. Calls may incur charges based on the selected model's input and output token prices and your OpenRouter account settings. Longer plans request a larger completion-token ceiling, so review the model's current pricing and your account limits before generating a plan. This app does not make a credit-balance request.

## Setup (Windows PowerShell)

Run these commands from this project directory (`ai-study-planner-agent`):

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
```

In `.env`, set both values:

```dotenv
OPENROUTER_API_KEY=your_private_key_here
OPENROUTER_MODEL=your_current_model_id_here
```

Get the API key from [OpenRouter Keys](https://openrouter.ai/keys). Pick `OPENROUTER_MODEL` from the [model catalog](https://openrouter.ai/models), copying its model ID. Do not commit `.env`, paste the key into source code, or share it in screenshots. Restart Streamlit after changing `.env`.

## Run tests

```powershell
python -m pytest -q
```

Tests use local fake SDK responses and simulated errors. They do not contact OpenRouter or use credits.

## Launch

```powershell
streamlit run app.py
```

Streamlit prints the local URL (usually `http://localhost:8501`). If the API key or model is missing, the app displays setup guidance and does not choose a fallback model.

## Optional email delivery

The email checkbox is off by default and sits just above the study form so its address field can appear immediately while the form continues batching study inputs. Select **Email me a copy of my study plan** to reveal the address field. The app validates that address before calling OpenRouter. After a plan is generated, it sends that same plan as a plain-text email; it does not call the model a second time. If SMTP is unavailable or delivery fails, the generated plan stays visible and the app shows a warning. Unchecking the option does not read SMTP settings or send email. The form submission runs generation and the optional send once; subsequent checkbox/progress reruns do not repeat either action.

Add SMTP settings to your local `.env` file. The `.env.example` file has empty placeholders:

```dotenv
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=your_smtp_username
SMTP_PASSWORD=your_smtp_password
SMTP_FROM_EMAIL=planner@example.com
SMTP_USE_SSL=false
```

Use the hostname, port, and credentials provided by your email provider. By default the app requires STARTTLS (commonly port 587). Set `SMTP_USE_SSL=true` for implicit TLS (commonly port 465). TLS certificate validation is enabled. The provider must allow SMTP authentication and sending from `SMTP_FROM_EMAIL`. No provider is assumed or preconfigured. Keep `.env` private and restart Streamlit after changing it.

To test email behavior without sending real messages, run `python -m pytest -q`; the SMTP connection and OpenRouter generation are mocked.

## Troubleshooting

- **Missing key/model:** check both variables in `.env`, then restart Streamlit.
- **API key rejected:** verify the key in OpenRouter and ensure it has not been revoked.
- **Model not found/unsupported:** copy the current model ID from the catalog and choose one supporting chat completions and JSON Schema structured outputs.
- **Rate limited:** wait before retrying.
- **Insufficient credits:** check your OpenRouter account balance, model price, and key spending limit.
- **Network error:** check internet access and retry.
- **Incomplete or malformed AI result:** the app reports the issue instead of rendering an invented plan. For long schedules, try fewer study days and generate the plan again.

## Project files

```text
app.py                   Streamlit form, plan display, checkboxes, session progress
study_planner.py         Validation, OpenRouter call, JSON parsing, error mapping
email_delivery.py        Optional email validation, SMTP delivery, plain-text formatting
tests/test_study_planner.py
tests/test_email_delivery.py
requirements.txt
.env.example
.gitignore
```
