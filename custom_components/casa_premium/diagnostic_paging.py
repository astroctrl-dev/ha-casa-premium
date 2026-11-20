"""Bounded read-only diagnostic event pagination (no Home Assistant dependency)."""


def diagnostic_page(events, after, limit, latest_seq):
    """Return an ordered page and a resumable cursor from the retained event buffer."""
    page = [event for event in events if event["seq"] > after][:limit]
    next_after = page[-1]["seq"] if page else after
    oldest = events[0]["seq"] if events else latest_seq + 1
    return {
        "events": page,
        "next_after": next_after,
        "has_more": next_after < latest_seq,
        "lost": max(0, oldest - after - 1) if after else 0,
    }
