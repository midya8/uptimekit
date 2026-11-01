# uptimekit

Synthetic uptime monitoring and availability reporting in pure Python -
no dependencies, no database, no daemon required. Point it at your
services, run `check` from cron or CI, and `report` tells you each
target's availability, average latency and incident history. The same history renders into a self-contained
HTML status page - no JS, no external CSS, servable from any static host.

Built as a portfolio project: the monitoring end of the SRE toolkit
family, where [sre-toolkit](https://github.com/midya8/sre-toolkit) covers
error budgets and alert triage.

## How it works

```
targets.json --check--> probe engine --append--> uptime-history.jsonl
                                                    |
                                    report <--------+
                        availability, latency, incidents
```

- **Probes** - HTTP (status code, optional keyword in body, latency), TCP
  connect, and TLS certificate expiry. Every probe returns a result; an
  unreachable target is a failed check, never a crash.
- **History** - append-only JSONL, one line per check. Cheap to tail,
  trivially backup-able, and `compact` enforces retention with an atomic
  rewrite.
- **Availability** - honest math: successful checks over total checks in
  the window, plus average latency of the successful ones and p50/p95
  percentiles (failures excluded - a failed check has no meaningful
  latency). `--trend` adds a per-day strip per target where monitoring
  gaps show as gaps instead of being averaged away, and `--compare`
  diffs the window against the immediately preceding one so a
  regression reads as a regression, not just a number.
- **Incidents** - a run of N consecutive failures opens an incident at the
  first failure; the next success closes it. `--threshold 2` is the flap
  guard: one bad probe is noise, two is a page. `--fail-open` exits 1
  while any incident is open, so CI can gate on it.

## Usage

```bash
python -m uptimekit check --config examples/targets.json          # probe once, record
python -m uptimekit check --config examples/targets.json --json   # machine-readable
python -m uptimekit report --window 24h                           # availability roll-up with p50/p95 latency
python -m uptimekit report --window 7d --trend                    # per-day availability strip
python -m uptimekit report --window 24h --compare                 # vs the previous 24h
python -m uptimekit report --incidents --threshold 2 --fail-open  # gate on open incidents
python -m uptimekit status-page --out status.html             # self-contained HTML status page
python -m uptimekit watch --config targets.json --interval 300  # probe forever (or --iterations N)
python -m uptimekit compact --keep 30d                            # retention
```

`watch` runs the probe loop itself for hosts without cron (Ctrl-C stops
cleanly with a summary). `check` exits 1 when any target fails, so a cron
line doubles as an alerting path:

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

Kinds: `http` (needs `url`; `expect_status` defaults to 200, `keyword`
optional), `tcp` (needs `host`/`port`), `tls` (needs `host`/`port`;
fails when the certificate is expired, expires within `min_days`, or the
handshake fails).
Unknown keys and missing fields are rejected with exit 2.

## Status page

`status-page` renders current state, uptime over the window, the latest
check detail and a 30-check tick strip per target into one HTML file with
inline CSS and no JavaScript. Serve it from any static host, commit it to
GitHub Pages, or open it from disk. Regenerate it after each check run;
`examples/status.html` is a rendered example. Targets come from
`--config` when given, otherwise from the history itself.

## Tests

```bash
python -m unittest discover -s tests -v
```

80 tests run fully offline: probe behavior is verified against loopback
HTTP/TCP servers, TLS paths use injected certificates, and the CLI tests
mock the probe engine so the suite never touches the network.

## Layout

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
