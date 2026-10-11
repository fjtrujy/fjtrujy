"""Offline tests for on-demand GitHub profile SVG endpoints."""
import datetime as dt
import io
import unittest
from unittest.mock import patch
from xml.etree import ElementTree

from scripts import live_profile_stats as live
from scripts.live_profile_http import serve_svg


class PRFixture:
    def search(self, query, page=1):
        if "is:merged" not in query:
            return {"total_count": 1200, "items": [], "incomplete_results": False}
        if "created:" not in query:
            return {"total_count": 3, "items": [
                {"repository_url": "https://api.github.com/repos/ps2dev/ps2sdk"},
                {"repository_url": "https://api.github.com/repos/pspdev/pspsdk"},
                {"repository_url": "https://api.github.com/repos/fjtrujy/NJEMU"},
            ]}
        raise AssertionError("Unexpected pagination")


class LanguageFixture:
    def request(self, url, payload=None):
        page = int(url.rsplit("page=", 1)[-1])
        if page == 1:
            return [
                {"fork": False, "archived": False, "language": "C"},
                {"fork": False, "archived": False, "language": "Swift"},
                {"fork": False, "archived": True, "language": "Ruby"},
                {"fork": True, "archived": False, "language": "Python"},
            ]
        return []


class LargeSearchFixture:
    def search(self, query, page=1):
        if "is:merged" not in query:
            return {"total_count": 3000}
        if "created:" not in query:
            return {"total_count": 1001}
        if "created:2014-01-01..2026-01-01" in query:
            return {"total_count": 1001}
        if "created:2014-01-01..2020-01-01" in query:
            return {"total_count": 1, "items": [
                {"repository_url": "https://api.github.com/repos/ps2dev/ps2sdk"}]}
        if "created:2020-01-02..2026-01-01" in query:
            return {"total_count": 1, "items": [
                {"repository_url": "https://api.github.com/repos/pspdev/pspsdk"}]}
        raise AssertionError(query)


class StubHTTP:
    def __init__(self):
        self.code = None
        self.headers = {}
        self.wfile = io.BytesIO()

    def send_response(self, code):
        self.code = code

    def send_header(self, key, value):
        self.headers[key] = value

    def end_headers(self):
        pass


class LiveStatsTests(unittest.TestCase):
    def test_external_repositories_stay_exact_not_graphql_approximation(self):
        counts = live.get_live_pr_metrics(PRFixture(), "fjtrujy")
        self.assertEqual(counts, {"authored": 1200, "merged": 3, "external": 2})

    def test_search_overflow_splits_by_date(self):
        real_datetime = dt.datetime
        with patch.object(live.dt, "datetime") as mocked:
            mocked.now.return_value = real_datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
            # The mocked date matches a 2014-2026 search partition.
            counts = live.get_live_pr_metrics(LargeSearchFixture(), "fjtrujy")
        self.assertEqual(counts["external"], 2)

    def test_primary_languages_exclude_forks_and_archives(self):
        languages = live.get_live_languages(LanguageFixture(), "fjtrujy")
        self.assertEqual(languages, [("C", 1), ("Swift", 1)])

    def test_live_impact_reuses_correct_svg_design(self):
        now = dt.datetime(2026, 10, 11, tzinfo=dt.timezone.utc)
        with patch.object(live.graphics, "get_commit_history", return_value={2025: 15}), \
             patch.object(live, "get_live_pr_metrics",
                          return_value={"authored": 10, "merged": 8, "external": 4}):
            svg = live.render_impact(api=object(), now=now)
        self.assertIn("UPSTREAM REPOS", svg)
        self.assertIn("COMMIT CONTRIBUTIONS", svg)
        ElementTree.fromstring(svg)

    def test_http_success_is_svg_and_cacheable(self):
        request = StubHTTP()
        serve_svg(request, lambda: "<svg></svg>")
        self.assertEqual(request.code, 200)
        self.assertEqual(request.wfile.getvalue(), b"<svg></svg>")
        self.assertIn("image/svg+xml", request.headers["Content-Type"])
        self.assertIn("s-maxage=3600", request.headers["Cache-Control"])
        self.assertEqual(request.headers["X-Content-Type-Options"], "nosniff")

    def test_http_error_is_not_cached_or_leaked(self):
        request = StubHTTP()
        def fail():
            raise RuntimeError("private API token should never appear")
        with patch("scripts.live_profile_http.logging.exception"):
            serve_svg(request, fail)
        self.assertEqual(request.code, 503)
        self.assertEqual(request.headers["Cache-Control"], "no-store")
        self.assertNotIn(b"private API token", request.wfile.getvalue())


if __name__ == "__main__":
    unittest.main()
