"""Passive analysis of CASA diagnostic events; HA receive time only."""
from collections import Counter
from datetime import datetime
from statistics import median

def _seconds(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError, AttributeError):
        return None

def analyze(events, threshold_seconds=0.5):
    counts = Counter(e.get("kind", "unknown") for e in events)
    receives = [e for e in events if e.get("kind") == "tcp_receive"]
    intervals, gaps, previous = [], [], None
    for e in receives:
        t = _seconds(e.get("utc"))
        if t is None:
            continue
        if previous is not None:
            delta = t - previous
            if delta >= 0:
                intervals.append(delta)
                if delta > threshold_seconds:
                    gaps.append({"utc": e["utc"], "seconds": round(delta, 3)})
        previous = t
    commands = Counter(e.get("command") for e in events if e.get("kind") == "telegram" and e.get("command"))
    keys = Counter(key for e in events if e.get("kind") == "sensor_observation" for key in e.get("keys", []))
    crc = sum(int(e.get("count", 1)) for e in events if e.get("kind") == "crc_error")
    times = [_seconds(e.get("utc")) for e in events]
    times = [t for t in times if t is not None]
    return {
        "events": len(events),
        "duration_seconds": round(max(times)-min(times), 3) if len(times)>1 else None,
        "counts": dict(counts),
        "tcp_bytes": sum(int(e.get("bytes", 0)) for e in receives),
        "tcp_interval_median_ms": round(median(intervals)*1000, 1) if intervals else None,
        "tcp_interval_max_ms": round(max(intervals)*1000, 1) if intervals else None,
        "gaps_over_threshold": len(gaps),
        "largest_gaps": sorted(gaps, key=lambda g:-g["seconds"])[:20],
        "crc_errors": crc,
        "telegram_commands": dict(commands),
        "sensor_keys": dict(keys),
        "limits": [
            "Gaps measure HA TCP receive observations, not proven TCP outages.",
            "Current API does not expose raw RS-485 timing or sensor values.",
            "Results include retained events only; dropped events may bias statistics.",
        ],
    }
