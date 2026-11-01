"""Probe history: append-only JSONL store with retention and window queries.

One line per probe result, so the file stays appendable from cron and
cheap to tail. Reads filter by target and time window without loading more
than the file itself - history is operational data, not a database.
"""

import json
import time
from dataclasses import dataclass
from pathlib import Path

from .probes import Result

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Entry:
    """One recorded probe result."""

    name: str
    kind: str
    ok: bool
    latency_ms: float
    detail: str
    checked_at: float
    status_code: int = 0
    error: str = ""


def entry_from_result(result: Result) -> Entry:
    return Entry(result.name, result.kind, result.ok, result.latency_ms,
                 result.detail, result.checked_at, result.status_code,
                 result.error)


def _to_json(entry: Entry) -> str:
    return json.dumps({
        "v": SCHEMA_VERSION,
        "name": entry.name,
        "kind": entry.kind,
        "ok": entry.ok,
        "latency_ms": round(entry.latency_ms, 1),
        "detail": entry.detail,
        "checked_at": entry.checked_at,
        "status_code": entry.status_code,
        "error": entry.error,
    }, separators=(",", ":"))


def _from_json(line: str, lineno: int) -> Entry:
    try:
        data = json.loads(line)
        return Entry(
            name=str(data["name"]),
            kind=str(data.get("kind", "")),
            ok=bool(data["ok"]),
            latency_ms=float(data.get("latency_ms", 0.0)),
            detail=str(data.get("detail", "")),
            checked_at=float(data["checked_at"]),
            status_code=int(data.get("status_code", 0)),
            error=str(data.get("error", "")),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"corrupt history line {lineno}: {exc}") from exc


def append(path: Path, results: list[Result], now: float | None = None) -> int:
    """Append probe results to the history file. Returns lines written."""
    del now  # results carry their own checked_at
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for result in results:
            fh.write(_to_json(entry_from_result(result)) + "\n")
    return len(results)


def read(path: Path, name: str | None = None, since: float | None = None,
         until: float | None = None) -> list[Entry]:
    """Read entries, oldest first, filtered by target and time window."""
    path = Path(path)
    if not path.exists():
        return []
    entries = []
    with path.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            entry = _from_json(line, lineno)
            if name is not None and entry.name != name:
                continue
            if since is not None and entry.checked_at < since:
                continue
            if until is not None and entry.checked_at > until:
                continue
            entries.append(entry)
    entries.sort(key=lambda e: e.checked_at)
    return entries


def compact(path: Path, keep_after: float, now: float | None = None) -> int:
    """Drop entries older than keep_after (retention). Returns lines dropped.

    Rewrites the file atomically: write-then-rename, so a crash mid-compact
    never leaves a truncated history.
    """
    del now
    path = Path(path)
    entries = read(path)
    kept = [e for e in entries if e.checked_at >= keep_after]
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for entry in kept:
            fh.write(_to_json(entry) + "\n")
    tmp.replace(path)
    return len(entries) - len(kept)
