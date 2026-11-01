"""Synthetic probes: HTTP, TCP connect, TLS certificate expiry.

Every probe returns a Result; a probe never raises for an unhealthy target,
only for a misconfigured spec. Network access goes through small helpers so
tests can run fully offline or against loopback servers.
"""

import socket
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

DEFAULT_TIMEOUT = 5.0
USER_AGENT = "uptimekit/0.1 (+https://github.com/midya8/uptimekit)"


@dataclass(frozen=True)
class Target:
    """One thing to probe.

    kind: "http", "tcp" or "tls".
    http needs url; tcp and tls need host and port.
    """

    name: str
    kind: str
    url: str = ""
    host: str = ""
    port: int = 0
    expect_status: int = 200
    keyword: str = ""
    timeout: float = DEFAULT_TIMEOUT

    def validate(self) -> None:
        if not self.name:
            raise ValueError("target needs a name")
        if self.kind not in ("http", "tcp", "tls"):
            raise ValueError(f"{self.name}: unknown kind {self.kind!r}")
        if self.kind == "http" and not self.url:
            raise ValueError(f"{self.name}: http target needs a url")
        if self.kind in ("tcp", "tls"):
            if not self.host:
                raise ValueError(f"{self.name}: {self.kind} target needs a host")
            if not (0 < self.port < 65536):
                raise ValueError(f"{self.name}: {self.kind} target needs a valid port")
        if self.timeout <= 0:
            raise ValueError(f"{self.name}: timeout must be positive")


@dataclass(frozen=True)
class Result:
    """Outcome of one probe run."""

    name: str
    kind: str
    ok: bool
    latency_ms: float
    detail: str
    checked_at: float
    status_code: int = 0
    error: str = ""


def _timed(fn):
    """Run fn, returning (value, latency_ms) and re-raising fn's errors."""
    start = time.monotonic()
    value = fn()
    return value, (time.monotonic() - start) * 1000.0


def _http_fetch(url: str, timeout: float) -> tuple[int, bytes]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read(1_000_000)
    except urllib.error.HTTPError as exc:  # a real response with a bad status
        return exc.code, exc.read(1_000_000)


def check_http(target: Target, now: float) -> Result:
    try:
        (status, body), latency = _timed(lambda: _http_fetch(target.url, target.timeout))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return Result(target.name, target.kind, False, 0.0, "unreachable",
                      now, error=str(exc.reason if isinstance(exc, urllib.error.URLError) else exc))
    if status != target.expect_status:
        return Result(target.name, target.kind, False, latency,
                      f"status {status}, expected {target.expect_status}",
                      now, status_code=status)
    if target.keyword and target.keyword.encode() not in body:
        return Result(target.name, target.kind, False, latency,
                      f"keyword {target.keyword!r} not found in body",
                      now, status_code=status)
    return Result(target.name, target.kind, True, latency, f"status {status}",
                  now, status_code=status)


def _tcp_connect(host: str, port: int, timeout: float) -> None:
    with socket.create_connection((host, port), timeout=timeout):
        pass


def check_tcp(target: Target, now: float) -> Result:
    try:
        _, latency = _timed(lambda: _tcp_connect(target.host, target.port,
                                                 target.timeout))
    except OSError as exc:
        return Result(target.name, target.kind, False, 0.0, "connect failed",
                      now, error=str(exc))
    return Result(target.name, target.kind, True, latency,
                  f"{target.host}:{target.port} accepted connection", now)


def _fetch_cert(host: str, port: int, timeout: float) -> dict:
    """TLS handshake and decoded peer certificate."""
    context = ssl.create_default_context()
    with socket.create_connection((host, port), timeout=timeout) as sock:
        with context.wrap_socket(sock, server_hostname=host) as tls:
            return tls.getpeercert()


def cert_days_left(decoded_cert: dict, now: float) -> float:
    """Days until notAfter for a decoded peer certificate."""
    not_after = ssl.cert_time_to_seconds(decoded_cert["notAfter"])
    return (not_after - now) / 86400.0


def check_tls(target: Target, now: float) -> Result:
    try:
        cert, latency = _timed(lambda: _fetch_cert(target.host, target.port, target.timeout))
    except (ssl.SSLError, OSError) as exc:
        return Result(target.name, target.kind, False, 0.0, "TLS handshake failed",
                      now, error=str(exc))
    days = cert_days_left(cert, now)
    ok = days > 0
    detail = f"certificate expires in {days:.1f} days" if ok else \
        f"certificate EXPIRED {-days:.1f} days ago"
    return Result(target.name, target.kind, ok, latency, detail, now)


_CHECKS = {"http": check_http, "tcp": check_tcp, "tls": check_tls}


def run_checks(targets: list[Target], now: float | None = None) -> list[Result]:
    """Probe every target, in order; one bad target never stops the rest."""
    now = time.time() if now is None else now
    for target in targets:
        target.validate()
    return [_CHECKS[target.kind](target, now) for target in targets]


def load_targets(data: object) -> list[Target]:
    """Validate a config list of target dicts."""
    if not isinstance(data, list):
        raise ValueError("config must be a JSON list of targets")
    targets = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"target {i} must be an object")
        known = {"name", "kind", "url", "host", "port", "expect_status",
                 "keyword", "timeout"}
        unknown = set(item) - known
        if unknown:
            raise ValueError(f"target {i}: unknown keys {sorted(unknown)}")
        target = Target(
            name=item.get("name", ""),
            kind=item.get("kind", ""),
            url=item.get("url", ""),
            host=item.get("host", ""),
            port=int(item.get("port", 0)),
            expect_status=int(item.get("expect_status", 200)),
            keyword=item.get("keyword", ""),
            timeout=float(item.get("timeout", DEFAULT_TIMEOUT)),
        )
        target.validate()
        targets.append(target)
    return targets
