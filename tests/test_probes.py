import http.server
import json
import threading
import time
import unittest
from unittest import mock

from uptimekit.probes import (Target, cert_days_left, check_tls, load_targets,
                              run_checks)


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/ok":
            body = b"service is operational"
            self.send_response(200)
        elif self.path == "/broken":
            body = b"boom"
            self.send_response(503)
        else:
            body = b"nope"
            self.send_response(404)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # quiet test server
        pass


class ServerCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join()
        cls.server.server_close()

    def url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"


class TestHttpProbe(ServerCase):
    def run_one(self, target):
        return run_checks([target], now=1234567890.0)[0]

    def test_ok_when_status_matches(self):
        result = self.run_one(Target("api", "http", url=self.url("/ok")))
        self.assertTrue(result.ok)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.checked_at, 1234567890.0)
        self.assertGreaterEqual(result.latency_ms, 0)

    def test_fail_on_unexpected_status(self):
        result = self.run_one(Target("api", "http", url=self.url("/broken")))
        self.assertFalse(result.ok)
        self.assertIn("503", result.detail)
        self.assertEqual(result.status_code, 503)

    def test_expect_status_is_configurable(self):
        target = Target("api", "http", url=self.url("/broken"), expect_status=503)
        self.assertTrue(self.run_one(target).ok)

    def test_keyword_must_appear_in_body(self):
        good = self.run_one(Target("api", "http", url=self.url("/ok"),
                                   keyword="operational"))
        self.assertTrue(good.ok)
        bad = self.run_one(Target("api", "http", url=self.url("/ok"),
                                  keyword="degraded"))
        self.assertFalse(bad.ok)
        self.assertIn("keyword", bad.detail)

    def test_unreachable_host_fails_cleanly(self):
        result = self.run_one(Target("down", "http",
                                     url="http://127.0.0.1:1/", timeout=1.0))
        self.assertFalse(result.ok)
        self.assertTrue(result.error)

    def test_bad_scheme_fails_cleanly(self):
        result = self.run_one(Target("odd", "http", url="ht!tp://x", timeout=1.0))
        self.assertFalse(result.ok)
        self.assertTrue(result.error)


class TestTcpProbe(ServerCase):
    def test_open_port_connects(self):
        target = Target("lb", "tcp", host="127.0.0.1", port=self.port)
        result = run_checks([target])[0]
        self.assertTrue(result.ok)
        self.assertIn(str(self.port), result.detail)

    def test_closed_port_fails(self):
        target = Target("lb", "tcp", host="127.0.0.1", port=1, timeout=1.0)
        result = run_checks([target])[0]
        self.assertFalse(result.ok)
        self.assertTrue(result.error)


class TestTlsProbe(unittest.TestCase):
    def test_cert_days_left_math(self):
        cert = {"notAfter": "Jan  2 00:00:00 2027 GMT"}
        import ssl
        expected = (ssl.cert_time_to_seconds(cert["notAfter"]) - 1000.0) / 86400.0
        self.assertAlmostEqual(cert_days_left(cert, 1000.0), expected)

    def test_valid_cert_is_ok(self):
        cert = {"notAfter": "Jan  2 00:00:00 2099 GMT"}
        with mock.patch("uptimekit.probes._fetch_cert", return_value=cert):
            result = check_tls(Target("site", "tls", host="example.com", port=443),
                               now=1234567890.0)
        self.assertTrue(result.ok)
        self.assertIn("expires in", result.detail)

    def test_expired_cert_fails(self):
        cert = {"notAfter": "Jan  2 00:00:00 2001 GMT"}
        with mock.patch("uptimekit.probes._fetch_cert", return_value=cert):
            result = check_tls(Target("site", "tls", host="example.com", port=443),
                               now=1234567890.0)
        self.assertFalse(result.ok)
        self.assertIn("EXPIRED", result.detail)

    def test_min_days_threshold_fails_before_expiry(self):
        cert = {"notAfter": "Jan 10 00:00:00 2027 GMT"}
        import ssl
        now = ssl.cert_time_to_seconds(cert["notAfter"]) - 5 * 86400.0
        target = Target("site", "tls", host="example.com", port=443, min_days=14)
        with mock.patch("uptimekit.probes._fetch_cert", return_value=cert):
            result = check_tls(target, now=now)
        self.assertFalse(result.ok)
        self.assertIn("threshold 14", result.detail)

    def test_min_days_passes_when_far_from_expiry(self):
        cert = {"notAfter": "Jan 10 00:00:00 2027 GMT"}
        import ssl
        now = ssl.cert_time_to_seconds(cert["notAfter"]) - 60 * 86400.0
        target = Target("site", "tls", host="example.com", port=443, min_days=14)
        with mock.patch("uptimekit.probes._fetch_cert", return_value=cert):
            result = check_tls(target, now=now)
        self.assertTrue(result.ok)

    def test_min_days_only_for_tls(self):
        with self.assertRaises(ValueError):
            Target("api", "http", url="http://x", min_days=5).validate()

    def test_handshake_failure_fails_cleanly(self):
        with mock.patch("uptimekit.probes._fetch_cert",
                        side_effect=OSError("refused")):
            result = check_tls(Target("site", "tls", host="example.com", port=443),
                               now=1234567890.0)
        self.assertFalse(result.ok)
        self.assertEqual(result.detail, "TLS handshake failed")
        self.assertIn("refused", result.error)


class TestLoadTargets(unittest.TestCase):
    def test_happy_path(self):
        targets = load_targets([
            {"name": "api", "kind": "http", "url": "https://api.example.com",
             "expect_status": 200, "keyword": "ok", "timeout": 2.5},
            {"name": "db", "kind": "tcp", "host": "db.internal", "port": 5432},
            {"name": "web", "kind": "tls", "host": "example.com", "port": 443},
        ])
        self.assertEqual([t.name for t in targets], ["api", "db", "web"])
        self.assertEqual(targets[0].timeout, 2.5)
        self.assertEqual(targets[1].expect_status, 200)  # default

    def test_rejects_bad_specs(self):
        bad = [
            "not-a-list",
            ["not-an-object"],
            [{"name": "x", "kind": "http"}],                       # no url
            [{"name": "x", "kind": "tcp", "host": "h"}],           # no port
            [{"name": "", "kind": "tcp", "host": "h", "port": 1}], # no name
            [{"name": "x", "kind": "carrier-pigeon"}],             # bad kind
            [{"name": "x", "kind": "tcp", "host": "h", "port": 70000}],
            [{"name": "x", "kind": "tcp", "host": "h", "port": 1, "mystery": 1}],
        ]
        for spec in bad:
            with self.assertRaises(ValueError, msg=repr(spec)):
                load_targets(spec)


class TestRunChecks(unittest.TestCase):
    def test_all_targets_run_in_order(self):
        seen = []

        class FakeHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append(self.path)
                self.send_response(200)
                self.end_headers()

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            targets = [Target(f"t{i}", "http", url=f"http://127.0.0.1:{port}/{i}")
                       for i in range(3)]
            results = run_checks(targets, now=time.time())
            self.assertEqual(len(results), 3)
            self.assertTrue(all(r.ok for r in results))
        finally:
            server.shutdown()
            thread.join()
            server.server_close()

    def test_invalid_target_aborts_before_probing(self):
        with self.assertRaises(ValueError):
            run_checks([Target("", "http", url="http://example.com")])


if __name__ == "__main__":
    unittest.main()
