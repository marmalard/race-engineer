"""First-run Setup page + key rotation (B2, spec 4). Display only --
the .env contract lives in core/config/env_setup.

Both Test buttons are thin I/O over real services and are non-blocking:
a failed test warns, saving is always allowed (offline install).
Convention-untested (Streamlit rendering + network I/O).
"""

from __future__ import annotations

import streamlit as st

from core.config.env_setup import (
    DEFAULTS,
    is_complete,
    read_env,
    write_env,
)
from core.update.version import get_version

_FIRST_RUN_INTRO = (
    "Welcome — three keys and you're racing. Your **iRacing login** lets "
    "the engineer pull official results and field data; your **Anthropic "
    "API key** powers the AI debriefs (get one at console.anthropic.com). "
    "Everything is stored only on this machine, in a local `.env` file."
)

_EDIT_INTRO = (
    "Update your saved keys here. Changes take effect immediately — no "
    "restart needed."
)


def _test_anthropic_key(key: str) -> str | None:
    """None on success, error text on failure. A models.list() call --
    cheap, no tokens consumed."""
    try:
        import anthropic

        anthropic.Anthropic(api_key=key).models.list()
        return None
    except Exception as exc:  # noqa: BLE001 -- shown to the user, never raised
        return str(exc)


def _test_iracing_login(username: str, password: str) -> str | None:
    """None on success, error text on failure (OAuth token fetch)."""
    client_id = DEFAULTS.get("IRACING_CLIENT_ID", "")
    client_secret = DEFAULTS.get("IRACING_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        return (
            "This build has no iRacing app credential baked in — "
            "set IRACING_CLIENT_ID / IRACING_CLIENT_SECRET in .env."
        )
    try:
        from core.benchmark.iracing_api import LiveIRacingAPI

        with LiveIRacingAPI(client_id, client_secret, username, password) as api:
            api.verify_login()
        return None
    except Exception as exc:  # noqa: BLE001 -- shown to the user, never raised
        return str(exc)


def render_setup_page() -> None:
    """Render the first-run Setup page or the post-setup key rotation UI."""
    first_run = not is_complete()
    st.header("Setup" if first_run else "Settings & Keys")
    st.markdown(_FIRST_RUN_INTRO if first_run else _EDIT_INTRO)

    existing = read_env()
    username = st.text_input(
        "iRacing username (email)",
        value=existing.get("IRACING_USERNAME", ""),
    )
    password = st.text_input(
        "iRacing password",
        value=existing.get("IRACING_PASSWORD", ""),
        type="password",
    )
    if st.button("Test iRacing login"):
        if not (username and password):
            st.warning("Enter your iRacing username and password first.")
        else:
            err = _test_iracing_login(username, password)
            if err is None:
                st.success("iRacing login works.")
            else:
                st.warning(f"iRacing login failed — you can still save. {err}")

    anthropic_key = st.text_input(
        "Anthropic API key",
        value=existing.get("ANTHROPIC_API_KEY", ""),
        type="password",
    )
    if st.button("Test Anthropic key"):
        if not anthropic_key:
            st.warning("Enter your Anthropic API key first.")
        else:
            err = _test_anthropic_key(anthropic_key)
            if err is None:
                st.success("Anthropic key works.")
            else:
                st.warning(f"Key test failed — you can still save. {err}")

    st.divider()
    if st.button("Save and start", type="primary"):
        write_env({
            "IRACING_USERNAME": username,
            "IRACING_PASSWORD": password,
            "ANTHROPIC_API_KEY": anthropic_key,
        })
        st.success("Saved.")
        st.rerun()  # first run: routing now sees a complete .env

    st.caption(f"Race Engineer v{get_version()}")
