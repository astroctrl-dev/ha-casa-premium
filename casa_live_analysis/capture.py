"""Single bounded backend-owned 15-minute CASA diagnostic recording."""
import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic

DURATION_SECONDS = 900


class Capture:
    def __init__(self, directory=Path("/data")):
        self.directory = Path(directory)
        self.started = None
        self.deadline = None
        self.file = self.directory / "casa-last-capture.csv"
        self.handle = None
        self.writer = None
        self.rows = 0
        self.status = "saved" if self.file.is_file() else "idle"
        self.error = None

    def start(self):
        if self.status == "running":
            raise ValueError("Opptak pågår allerede")
        self.directory.mkdir(parents=True, exist_ok=True)
        pending = self.file.with_suffix(".csv.part")
        self.handle = pending.open("w", newline="", encoding="utf-8")
        self.writer = csv.writer(self.handle)
        self.writer.writerow(("utc", "seq", "kind", "event_json"))
        self.handle.flush()
        self.rows = 0
        self.started = datetime.now(timezone.utc).isoformat()
        self.deadline = monotonic() + DURATION_SECONDS
        self.status = "running"
        self.error = None

    def append(self, event):
        self.tick()
        if self.status != "running":
            return
        try:
            self.writer.writerow((event.get("utc"), event.get("seq"),
                                  event.get("kind"), json.dumps(event, ensure_ascii=False)))
            self.rows += 1
            self.handle.flush()
        except OSError as exc:
            self.error = str(exc)
            self._close()
            self.status = "failed"

    def _close(self):
        if self.handle:
            self.handle.close()
        self.handle = None
        self.writer = None

    def stop(self):
        if self.status != "running":
            return
        try:
            self._close()
            os.replace(self.file.with_suffix(".csv.part"), self.file)
            self.status = "saved"
        except OSError as exc:
            self.status = "failed"
            self.error = str(exc)

    def tick(self):
        if self.status == "running" and monotonic() >= self.deadline:
            self.stop()

    def snapshot(self):
        self.tick()
        return {"status": self.status, "started_at": self.started,
                "remaining_seconds": max(0, int(self.deadline - monotonic() + 0.999))
                if self.status == "running" else 0,
                "rows": self.rows, "file_exists": self.file.is_file(),
                "error": self.error}
