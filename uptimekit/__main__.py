"""uptimekit CLI: check, report, compact."""

import argparse
import json
import sys
import time
from pathlib import Path

from .availability import availability, current_state, fleet, incidents
from .history import append, compact, read
from .probes import load_targets, run_checks

WINDOWS = {"1h": 3600.0, "24h": 86400.0, "7d": 7 * 86400.0, "30d": 30 * 86400.0}
DEFAULT_HISTORY = "uptime-history.jsonl"


def _load_config(path: str):
    try:
        return load_targets(json.load(open(path)))
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"error: bad config: {exc}", file=sys.stderr)
        raise SystemExit(2)


def _window_seconds(value: str) -> float:
    if value in WINDOWS:
        return WINDOWS[value]
    try:
        seconds = float(value)
    except ValueError:
        raise SystemExit(f"error: unknown window {value!r} "
                         f"(use one of {', '.join(WINDOWS)} or seconds)")
    if seconds <= 0:
        raise SystemExit("error: window must be positive")
    return seconds


def _cmd_check(args: argparse.Namespace) -> int:
    targets = _load_config(args.config)
    results = run_checks(targets)
    append(Path(args.history), results)
    if args.json:
        print(json.dumps([
            {"name": r.name, "kind": r.kind, "ok": r.ok,
             "latency_ms": round(r.latency_ms, 1), "detail": r.detail,
             "checked_at": r.checked_at, "status_code": r.status_code,
             "error": r.error} for r in results], indent=2))
    else:
        for r in results:
            mark = "ok  " if r.ok else "FAIL"
            print(f"[{mark}] {r.name:20s} {r.detail}")
    return 0 if all(r.ok for r in results) else 1


def _cmd_report(args: argparse.Namespace) -> int:
    now = time.time()
    window = _window_seconds(args.window)
    entries = read(Path(args.history), since=now - window)
    rolls = fleet(entries)
    if args.json:
        print(json.dumps({
            "window": args.window,
            "targets": [
                {"name": a.name, "checks": a.checks, "failures": a.failures,
                 "uptime_pct": round(a.uptime_pct, 3),
                 "avg_latency_ms": round(a.avg_latency_ms, 1),
                 "state": current_state(entries, a.name)}
                for a in rolls],
        }, indent=2))
        return 0
    print(f"Availability over {args.window} (to {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now))}):")
    if not rolls:
        print("  no history in window")
    for a in rolls:
        state = current_state(entries, a.name)
        latency = f", avg {a.avg_latency_ms:.0f} ms" if a.checks > a.failures else ""
        print(f"  {a.name:20s} {a.uptime_pct:6.2f}% over {a.checks} checks"
              f" ({a.failures} failed{latency}) - currently {state}")
    if args.incidents:
        open_found = False
        print("Incidents:")
        for a in rolls:
            for inc in incidents(entries, a.name, threshold=args.threshold):
                status = "OPEN" if inc.open else \
                    f"ended {time.strftime('%H:%M:%S', time.localtime(inc.ended_at))}"
                if inc.open:
                    open_found = True
                print(f"  {inc.name:20s} from {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(inc.started_at))}"
                      f" ({inc.checks_failed} check{'s' if inc.checks_failed != 1 else ''})"
                      f" - {status}")
        return 1 if open_found and args.fail_open else 0
    return 0


def _cmd_compact(args: argparse.Namespace) -> int:
    keep = _window_seconds(args.keep)
    dropped = compact(Path(args.history), time.time() - keep)
    print(f"compacted {args.history}: dropped {dropped} entr{'y' if dropped == 1 else 'ies'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="uptimekit",
        description="Synthetic uptime monitoring: probe targets, keep history,"
                    " report availability and incidents.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("check", help="probe every target once and record results")
    p.add_argument("--config", required=True, help="JSON list of targets")
    p.add_argument("--history", default=DEFAULT_HISTORY)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_check)

    p = sub.add_parser("report", help="availability and incidents from history")
    p.add_argument("--history", default=DEFAULT_HISTORY)
    p.add_argument("--window", default="24h",
                   help="1h, 24h, 7d, 30d, or a number of seconds")
    p.add_argument("--incidents", action="store_true", help="also list incidents")
    p.add_argument("--threshold", type=int, default=1,
                   help="consecutive failures before an incident opens")
    p.add_argument("--fail-open", action="store_true",
                   help="exit 1 when an incident is still open")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_report)

    p = sub.add_parser("compact", help="drop history older than --keep")
    p.add_argument("--history", default=DEFAULT_HISTORY)
    p.add_argument("--keep", default="30d")
    p.set_defaults(func=_cmd_compact)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
