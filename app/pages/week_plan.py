"""Week Plan page — the scheduled artifact, rendered.

Display only. The watcher generates and refreshes the plan; this page
shows the latest one, its history, and the optional AI delivery. These
sentences inform — nothing here gates.
"""

from dataclasses import asdict
from datetime import date
import json
import os

import streamlit as st

from app.navigation import page_for
from core.weekplan.build import target_week_start
from core.weekplan.render import render_week_plan
from core.weekplan.store import WeekPlanStore


def _current_week_plan(store) -> object | None:
    """The target week's plan, or None (store errors included — the
    page must always render)."""
    try:
        return store.get(target_week_start(date.today()).isoformat())
    except Exception:  # noqa: BLE001
        return None


def render_week_plan_page() -> None:
    st.title("Week Plan")
    st.markdown(
        "Your engineer's plan for the racing week — the race worth "
        "entering and the practice that moves you."
    )

    store = WeekPlanStore()
    plan = _current_week_plan(store)

    if plan is None:
        st.info(
            "No plan yet for this week. The engineer prepares it on "
            "Sunday, before the Tuesday flip — keep the watcher running "
            "and it lands by itself."
        )
    else:
        st.markdown(render_week_plan(plan))
        if not plan.curve_filled and plan.race is not None:
            st.page_link(
                page_for("briefing"),
                label="Watch the field curve build on the Race Briefing "
                      "page",
            )
        st.caption(
            f"Prepared {plan.created_at[:10]}, last updated "
            f"{plan.updated_at[:16].replace('T', ' ')} — it refreshes "
            f"itself as the week's field data arrives."
        )

    # history
    try:
        past = [p for p in store.history()
                if plan is None or p.week_start != plan.week_start]
    except Exception:  # noqa: BLE001
        past = []
    if past:
        with st.expander(f"Past weeks ({len(past)})"):
            for p in past:
                st.markdown(render_week_plan(p))
                st.divider()

    # --- optional AI layer (the briefing page pattern) ---
    if plan is None or not os.environ.get("ANTHROPIC_API_KEY"):
        return
    from core.coaching.synthesizer import Synthesizer

    plan_json = json.dumps(asdict(plan), default=str)
    nar_key = f"weekplan_narrative_{plan.week_start}_{plan.updated_at}"
    if st.button("Engineer's delivery (AI)"):
        synth = Synthesizer(api_key=os.environ["ANTHROPIC_API_KEY"])
        with st.spinner("Your engineer is preparing the delivery..."):
            st.session_state[nar_key] = (
                synth.generate_week_plan_narrative(plan_json)
            )
    narrative = st.session_state.get(nar_key)
    if narrative:
        st.markdown(narrative)
        st.divider()
        history = st.session_state.setdefault("weekplan_chat", [])
        for m in history:
            with st.chat_message(m["role"]):
                st.markdown(m["content"])
        if q := st.chat_input("Ask your engineer about the week..."):
            history.append({"role": "user", "content": q})
            synth = Synthesizer(api_key=os.environ["ANTHROPIC_API_KEY"])
            with st.spinner("..."):
                reply = synth.week_plan_chat(plan_json, narrative,
                                             history)
            history.append({"role": "assistant", "content": reply})
            st.rerun()
