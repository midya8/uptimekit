import tempfile
import unittest
from pathlib import Path

from uptimekit.history import append, compact, read
from uptimekit.probes import Result


def result(name, ok, at, latency=12.5, detail="status 200"):
    return Result(name, "http", ok, latency, detail, at,
                  status_code=200 if ok else 503, error="" if ok else "boom")


class TestAppendAndRead(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "h.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def test_roundtrip(self):
        append(self.path, [result("api", True, 100.0), result("db", False, 200.0)])
        entries = read(self.path)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].name, "api")
        self.assertTrue(entries[0].ok)
        self.assertFalse(entries[1].ok)
        self.assertEqual(entries[1].status_code, 503)

    def test_missing_file_reads_empty(self):
        self.assertEqual(read(self.path), [])

    def test_append_creates_parent_dirs(self):
        deep = Path(self.tmp.name) / "a" / "b" / "h.jsonl"
        self.assertEqual(append(deep, [result("api", True, 1.0)]), 1)
        self.assertTrue(deep.exists())

    def test_filter_by_name_and_window(self):
        append(self.path, [result("api", True, 100.0), result("db", True, 150.0),
                           result("api", False, 200.0)])
        self.assertEqual([e.checked_at for e in read(self.path, name="api")],
                         [100.0, 200.0])
        self.assertEqual([e.checked_at for e in read(self.path, since=150.0)],
                         [150.0, 200.0])
        self.assertEqual([e.checked_at for e in read(self.path, until=150.0)],
                         [100.0, 150.0])

    def test_read_sorts_oldest_first(self):
        append(self.path, [result("api", True, 300.0)])
        append(self.path, [result("api", True, 100.0)])
        self.assertEqual([e.checked_at for e in read(self.path)], [100.0, 300.0])

    def test_corrupt_line_raises_with_lineno(self):
        self.path.write_text('{"ok": true}\n')
        with self.assertRaisesRegex(ValueError, "line 1"):
            read(self.path)

    def test_compact_drops_old_entries(self):
        append(self.path, [result("api", True, 100.0), result("api", True, 200.0),
                           result("api", True, 300.0)])
        dropped = compact(self.path, keep_after=250.0)
        self.assertEqual(dropped, 2)
        self.assertEqual([e.checked_at for e in read(self.path)], [300.0])


if __name__ == "__main__":
    unittest.main()
