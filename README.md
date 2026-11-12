# uptimekit

I wanted a way to watch a handful of services without running a daemon, a database, or anything else that needs looking after itself. uptimekit is that: synthetic uptime monitoring in pure Python, no dependencies. You point it at your services, run `check` from cron or CI, and `report` tells you each target's availability, average latency, and incident history. The same history renders into a self-contained HTML status page — no JavaScript, no external CSS, servable from any static host.

I built this as a portfolio project. It's the monitoring end of the SRE toolkit family — [sre-toolkit](https://github.com/midya8/sre-toolkit) covers error budgets and alert triage.

## How it works

```
targets.json --check--> probe engine --append--> uptime-history.jsonl
                                                    |
                                    report <--------+
                        availability, latency, incidents
```

**Probes.** Three kinds: HTTP (status code, optional keyword in the body, latency), TCP connect, and TLS certificate expiry, with a `min_days` threshold so a certificate nearing expiry fails the check before it actually lapses. `max_latency_ms` turns slow into down — a 200 that takes 8 seconds is an incident, not a success. Every probe returns a result; an unreachable target is a failed check, never a crash.

**History.** Append-only JSONL, one line per check. Cheap to tail, easy to back up, and `compact` enforces retention with an atomic rewrite.

**Availability.** Straight math: successful checks over total checks in the window, plus average latency of the successful ones and p50/p95 percentiles. Failures are excluded from the latency numbers — a failed check has no meaningful latency. `--trend` adds a per-day strip per target where monitoring gaps show as gaps instead of being averaged away, and `--compare` diffs the window against the immediately preceding one, so a regression reads as a regression, not just a number.

**Incidents.** A run of N consecutive failures opens an incident at the first failure; the next success closes it. `--threshold 2` is the flap guard: one bad probe is noise, two is a page. `--fail-open` exits 1 while any incident is open; `--max-open-minutes` is the gentler gate that fires only on sustained outages, so a self-healing 2-minute blip does not page anyone.

**SLOs.** Give a target `"slo": 99.9` and `report --config` measures the window against it: error budget consumed so far, and whether the SLO is met or breached. `--fail-slo` exits 1 on a breach, so CI or cron can gate on the number that matters instead of on single probes.

## Running it

```bash
python -m uptimekit check --config examples/targets.json          # probe once, record
python -m uptimekit check --config examples/targets.json --json   # machine-readable
python -m uptimekit report --window 24h                           # availability roll-up with p50/p95 latency
python -m uptimekit report --window 7d --trend                    # per-day availability strip
python -m uptimekit report --window 24h --compare                 # vs the previous 24h
python -m uptimekit report --incidents --threshold 2 --fail-open  # gate on open incidents
python -m uptimekit report --incidents --max-open-minutes 15      # gate on sustained outages only
python -m uptimekit report --config examples/targets.json --fail-slo  # gate on error budgets
python -m uptimekit status-page --out status.html             # self-contained HTML status page
python -m uptimekit watch --config targets.json --interval 300  # probe forever (or --iterations N)
python -m uptimekit compact --keep 30d                            # retention
```

`watch` runs the probe loop itself for hosts without cron (Ctrl-C stops cleanly with a summary). `check` exits 1 when any target fails, so a cron line doubles as an alerting path:

```cron
*/5 * * * * cd /opt/uptime && python -m uptimekit check --config targets.json || echo "uptime check failed" | mail -s "uptime" oncall@example.com
```

### Target config

```json
[
  {"name": "api", "kind": "http", "url": "https://api.example.com/health",
   "expect_status": 200, "keyword": "ok", "timeout": 5},
  {"name": "postgres", "kind": "tcp", "host": "db.internal", "port": 5432},
  {"name": "web-tls", "kind": "tls", "host": "example.com", "port": 443}
]
```

Kinds: `http` (needs `url`; `expect_status` defaults to 200, `keyword` optional), `tcp` (needs `host`/`port`), `tls` (needs `host`/`port`; fails when the certificate is expired, expires within `min_days`, or the handshake fails). `max_latency_ms` (http/tcp, default 0 = off) fails a check that passes but is too slow. Unknown keys and missing fields are rejected with exit 2.

## The status page

`status-page` renders current state, uptime over the window, the latest check detail and a 30-check tick strip per target into one HTML file with inline CSS and no JavaScript. Serve it from any static host, commit it to GitHub Pages, or open it from disk. Regenerate it after each check run; `examples/status.html` is a rendered example. Targets come from `--config` when given, otherwise from the history itself.

## Tests

```bash
python -m unittest discover -s tests -v
```

98 tests run fully offline: probe behavior is verified against loopback HTTP/TCP servers, TLS paths use injected certificates, and the CLI tests mock the probe engine so the suite never touches the network.

## Files

```
uptimekit/
  probes.py        # target specs, HTTP/TCP/TLS probes, config validation
  history.py       # append-only JSONL store, window reads, retention
  availability.py  # uptime roll-ups, incident detection, current state
  statuspage.py    # self-contained HTML status page renderer
  __main__.py      # CLI: check / watch / report / status-page / compact
tests/             # unittest suite, no network access
examples/          # sample target config
```
