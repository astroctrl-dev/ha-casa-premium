"""Bounded, passive diagnostics event stream for the CASA receiver.

Times represent Home Assistant observations, not physical RS-485 wire timing.
No gateway connection or device command is created by this module.
"""
from collections import deque
from datetime import datetime, timezone
from time import monotonic

MAX_EVENTS = 4096


class DiagnosticEvents:
    def __init__(self):
        self._events = deque(maxlen=MAX_EVENTS)
        self._seq = 0
        self._last_time = None

    def record(self, kind, **fields):
        now = monotonic()
        self._seq += 1
        event = {
            "seq": self._seq,
            "utc": datetime.now(timezone.utc).isoformat(),
            "kind": kind,
            "elapsed_ms": round((now - self._last_time) * 1000, 3)
            if self._last_time is not None else None,
            **fields,
        }
        self._last_time = now
        self._events.append(event)

    def snapshot(self, after=0):
        after = max(0, int(after))
        oldest = self._events[0]["seq"] if self._events else self._seq + 1
        return {
            "latest_seq": self._seq,
            "oldest_seq": oldest,
            "lost": max(0, oldest - after - 1) if after else 0,
            "events": [event for event in self._events if event["seq"] > after],
        }
