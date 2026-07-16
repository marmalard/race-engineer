"""Theme header helpers must HTML-escape interpolated content.

These render via ``st.markdown(..., unsafe_allow_html=True)`` and receive
values derived from uploaded telemetry files (track/car/driver names from the
embedded IBT YAML). A crafted name must not be able to inject live HTML.
Regression guard for the stored-XSS fix in ``header_strip``/``section_header``.
"""

import app.components.theme as theme


def _capture(monkeypatch):
    """Patch st.markdown to record the HTML strings the helpers emit."""
    calls: list[str] = []
    monkeypatch.setattr(theme.st, "markdown", lambda body, **kw: calls.append(body))
    return calls


XSS = '<img src=x onerror="alert(document.cookie)">'


class TestHeaderStrip:
    def test_escapes_payload(self, monkeypatch):
        calls = _capture(monkeypatch)
        theme.header_strip([XSS, "clean"])
        html_out = calls[0]
        assert "<img" not in html_out
        assert "onerror" not in html_out or "&lt;img" in html_out
        assert "&lt;img src=x onerror=" in html_out

    def test_bold_wraps_escaped_text_only(self, monkeypatch):
        calls = _capture(monkeypatch)
        theme.header_strip([XSS, "car"], bold=(0,))
        html_out = calls[0]
        # The <b> structure the app intends is present...
        assert "<b>&lt;img" in html_out
        # ...but the payload itself is inert (escaped).
        assert "<img" not in html_out

    def test_empty_parts_skipped(self, monkeypatch):
        calls = _capture(monkeypatch)
        theme.header_strip(["track", "", "driver"], bold=(2,))
        html_out = calls[0]
        assert "track · <b>driver</b>" in html_out


class TestSectionHeader:
    def test_escapes_title(self, monkeypatch):
        calls = _capture(monkeypatch)
        theme.section_header(XSS)
        html_out = calls[0]
        assert "<img" not in html_out
        assert "&lt;img" in html_out
