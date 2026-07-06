"""JSONL event log for live coaching sessions.

One JSON object per line, flushed on every write — a sim or process crash
must not lose the laps already driven. This is the raw material for tuning
nudge/prompt thresholds after a session: every spoken line, every prompt
fire, and the full per-region diagnosis numbers land here so the drive
itself is the experiment.
"""

import json
from datetime import datetime, timezone
from pathlib import Path


class SessionLog:
    """Append-only JSONL log; every event gets a UTC ISO timestamp."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "a", encoding="utf-8")

    def log(self, event: str, **fields) -> None:
        """Write one event line. Never raises into the live loop."""
        record = {"t": datetime.now(timezone.utc).isoformat(), "event": event}
        record.update(fields)
        try:
            line = json.dumps(record, default=str)
        except Exception:
            line = json.dumps({"t": record["t"], "event": event,
                               "error": "unserializable event"})
        self._fh.write(line + "\n")
        self._fh.flush()

    def close(self) -> None:
        try:
            self._fh.close()
        except Exception:
            pass
