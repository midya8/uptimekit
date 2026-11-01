import unittest

from uptimekit.history import Entry
from uptimekit.statuspage import render


def entry(name, ok, at, detail="status 200"):
    return Entry(name, "http", ok, 10.0, detail, at, 200 if ok else 503, "")


class TestRender(unittest.TestCase):
    def test_all_operational_banner(self):
        entries = [entry("api", True, 100.0), entry("db", True, 100.0)]
        page = render(entries, ["api", "db"], "24h", now=200.0)
        self.assertIn("All systems operational", page)
        self.assertIn("100.00% uptime", page)
        self.assertIn("state up", page)

    def test_down_banner_names_targets(self):
        entries = [entry("api", False, 100.0), entry("db", True, 100.0)]
        page = render(entries, ["api", "db"], "24h", now=200.0)
        self.assertIn("1 system down: api", page)
        self.assertIn("state down", page)

    def test_unknown_state_without_history(self):
        page = render([], ["api"], "24h", now=200.0)
        self.assertIn("state unknown", page)
        self.assertIn("no checks recorded yet", page)
        self.assertIn("never checked", page)

    def test_uptime_percentage_in_page(self):
        entries = [entry("api", True, 1.0), entry("api", True, 2.0),
                   entry("api", False, 3.0)]
        page = render(entries, ["api"], "24h", now=10.0)
        self.assertIn("66.67% uptime", page)

    def test_html_is_escaped(self):
        entries = [entry("api", False, 1.0, detail="<script>alert(1)</script>")]
        page = render(entries, ["api"], "24h", now=10.0)
        self.assertNotIn("<script>alert", page)
        self.assertIn("&lt;script&gt;", page)
        page2 = render(entries, ["<b>x</b>"], "24h", now=10.0)
        self.assertNotIn("<b>x</b>", page2.replace("<body>", "").replace("<br>", ""))

    def test_tick_strip_reflects_recent_checks(self):
        entries = [entry("api", i % 3 != 0, float(i)) for i in range(10)]
        page = render(entries, ["api"], "24h", now=20.0)
        self.assertEqual(page.count('class="tick ok"'), 6)
        self.assertEqual(page.count('class="tick fail"'), 4)

    def test_tick_strip_pads_to_width(self):
        entries = [entry("api", True, 1.0)]
        page = render(entries, ["api"], "24h", now=10.0)
        total_ticks = page.count('class="tick ok"') + page.count('class="tick fail"')
        bare = page.count('<div class="tick"></div>')
        self.assertEqual(total_ticks + bare, 30)

    def test_deterministic_output(self):
        entries = [entry("api", True, 1.0), entry("db", False, 2.0)]
        self.assertEqual(render(entries, ["api", "db"], "1h", now=10.0),
                         render(entries, ["api", "db"], "1h", now=10.0))

    def test_footer_carries_window_and_time(self):
        page = render([], ["api"], "7d", now=0.0)
        self.assertIn("window: 7d", page)


if __name__ == "__main__":
    unittest.main()
