"""On-demand profile SVG generation for a public serverless image endpoint.

Both images are recomputed on a cache miss from GitHub's API. They can be
cached by the hosting CDN and independently by GitHub's image proxy; GitHub
does not guarantee that visiting a README triggers an origin request.
"""
import datetime as dt
from concurrent.futures import ThreadPoolExecutor
import math
import os
from urllib.parse import urlencode

from scripts import update_profile_stats as graphics


def make_api():
    # Never include this credential in a generated SVG, URL, error page or log.
    return graphics.GitHub(
        os.getenv("PROFILE_GITHUB_TOKEN") or os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
    )


def get_live_pr_metrics(api, user):
    if user != graphics.USER:
        raise ValueError("Unexpected account name")
    public = "is:pr is:public author:" + user
    merged_query = "is:pr is:merged is:public author:" + user

    with ThreadPoolExecutor(max_workers=2) as executor:
        authored_future = executor.submit(api.search, public)
        merged_future = executor.submit(api.search, merged_query)
        authored = authored_future.result()["total_count"]
        merged_first = merged_future.result()

    repositories = set()

    def fetch_window(start, end, first=None):
        query = merged_query
        if start is not None:
            query += " created:{}..{}".format(start.isoformat(), end.isoformat())
        first = first if first is not None else api.search(query)
        count = first["total_count"]
        if count > 1000:
            if start == end:
                raise RuntimeError("GitHub search exceeds 1,000 results for one day")
            midpoint = start + (end - start) // 2
            fetch_window(start, midpoint)
            fetch_window(midpoint + dt.timedelta(days=1), end)
            return

        pages = math.ceil(count / 100)
        results = [first]
        if pages > 1:
            # Search has a separate secondary rate limit. Keep concurrency
            # modest and cache the final SVG at the CDN for an hour.
            with ThreadPoolExecutor(max_workers=5) as executor:
                results += list(executor.map(
                    lambda page: api.search(query, page),
                    range(2, pages + 1),
                ))
        for result in results:
            for item in result["items"]:
                repository = item["repository_url"].split("/repos/", 1)[-1]
                if repository.split("/", 1)[0].casefold() != user.casefold():
                    repositories.add(repository.casefold())

    if merged_first["total_count"] <= 1000:
        fetch_window(None, None, merged_first)
    else:
        fetch_window(dt.date(2014, 1, 1), dt.datetime.now(dt.timezone.utc).date())

    return {
        "authored": authored,
        "merged": merged_first["total_count"],
        "external": len(repositories),
    }


def get_live_languages(api, user):
    """Use REST's primary-language field, fetching public repos in parallel."""
    if user != graphics.USER:
        raise ValueError("Unexpected account name")
    totals = {}
    for start in range(1, 32, 3):
        def fetch(page):
            query = urlencode({
                "type": "owner",
                "per_page": 100,
                "page": page,
            })
            return api.request("{}/users/{}/repos?{}".format(
                graphics.REST, user, query))

        with ThreadPoolExecutor(max_workers=3) as executor:
            results = list(executor.map(fetch, range(start, start + 3)))
        for repos in results:
            for repo in repos:
                if repo["fork"] or repo["archived"] or not repo["language"]:
                    continue
                language = repo["language"]
                totals[language] = totals.get(language, 0) + 1
            if len(repos) < 100:
                return sorted(totals.items(), key=lambda pair: (-pair[1], pair[0]))
    raise RuntimeError("GitHub repository pagination exceeded safety limit")


def render_impact(api=None, now=None):
    api = api or make_api()
    now = now or dt.datetime.now(dt.timezone.utc)
    with ThreadPoolExecutor(max_workers=2) as executor:
        commits_future = executor.submit(graphics.get_commit_history, api, graphics.USER, now)
        prs_future = executor.submit(get_live_pr_metrics, api, graphics.USER)
        counts = commits_future.result()
        prs = prs_future.result()
    return graphics.impact_svg(
        prs, counts, now.strftime("%Y-%m-%d UTC")
    )


def render_activity(api=None, now=None):
    api = api or make_api()
    now = now or dt.datetime.now(dt.timezone.utc)
    with ThreadPoolExecutor(max_workers=2) as executor:
        calendar_future = executor.submit(graphics.get_calendar, api, graphics.USER, now)
        languages_future = executor.submit(get_live_languages, api, graphics.USER)
        calendar = calendar_future.result()
        languages = languages_future.result()
    return graphics.activity_svg(
        calendar, languages, now.strftime("%Y-%m-%d UTC")
    )
