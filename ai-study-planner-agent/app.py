"""Streamlit interface for the AI Study Planner Agent."""

import os
import uuid

import streamlit as st
from dotenv import load_dotenv

from email_delivery import (
    InvalidEmailError,
    generate_and_optionally_email,
)
from study_planner import (
    PlannerError,
    calculate_progress,
    set_task_completion,
    validate_inputs,
)

load_dotenv()
st.set_page_config(page_title="AI Study Planner", layout="wide")

st.title("AI Study Planner Agent")
st.write("Create a practical study plan, then track your progress one task at a time.")

# Streamlit session state is this beginner app's temporary progress storage.
if "plan" not in st.session_state:
    st.session_state.plan = None
if "completed" not in st.session_state:
    st.session_state.completed = set()
if "plan_id" not in st.session_state:
    st.session_state.plan_id = None

# These controls sit above the original form so the email field appears immediately;
# the study inputs and Generate button remain in their existing batched form.
email_enabled = st.checkbox(
    "Email me a copy of my study plan",
    value=False,
    key="email_delivery_enabled",
)
email_address = ""
if email_enabled:
    email_address = st.text_input(
        "Email address",
        placeholder="you@example.com",
        key="study_plan_email_address",
    )

with st.form("study_plan_form"):
    topic = st.text_input("Subject or topic", placeholder="e.g. Python fundamentals")
    skill_level = st.selectbox("Current skill level", ["Beginner", "Intermediate", "Advanced"])
    col1, col2 = st.columns(2)
    with col1:
        hours = st.number_input("Available study hours per day", min_value=0.25, max_value=12.0, value=1.0, step=0.25)
    with col2:
        days = st.number_input("Number of study days", min_value=1, max_value=60, value=7, step=1)
    goal = st.text_area("Learning goal (optional)", placeholder="What would you like to be able to do?")
    submitted = st.form_submit_button("Generate my study plan", type="primary")

if submitted:
    try:
        inputs = validate_inputs(topic, skill_level, hours, days, goal)
        with st.spinner("Building your personalized plan..."):
            plan, email_warning = generate_and_optionally_email(
                inputs,
                email_enabled=email_enabled,
                email_address=email_address,
            )
        st.session_state.plan = plan
        st.session_state.completed = set()
        # A fresh ID ensures a regenerated identical plan starts with fresh checkboxes.
        st.session_state.plan_id = uuid.uuid4().hex[:12]
        if email_warning:
            st.warning(f"Your plan was generated successfully and is shown below, but the email could not be sent: {email_warning}")
        elif email_enabled:
            st.success("Your plan was generated and emailed successfully.")
        else:
            st.success("Your plan is ready.")
    except InvalidEmailError as exc:
        st.error(str(exc))
    except ValueError as exc:
        st.error(str(exc))
    except PlannerError as exc:
        st.error(str(exc))

if st.session_state.plan:
    plan = st.session_state.plan
    st.subheader("Your learning objective")
    st.write(plan["overall_objective"])

    all_task_ids = []
    for day in plan["days"]:
        st.markdown(f"### Day {day['day']}: {day['topic']}")
        st.markdown("**Learning tasks**")
        for section, heading in (("tasks", "Task"), ("exercises", "Practice"), ("revision", "Revision")):
            if section != "tasks":
                st.markdown(f"**{heading}**")
            for index, item in enumerate(day[section]):
                task_id = f"{st.session_state.plan_id}-{day['day']}-{section}-{index}"
                all_task_ids.append(task_id)
                checked = st.checkbox(item, key=task_id, value=task_id in st.session_state.completed)
                st.session_state.completed = set_task_completion(
                    st.session_state.completed, task_id, checked
                )
        st.markdown(f"**Expected outcome:** {day['expected_outcome']}")

    total = len(all_task_ids)
    progress = calculate_progress(st.session_state.completed, total)
    st.subheader("Your progress")
    st.progress(progress, text=f"{round(progress * 100)}% complete ({len(st.session_state.completed)} of {total} activities)")

with st.sidebar:
    st.header("Configuration")
    if not os.getenv("OPENROUTER_API_KEY", "").strip():
        st.warning("OPENROUTER_API_KEY is not set.")
    if not os.getenv("OPENROUTER_MODEL", "").strip():
        st.warning("OPENROUTER_MODEL is not set. Choose an available model ID.")
    st.caption("The language model writes the plan. Python validates its structure and calculates progress. Streamlit displays the form and stores checkboxes in this browser session.")
