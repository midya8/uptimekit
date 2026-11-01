import unittest

from uptimekit.availability import (availability, current_state, fleet,
                                    incidents, latency_percentiles,
                                    percentile, trend)
from uptimekit.history import Entry


def entry(name, ok, at, latency=10.0):
    return Entry(name, "http", ok, latency, "d", at, 200 if ok else 503, "")


class TestAvailability(unittest.TestCase):
    def test_basic_rollup(self):
        entries = [entry("api", True, 1), entry("api", True, 2),
                   entry("api", False, 3), entry("api", True, 4)]
        a = availability(entries, "api")
        self.assertEqual(a.checks, 4)
        self.assertEqual(a.failures, 1)
        self.assertAlmostEqual(a.uptime_pct, 75.0)
        self.assertTrue(a.last_ok)

    def test_empty_window(self):
        a = availability([], "api")
        self.assertEqual(a.checks, 0)
        self.assertIsNone(a.last_ok)

    def test_avg_latency_uses_successes_only(self):
        entries = [entry("api", True, 1, latency=100.0),
                   entry("api", False, 2, latency=0.0),
                   entry("api", True, 3, latency=300.0)]
        self.assertAlmostEqual(availability(entries, "api").avg_latency_ms, 200.0)

    def test_all_failing(self):
        entries = [entry("api", False, 1), entry("api", False, 2)]
        a = availability(entries, "api")
        self.assertEqual(a.uptime_pct, 0.0)
        self.assertEqual(a.avg_latency_ms, 0.0)


class TestFleet(unittest.TestCase):
    def test_rolls_up_every_target_sorted(self):
        entries = [entry("db", True, 1), entry("api", False, 1),
                   entry("api", True, 2)]
        rolls = fleet(entries)
        self.assertEqual([a.name for a in rolls], ["api", "db"])
        self.assertEqual(rolls[0].checks, 2)
        self.assertEqual(rolls[1].failures, 0)


class TestIncidents(unittest.TestCase):
    def test_single_failure_opens_and_closes(self):
        entries = [entry("api", True, 1), entry("api", False, 2),
                   entry("api", True, 3)]
        inc = incidents(entries, "api")
        self.assertEqual(len(inc), 1)
        self.assertEqual(inc[0].started_at, 2)
        self.assertEqual(inc[0].ended_at, 3)
        self.assertFalse(inc[0].open)

    def test_open_incident_when_still_failing(self):
        entries = [entry("api", False, 1), entry("api", False, 2)]
        inc = incidents(entries, "api")
        self.assertTrue(inc[0].open)
        self.assertEqual(inc[0].checks_failed, 2)

    def test_threshold_ignores_flaps(self):
        entries = [entry("api", False, 1), entry("api", True, 2),
                   entry("api", False, 3), entry("api", False, 4),
                   entry("api", True, 5)]
        th2 = incidents(entries, "api", threshold=2)
        self.assertEqual(len(th2), 1)
        self.assertEqual((th2[0].started_at, th2[0].ended_at, th2[0].checks_failed),
                         (3, 5, 2))
        self.assertEqual(incidents(entries, "api", threshold=3), [])

    def test_bad_threshold_rejected(self):
        with self.assertRaises(ValueError):
            incidents([], "api", threshold=0)

    def test_ignores_other_targets(self):
        entries = [entry("db", False, 1), entry("api", True, 2)]
        self.assertEqual(incidents(entries, "api"), [])


class TestPercentile(unittest.TestCase):
    def test_nearest_rank(self):
        self.assertEqual(percentile([10, 20, 30, 40], 50), 20)
        self.assertEqual(percentile([10, 20, 30, 40], 95), 40)
        self.assertEqual(percentile([10, 20, 30, 40], 100), 40)

    def test_empty_and_single(self):
        self.assertEqual(percentile([], 95), 0.0)
        self.assertEqual(percentile([42], 50), 42)

    def test_bad_pct_rejected(self):
        for bad in (0, -5, 101):
            with self.assertRaises(ValueError):
                percentile([1], bad)

    def test_latency_percentiles_skip_failures(self):
        entries = [entry("api", True, 1, latency=100.0),
                   entry("api", False, 2, latency=0.0),
                   entry("api", True, 3, latency=300.0)]
        pcts = latency_percentiles(entries, "api")
        self.assertEqual(pcts[50], 100.0)
        self.assertEqual(pcts[95], 300.0)


class TestTrend(unittest.TestCase):
    def test_buckets_with_gap_visible(self):
        entries = [entry("api", True, 10), entry("api", False, 20),
                   entry("api", True, 110)]
        buckets = trend(entries, "api", bucket_seconds=100, start=0, end=200)
        self.assertEqual(len(buckets), 2)
        self.assertEqual((buckets[0].checks, buckets[0].failures), (2, 1))
        self.assertAlmostEqual(buckets[0].uptime_pct, 50.0)
        self.assertAlmostEqual(buckets[1].uptime_pct, 100.0)

    def test_empty_bucket_reported_not_skipped(self):
        entries = [entry("api", True, 5)]
        buckets = trend(entries, "api", bucket_seconds=10, start=0, end=30)
        self.assertEqual([b.checks for b in buckets], [1, 0, 0])

    def test_ignores_other_targets(self):
        entries = [entry("db", False, 5), entry("api", True, 5)]
        buckets = trend(entries, "api", bucket_seconds=10, start=0, end=10)
        self.assertEqual(buckets[0].failures, 0)

    def test_bad_params_rejected(self):
        with self.assertRaises(ValueError):
            trend([], "api", bucket_seconds=0, start=0, end=10)
        with self.assertRaises(ValueError):
            trend([], "api", bucket_seconds=10, start=10, end=10)


class TestCurrentState(unittest.TestCase):
    def test_states(self):
        self.assertEqual(current_state([], "api"), "unknown")
        self.assertEqual(current_state([entry("api", True, 1)], "api"), "up")
        self.assertEqual(current_state([entry("api", True, 1),
                                        entry("api", False, 2)], "api"), "down")


if __name__ == "__main__":
    unittest.main()
