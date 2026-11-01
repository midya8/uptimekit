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


def percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile; 0.0 for empty input."""
    if not values:
        return 0.0
    if not 0 < pct <= 100:
        raise ValueError("pct must be in (0, 100]")
    ordered = sorted(values)
    import math
    rank = max(1, math.ceil(pct / 100.0 * len(ordered)))
    return ordered[rank - 1]


def error_budget_consumed(uptime_pct: float, slo: float) -> float:
    """Fraction of the error budget consumed in the window.

    0.0 at 100% uptime, 1.0 exactly at the SLO, above 1.0 when the SLO is
    breached. An SLO of 100% allows no bad checks at all, so any failure
    exhausts the budget immediately.
    """
    if not 0.0 < slo <= 100.0:
        raise ValueError("slo must be in (0, 100]")
    if not 0.0 <= uptime_pct <= 100.0:
        raise ValueError("uptime_pct must be between 0 and 100")
    if slo >= 100.0:
        return 0.0 if uptime_pct >= 100.0 else float("inf")
    return (100.0 - uptime_pct) / (100.0 - slo)


def latency_percentiles(entries: list[Entry], name: str,
                        pcts: tuple = (50, 95)) -> dict:
    """Percentiles over successful checks only - a failed check has no
    meaningful latency and would drag the numbers toward zero."""
    latencies = [e.latency_ms for e in entries if e.name == name and e.ok]
    return {p: percentile(latencies, p) for p in pcts}


@dataclass(frozen=True)
class TrendBucket:
    """Availability for one time bucket (e.g. one day)."""

    start: float
    checks: int
    failures: int
    uptime_pct: float


def trend(entries: list[Entry], name: str, bucket_seconds: float,
          start: float, end: float) -> list[TrendBucket]:
    """Availability per bucket between start and end, buckets aligned to
    start. Empty buckets are reported with zero checks, not skipped, so a
    monitoring gap is visible as a gap instead of averaged away."""
    if bucket_seconds <= 0:
        raise ValueError("bucket_seconds must be positive")
    if end <= start:
        raise ValueError("end must be after start")
    mine = [e for e in entries if e.name == name]
    buckets = []
    t = start
    while t < end:
        in_bucket = [e for e in mine if t <= e.checked_at < t + bucket_seconds]
        checks = len(in_bucket)
        failures = sum(1 for e in in_bucket if not e.ok)
        uptime = 100.0 * (checks - failures) / checks if checks else 0.0
        buckets.append(TrendBucket(t, checks, failures, uptime))
        t += bucket_seconds
    return buckets
