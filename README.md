# uptimekit

Synthetic uptime monitoring and availability reporting in pure Python -
no dependencies, no database, no daemon required. Point it at your
services, run `check` from cron or CI, and `report` tells you each
target's availability, average latency and incident history. A companion
status-page renderer (coming next) turns the same history into a
self-contained HTML status page.

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
  the window, plus average latency of the successful ones.
- **Incidents** - a run of N consecutive failures opens an incident at the
  first failure; the next success closes it. `--threshold 2` is the flap
  guard: one bad probe is noise, two is a page. `--fail-open` exits 1
  while any incident is open, so CI can gate on it.

## Usage

```bash
python -m uptimekit check --config examples/targets.json          # probe once, record
python -m uptimekit check --config examples/targets.json --json   # machine-readable
python -m uptimekit report --window 24h                           # availability roll-up
python -m uptimekit report --incidents --threshold 2 --fail-open  # gate on open incidents
python -m uptimekit compact --keep 30d                            # retention
```

`check` exits 1 when any target fails, so a cron line doubles as an
alerting path:

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
fails when the certificate is expired or the handshake fails).
Unknown keys and missing fields are rejected with exit 2.

## Tests

```bash
python -m unittest discover -s tests -v
```

45 tests run fully offline: probe behavior is verified against loopback
HTTP/TCP servers, TLS paths use injected certificates, and the CLI tests
mock the probe engine so the suite never touches the network.

## Layout

```
uptimekit/
  probes.py        # target specs, HTTP/TCP/TLS probes, config validation
  history.py       # append-only JSONL store, window reads, retention
  availability.py  # uptime roll-ups, incident detection, current state
  __main__.py      # CLI: check / report / compact
tests/             # unittest suite, no network access
examples/          # sample target config
```
