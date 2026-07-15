"""In-memory nudge feed + minimal stdlib web display for the live coach.

The live loop pushes each completed lap's coaching block here; a tiny
stdlib HTTP server serves an auto-updating dark page that any browser on
the LAN (e.g. an iPad in the sim room) can open. No third-party deps —
this is the throwaway validation surface before the real HUD (Plan 2).
"""

import json
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class NudgeFeed:
    """Thread-safe ring of recent lap coaching blocks, newest first."""

    def __init__(self, max_entries: int = 20) -> None:
        self.max_entries = max_entries
        self._entries: list[str] = []
        self._lock = threading.Lock()

    def add(self, entry: str) -> None:
        with self._lock:
            self._entries.insert(0, entry)
            del self._entries[self.max_entries:]

    def snapshot(self) -> list[str]:
        with self._lock:
            return list(self._entries)


_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Race Engineer</title>
<style>
  :root { color-scheme: dark; }
  body { margin:0; background:#0d0f12; color:#e8e8e8;
         font-family: -apple-system, system-ui, sans-serif; }
  header { padding:14px 18px; font-weight:600; font-size:15px;
           color:#9aa0a6; border-bottom:1px solid #1d2127;
           position:sticky; top:0; background:#0d0f12; }
  #feed { padding:10px 14px; }
  .lap { background:#15181d; border:1px solid #232831; border-radius:10px;
         padding:12px 14px; margin:10px 0; white-space:pre-wrap;
         font-size:19px; line-height:1.5; }
  .lap:first-child { border-color:#3a4150; background:#191d24; }
  .empty { color:#6b7280; padding:24px 14px; font-size:16px; }
</style>
</head>
<body>
<header>Race Engineer &middot; live coach</header>
<div id="feed"><div class="empty">Waiting for your first lap&hellip;</div></div>
<script>
function esc(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;');}
async function poll(){
  try{
    const r = await fetch('/feed', {cache:'no-store'});
    const d = await r.json();
    if(!d.entries.length) return;
    document.getElementById('feed').innerHTML =
      d.entries.map(e => '<div class="lap">' + esc(e) + '</div>').join('');
  }catch(e){}
}
poll();
setInterval(poll, 2000);
</script>
</body>
</html>
"""


def render_page() -> str:
    """The full HTML page (polls /feed every 2s)."""
    return _PAGE


def _make_handler(feed: NudgeFeed):
    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            # Match the route exactly (an optional query string aside) so
            # paths like /feedback fall through to 404.
            route = self.path.split("?", 1)[0]
            if route == "/feed":
                body = json.dumps({"entries": feed.snapshot()}).encode("utf-8")
                self._respond(200, "application/json", body, no_store=True)
            elif route == "/" or route.startswith("/index"):
                self._respond(
                    200, "text/html; charset=utf-8", render_page().encode("utf-8")
                )
            else:
                self._respond(404, "text/plain; charset=utf-8", b"not found")

        def _respond(
            self, status: int, ctype: str, body: bytes, no_store: bool = False
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            if no_store:
                self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args) -> None:  # silence per-request stderr noise
            pass

    return _Handler


def start_web_display(
    feed: NudgeFeed, host: str = "0.0.0.0", port: int = 8042
) -> ThreadingHTTPServer:
    """Start the feed server in a daemon thread; returns the server.

    Pass port=0 to bind an ephemeral port (read it from
    server.server_address[1]); used by tests.
    """
    server = ThreadingHTTPServer((host, port), _make_handler(feed))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


# --- Radio-transcript formatter (consumer-UX A6b) -------------------------
# One line per session-log event (core/live/session_log.py JSONL). Pure
# formatter — reused by the Toolbox activity feed and, later, the tray
# status view and the iPad feed. Empty string = machinery, don't show.

_ICON_RADIO = "\U0001f399"
_ICON_LAP = "\U0001f3c1"


def _fmt_clock(iso: str | None) -> str:
    """UTC ISO timestamp -> local HH:MM:SS ('--:--:--' when absent)."""
    if not iso:
        return "--:--:--"
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%H:%M:%S")
    except ValueError:
        return "--:--:--"


def _fmt_lap_time(seconds: float) -> str:
    """Seconds -> m:ss.mmm (kept local: core/live must not import
    core/briefing for a 2-line format)."""
    m = int(seconds // 60)
    return f"{m}:{seconds - 60 * m:06.3f}"


def format_transcript_line(event: dict) -> str:
    """One radio-transcript line for a live-session JSONL event."""
    clock = _fmt_clock(event.get("t"))
    kind = event.get("event", "")
    if kind == "connect":
        ref = event.get("reference")
        tail = (
            f"reference {_fmt_lap_time(ref['lap_time'])} loaded"
            if ref
            else "no reference — lap one sets the baseline"
        )
        return (
            f"{clock}  {_ICON_RADIO} On air — {event.get('track', '?')} · "
            f"{event.get('car', '?')} · {tail}"
        )
    if kind == "lap":
        delta = event.get("delta")
        delta_txt = f" ({delta:+.1f}s)" if delta is not None else ""
        dirty_txt = " — track limits, won't count" if event.get("dirty") else ""
        return (
            f"{clock}  {_ICON_LAP} Lap {event.get('lap', '?')} — "
            f"{_fmt_lap_time(event['lap_time'])}{delta_txt}{dirty_txt}"
        )
    if kind == "baseline":
        return (
            f"{clock}  {_ICON_LAP} Lap {event.get('lap', '?')} — "
            f"{_fmt_lap_time(event['lap_time'])}, baseline set"
        )
    if kind == "prompt":
        return f"{clock}  {_ICON_RADIO} {event.get('text', '')}"
    if kind == "discard":
        return f"{clock}  ↩ {event.get('speech', 'Lap discarded.')}"
    if kind in ("invalid", "dirty_baseline_skipped"):
        return f"{clock}  ⚠ {event.get('speech', '')}"
    if kind == "schedule":
        return ""  # prompt-schedule dump — machinery, not radio
    return f"{clock}  \xb7 {kind}"
