"""Availability math and incident detection over probe history.

Availability is simple and honest: successful checks divided by total
checks in the window. Incidents are state transitions - a target is down
after N consecutive failed checks and recovers on the first success.
"""

from dataclasses import dataclass

from .history import Entry


@dataclass(frozen=True)
class Availability:
    """Availability for one target over a window."""

    name: str
    checks: int
    failures: int
    uptime_pct: float
    avg_latency_ms: float
    last_ok: bool | None  # None when the window has no checks


def availability(entries: list[Entry], name: str) -> Availability:
    """Roll up one target's entries (already window-filtered)."""
    checks = len(entries)
    if checks == 0:
        return Availability(name, 0, 0, 0.0, 0.0, None)
    failures = sum(1 for e in entries if not e.ok)
    uptime = 100.0 * (checks - failures) / checks
    ok_latencies = [e.latency_ms for e in entries if e.ok]
    avg_latency = sum(ok_latencies) / len(ok_latencies) if ok_latencies else 0.0
    return Availability(name, checks, failures, uptime, avg_latency,
                        entries[-1].ok)


def fleet(entries: list[Entry]) -> list[Availability]:
    """Per-target roll-ups for every target present, sorted by name."""
    names = sorted({e.name for e in entries})
    return [availability([e for e in entries if e.name == n], n) for n in names]


@dataclass(frozen=True)
class Incident:
    """One down period: started at the first failure of a run."""

    name: str
    started_at: float
    ended_at: float | None  # None = still open
    checks_failed: int

    @property
    def open(self) -> bool:
        return self.ended_at is None


def incidents(entries: list[Entry], name: str, threshold: int = 1) -> list[Incident]:
    """Detect down periods for one target, oldest first.

    A run of at least `threshold` consecutive failures opens an incident at
    the run's first failure; the next success closes it. threshold=2 is the
    usual flap guard: one bad probe is noise, two is a page.
    """
    if threshold < 1:
        raise ValueError("threshold must be >= 1")
    mine = sorted((e for e in entries if e.name == name), key=lambda e: e.checked_at)
    found: list[Incident] = []
    run_start: float | None = None
    run_len = 0
    for entry in mine:
        if not entry.ok:
            if run_start is None:
                run_start = entry.checked_at
            run_len += 1
        else:
            if run_start is not None and run_len >= threshold:
                found.append(Incident(name, run_start, entry.checked_at, run_len))
            run_start = None
            run_len = 0
    if run_start is not None and run_len >= threshold:
        found.append(Incident(name, run_start, None, run_len))
    return found


def current_state(entries: list[Entry], name: str) -> str:
    """'up', 'down', or 'unknown' from the latest entry."""
    mine = [e for e in entries if e.name == name]
    if not mine:
        return "unknown"
    return "up" if mine[-1].ok else "down"
