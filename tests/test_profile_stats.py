"""Offline regression tests for the GitHub profile graphics generator."""
import datetime as dt
import importlib.util
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

PATH = Path(__file__).resolve().parents[1] / "scripts" / "update_profile_stats.py"
spec = importlib.util.spec_from_file_location("profile_stats", PATH)
stats = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stats)


class SearchFixture:
    def __init__(self):
        self.queries = []

    def search(self, query, page=1):
        self.queries.append((query, page))
        assert "is:public" in query
        if "created:2026-01-01..2026-01-04" in query:
            # An overloaded range must be split, not silently truncated.
            return {"total_count": 1000, "incomplete_results": False, "items": []}
        if "created:2026-01-01..2026-01-02" in query:
            return {"total_count": 1, "incomplete_results": False, "items": [
                {"repository_url": "https://api.github.com/repos/ps2dev/ps2sdk"}]}
        if "created:2026-01-03..2026-01-04" in query:
            return {"total_count": 3, "incomplete_results": False, "items": [
                {"repository_url": "https://api.github.com/repos/ps2dev/ps2sdk"},
                {"repository_url": "https://api.github.com/repos/pspdev/pspsdk"},
                {"repository_url": "https://api.github.com/repos/fjtrujy/NJEMU"}]}
        raise AssertionError("Unexpected search query: " + query)


class LanguageFixture:
    def graphql(self, query, variables):
        if variables["after"] is None:
            return {"user": {"repositories": {
                "pageInfo": {"hasNextPage": True, "endCursor": "page2"},
                "nodes": [
                    {"isFork": False, "isArchived": False, "languages": {"edges": [
                        {"size": 90000, "node": {"name": "C"}},
                        {"size": 200, "node": {"name": "Swift"}},
                    ]}},
                    {"isFork": True, "isArchived": False, "languages": {"edges": [
                        {"size": 100000000, "node": {"name": "C++"}},
                    ]}},
                    {"isFork": False, "isArchived": True, "languages": {"edges": [
                        {"size": 50, "node": {"name": "Rust"}},
                    ]}},
                ],
            }}}
        return {"user": {"repositories": {
            "pageInfo": {"hasNextPage": False, "endCursor": None},
            "nodes": [
                {"isFork": False, "isArchived": False, "languages": {"edges": [
                    {"size": 42, "node": {"name": "Swift"}},
                ]}},
                {"isFork": False, "isArchived": False, "languages": {"edges": [
                    {"size": 99, "node": {"name": "C"}},
                ]}},
            ],
        }}}


class ProfileStatsTests(unittest.TestCase):
    def test_search_splits_overloaded_range_and_deduplicates_external_repos(self):
        api = SearchFixture()
        count = stats.external_merged_repos(api, "fjtrujy",
                                            dt.date(2026, 1, 1),
                                            dt.date(2026, 1, 4))
        self.assertEqual(count, 2)
        self.assertEqual(len(api.queries), 3)

    def test_contribution_streak_allows_for_incomplete_today(self):
        today = dt.date(2026, 10, 11)
        days = {
            today: 0,
            today - dt.timedelta(days=1): 2,
            today - dt.timedelta(days=2): 1,
            today - dt.timedelta(days=3): 0,
        }
        self.assertEqual(stats.streak_count(days, today), 2)
        days[today] = 1
        self.assertEqual(stats.streak_count(days, today), 3)

    def test_primary_language_counts_repositories_not_bytes(self):
        self.assertEqual(stats.get_languages(LanguageFixture(), "fjtrujy"), [("C", 2), ("Swift", 1)])

    def test_svg_generation_produces_accessible_xml(self):
        today = dt.date(2026, 10, 11)
        days = {today - dt.timedelta(days=364 - i): i % 12
                for i in range(365)}
        impact = stats.impact_svg(
            {"authored": 1000, "merged": 900, "external": 75},
            {2025: 200, 2026: 300},
            "2026-10-11 UTC",
        )
        activity = stats.activity_svg(
            days, [("C", 500), ("Swift", 300), ("TypeScript", 200)],
            "2026-10-11 UTC",
        )
        for svg in [impact, activity]:
            xml = ET.fromstring(svg)
            self.assertIn("title", svg)
            self.assertIn("description", svg)
            self.assertEqual(xml.attrib["role"], "img")
        self.assertIn("1,000", impact)
        self.assertIn("500", impact)
        self.assertIn("Swift", activity)

    def test_xml_escapes_untrusted_language_names(self):
        now = dt.date(2026, 10, 11)
        days = {now - dt.timedelta(days=i): 1 for i in range(365)}
        svg = stats.activity_svg(days, [("<test>&", 123)], "2026-10-11 UTC")
        ET.fromstring(svg)
        self.assertIn("&lt;test&gt;&amp;", svg)


if __name__ == "__main__":
    unittest.main()
