import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from uptimekit.__main__ import main
from uptimekit.probes import Result


def fake_results(ok_map):
    def _run(targets, now=None):
        return [Result(t.name, t.kind, ok_map.get(t.name, True), 5.0,
                       "status 200", 1000.0, 200, "") for t in targets]
    return _run


class CliCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.config = self.dir / "targets.json"
        self.config.write_text(json.dumps([
            {"name": "api", "kind": "http", "url": "http://x/"},
            {"name": "db", "kind": "tcp", "host": "h", "port": 1},
        ]))
        self.history = self.dir / "h.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def _seed(self, ok_seq, base=0.0):
        from uptimekit.history import append
        results = [Result("api", "http", ok, 10.0, "d", base + i + 1,
                          200 if ok else 503, "")
                   for i, ok in enumerate(ok_seq)]
        append(self.history, results)

    def run_cli(self, argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(argv)
        return code, buf.getvalue()


class TestCheck(CliCase):
    def test_check_records_and_reports(self):
        with mock.patch("uptimekit.__main__.run_checks", fake_results({})):
            code, out = self.run_cli(["check", "--config", str(self.config),
                                      "--history", str(self.history)])
        self.assertEqual(code, 0)
        self.assertIn("[ok  ] api", out)
        lines = self.history.read_text().strip().split("\n")
        self.assertEqual(len(lines), 2)

    def test_check_exit_1_on_failure(self):
        with mock.patch("uptimekit.__main__.run_checks", fake_results({"db": False})):
            code, out = self.run_cli(["check", "--config", str(self.config),
                                      "--history", str(self.history)])
        self.assertEqual(code, 1)
        self.assertIn("[FAIL] db", out)

    def test_check_json(self):
        with mock.patch("uptimekit.__main__.run_checks", fake_results({})):
            code, out = self.run_cli(["check", "--config", str(self.config),
                                      "--history", str(self.history), "--json"])
        data = json.loads(out)
        self.assertEqual([r["name"] for r in data], ["api", "db"])
        self.assertTrue(all(r["ok"] for r in data))

    def test_bad_config_exits_2(self):
        self.config.write_text("{bad json")
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                main(["check", "--config", str(self.config),
                      "--history", str(self.history)])
        self.assertEqual(ctx.exception.code, 2)


class TestReport(CliCase):
    def test_report_rollup(self):
        self._seed([True, True, False, True])
        with mock.patch("uptimekit.__main__.time") as t:
            t.time.return_value = 100.0
            t.strftime = __import__("time").strftime
            t.localtime = __import__("time").localtime
            code, out = self.run_cli(["report", "--history", str(self.history)])
        self.assertEqual(code, 0)
        self.assertIn("api", out)
        self.assertIn("75.00%", out)
        self.assertIn("currently up", out)

    def test_report_empty_history(self):
        code, out = self.run_cli(["report", "--history", str(self.history)])
        self.assertEqual(code, 0)
        self.assertIn("no history in window", out)

    def test_report_json(self):
        self._seed([True, False])
        with mock.patch("uptimekit.__main__.time") as t:
            t.time.return_value = 100.0
            t.strftime = __import__("time").strftime
            t.localtime = __import__("time").localtime
            code, out = self.run_cli(["report", "--history", str(self.history),
                                      "--json"])
        data = json.loads(out)
        self.assertEqual(data["targets"][0]["uptime_pct"], 50.0)
        self.assertEqual(data["targets"][0]["state"], "down")

    def test_report_incidents_fail_open(self):
        self._seed([False, False])
        with mock.patch("uptimekit.__main__.time") as t:
            t.time.return_value = 100.0
            t.strftime = __import__("time").strftime
            t.localtime = __import__("time").localtime
            code, out = self.run_cli(["report", "--history", str(self.history),
                                      "--incidents", "--fail-open"])
        self.assertEqual(code, 1)
        self.assertIn("OPEN", out)

    def test_report_incidents_closed_exits_0(self):
        self._seed([False, True])
        with mock.patch("uptimekit.__main__.time") as t:
            t.time.return_value = 100.0
            t.strftime = __import__("time").strftime
            t.localtime = __import__("time").localtime
            code, out = self.run_cli(["report", "--history", str(self.history),
                                      "--incidents", "--fail-open"])
        self.assertEqual(code, 0)
        self.assertNotIn("OPEN", out)

    def test_bad_window_exits(self):
        with self.assertRaises(SystemExit):
            main(["report", "--history", str(self.history), "--window", "fortnight"])


class TestCompact(CliCase):
    def test_compact_drops_old(self):
        self._seed([True, True], base=0.0)
        with mock.patch("uptimekit.__main__.time") as t:
            t.time.return_value = 100.0
            code, out = self.run_cli(["compact", "--history", str(self.history),
                                      "--keep", "10"])
        self.assertEqual(code, 0)
        self.assertIn("dropped 2 entries", out)


if __name__ == "__main__":
    unittest.main()
