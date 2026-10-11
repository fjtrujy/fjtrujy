#!/usr/bin/env python3
"""Generate self-hosted GitHub profile graphics from public GitHub API data.

Usage:
    GH_TOKEN="$(gh auth token)" python3 scripts/update_profile_stats.py

The generated graphics intentionally distinguish authored/merged public PRs,
external repositories reached through merged PRs, and GitHub-counted commit
contributions. These are different measures; none is an all-commits search.
"""
import datetime as dt
import html
import json
import math
import os
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

USER = "fjtrujy"
ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
REST = "https://api.github.com"
GRAPHQL = REST + "/graphql"
SPLIT_THRESHOLD = 900
BG = "#071421"
PANEL = "#112b3d"
STROKE = "#2c5668"
TEXT = "#f0f7fa"
MUTED = "#9bb7c3"
MINT = "#55e5bb"
AMBER = "#f8b878"
PALETTE = ["#1b3546", "#28675f", "#2e987e", "#55d6b5", "#b1f4df"]


class GitHub:
    def __init__(self, token):
        if not token:
            raise ValueError("GH_TOKEN or GITHUB_TOKEN is required")
        self.token = token

    def request(self, url, payload=None):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {
            "Authorization": "Bearer " + self.token,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "fjtrujy-profile-metrics",
        }
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers)
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=45) as response:
                    return json.load(response)
            except urllib.error.HTTPError as exc:
                if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                    raise RuntimeError("GitHub API request failed (HTTP {})".format(exc.code)) from exc
                time.sleep(2 ** attempt)
        raise RuntimeError("GitHub API request failed")

    def graphql(self, query, variables=None):
        result = self.request(GRAPHQL, {"query": query, "variables": variables or {}})
        if result.get("errors"):
            raise RuntimeError("GitHub GraphQL error: " + json.dumps(result["errors"]))
        return result["data"]

    def search(self, query, page=1):
        qs = urllib.parse.urlencode({"q": query, "per_page": 100, "page": page})
        result = self.request(REST + "/search/issues?" + qs)
        if result["incomplete_results"]:
            raise RuntimeError("GitHub returned incomplete search results for " + query)
        return result


def get_commit_history(api, user, now):
    created = api.graphql(
        "query($login:String!) { user(login:$login) { createdAt } }",
        {"login": user},
    )["user"]["createdAt"]
    first_year = int(created[:4])
    years = list(range(first_year, now.year + 1))
    fields = []
    for year in years:
        end = "{}-12-31T23:59:59Z".format(year)
        if year == now.year:
            end = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        fields.append(
            'y{0}: contributionsCollection(from:"{0}-01-01T00:00:00Z", '
            'to:"{1}") {{ totalCommitContributions }}'.format(year, end)
        )
    query = 'query {{ user(login:"{0}") {{ {1} }} }}'.format(user, " ".join(fields))
    data = api.graphql(query)["user"]
    counts = {year: data["y{}".format(year)]["totalCommitContributions"] for year in years}
    return counts


def get_calendar(api, user, now):
    start = now.date() - dt.timedelta(days=364)
    query = (
        'query($login:String!, $from:DateTime!, $to:DateTime!) {'
        'user(login:$login) { contributionsCollection(from:$from,to:$to) {'
        'contributionCalendar { weeks { contributionDays { date contributionCount } } }'
        '} } }'
    )
    data = api.graphql(query, {
        "login": user,
        "from": start.isoformat() + "T00:00:00Z",
        "to": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    })
    days = {}
    for week in data["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]:
        for day in week["contributionDays"]:
            date = dt.date.fromisoformat(day["date"])
            if start <= date <= now.date():
                days[date] = day["contributionCount"]
    if len(days) < 360:
        raise RuntimeError("Incomplete contribution calendar")
    return {start + dt.timedelta(days=i): days.get(start + dt.timedelta(days=i), 0)
            for i in range(365)}


def external_merged_repos(api, user, first_day, today):
    # GitHub caps search pagination at 1,000. Split dense date ranges so the
    # repository count stays accurate as the user's PR history grows.
    base = "is:pr is:merged is:public author:" + user
    repos = set()

    def scan(start, end):
        query = base + " created:{}..{}".format(start.isoformat(), end.isoformat())
        first = api.search(query)
        count = first["total_count"]
        if count > SPLIT_THRESHOLD:
            if start == end:
                raise RuntimeError("More than 900 merged PRs on one day; cannot paginate safely")
            midpoint = start + (end - start) // 2
            scan(start, midpoint)
            scan(midpoint + dt.timedelta(days=1), end)
            return
        pages = math.ceil(count / 100)
        for page in range(1, pages + 1):
            result = first if page == 1 else api.search(query, page)
            for pr in result["items"]:
                repository = pr["repository_url"].split("/repos/", 1)[-1]
                if repository.split("/", 1)[0].casefold() != user.casefold():
                    repos.add(repository.casefold())

    scan(first_day, today)
    return len(repos)


def get_pr_metrics(api, user, today, first_year):
    authored = api.search("is:pr is:public author:" + user)["total_count"]
    merged = api.search("is:pr is:merged is:public author:" + user)["total_count"]
    external = external_merged_repos(api, user, dt.date(first_year, 1, 1), today)
    return {"authored": authored, "merged": merged, "external": external}


def get_languages(api, user):
    query = """
    query($login:String!, $after:String) {
      user(login:$login) {
        repositories(first:100, after:$after, privacy:PUBLIC,
                     ownerAffiliations:OWNER, orderBy:{field:PUSHED_AT,direction:DESC}) {
          pageInfo { hasNextPage endCursor }
          nodes {
            isFork isArchived
            languages(first:15, orderBy:{field:SIZE,direction:DESC}) {
              edges { size node { name } }
            }
          }
        }
      }
    }
    """
    cursor = None
    totals = {}
    while True:
        result = api.graphql(query, {"login": user, "after": cursor})
        page = result["user"]["repositories"]
        for repo in page["nodes"]:
            if repo["isFork"] or repo["isArchived"]:
                continue
            # Each repository votes once for its largest language. Counting
            # bytes across all repositories would let one huge emulator dwarf
            # every smaller project and misrepresent the breadth of the work.
            edges = repo["languages"]["edges"]
            if edges:
                name = edges[0]["node"]["name"]
                totals[name] = totals.get(name, 0) + 1
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]
    return sorted(totals.items(), key=lambda pair: (-pair[1], pair[0]))


def esc(value):
    return html.escape(str(value), quote=True)


def svg_shell(height, body, title, description):
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="{height}" '
        'viewBox="0 0 1200 {height}" role="img" aria-labelledby="title description">'
        '<title id="title">{title}</title><desc id="description">{desc}</desc>'
        '<defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">'
        '<stop offset="0" stop-color="#071421"/>'
        '<stop offset="1" stop-color="#113449"/></linearGradient></defs>'
        '<rect width="1200" height="{height}" rx="22" fill="url(#bg)"/>'
        '<rect x="1" y="1" width="1198" height="{inner}" rx="21" '
        'fill="none" stroke="#2c5668" stroke-width="2"/>'
        '{body}</svg>'
    ).format(height=height, inner=height - 2, body=body,
             title=esc(title), desc=esc(description))
    ET.fromstring(svg)
    return svg + "\n"


def text(x, y, value, size=16, color=TEXT, weight=400, anchor=None, family="Arial, Helvetica, sans-serif"):
    attr = ' text-anchor="{}"'.format(anchor) if anchor else ""
    return (
        '<text x="{x}" y="{y}" fill="{color}" font-family="{family}" '
        'font-size="{size}" font-weight="{weight}"{attr}>{value}</text>'
    ).format(x=x, y=y, color=color, family=esc(family),
             size=size, weight=weight, attr=attr, value=esc(value))


def rect(x, y, width, height, fill, rx=0, stroke=None):
    outline = ' stroke="{}"'.format(stroke) if stroke else ""
    return '<rect x="{0}" y="{1}" width="{2}" height="{3}" rx="{4}" fill="{5}"{6}/>'.format(
        x, y, width, height, rx, fill, outline)


def impact_svg(prs, commit_history, date):
    count = sum(commit_history.values())
    cards = [
        ("PUBLIC PRs", prs["authored"], "Authored across GitHub", MINT),
        ("MERGED PRs", prs["merged"], "Accepted upstream & in own repos", AMBER),
        ("UPSTREAM REPOS", prs["external"], "External repos with merged PRs", "#79cdeb"),
        ("COMMIT CONTRIBUTIONS", count, "GitHub-counted history", MINT),
    ]
    parts = [
        text(47, 48, "OPEN SOURCE / IMPACT", 21, TEXT, 700),
        text(1154, 47, "UPDATED " + date, 12, MUTED, 700, "end"),
    ]
    for index, (name, number, detail, color) in enumerate(cards):
        x = 47 + 284 * index
        parts += [
            rect(x, 68, 258, 112, PANEL, 12, STROKE),
            rect(x + 17, 85, 3, 17, color, 1),
            text(x + 28, 99, name, 12, MUTED, 700),
            text(x + 19, 149, "{:,}".format(number), 40, color, 700),
            text(x + 19, 168, detail, 11, MUTED),
        ]
    parts.append(text(48, 206, "Public PRs only  /  Upstream = repositories outside my account  /  Commits follow GitHub's contribution rules", 12, MUTED))
    return svg_shell(226, "".join(parts), "Open-source impact metrics",
                     "Authored public pull requests: {}; merged public pull requests: {}; external repositories with a merged pull request: {}; GitHub-counted commit contributions: {}.".format(
                         prs["authored"], prs["merged"], prs["external"], count
                     ))


def streak_count(days, today):
    anchor = today if days.get(today, 0) else today - dt.timedelta(days=1)
    consecutive = 0
    while days.get(anchor, 0) > 0:
        consecutive += 1
        anchor -= dt.timedelta(days=1)
    return consecutive


def activity_svg(days, languages, date):
    begin, end = min(days), max(days)
    first_sunday = begin - dt.timedelta(days=(begin.weekday() + 1) % 7)
    weeks = ((end - first_sunday).days // 7) + 1
    if weeks > 54:
        raise RuntimeError("Unexpected number of calendar columns")
    parts = [
        text(46, 47, "GITHUB / ACTIVITY", 21, TEXT, 700),
        text(1154, 47, "LAST 365 DAYS  |  " + date, 12, MUTED, 700, "end"),
        text(47, 79, "Contribution calendar", 17, "#d0e4ea", 700),
        text(749, 79, "Primary project languages", 17, "#d0e4ea", 700),
        text(749, 98, "Public, non-fork, non-archived repositories", 12, MUTED),
        rect(728, 71, 1.5, 233, STROKE),
    ]
    last_month = None
    for week in range(weeks):
        top = first_sunday + dt.timedelta(days=week * 7)
        month = top.strftime("%b")
        if month != last_month and top.month != begin.month and top.day <= 7:
            parts.append(text(48 + 12 * week, 107, month, 11, MUTED))
        last_month = month
        for row in range(7):
            day = top + dt.timedelta(days=row)
            if day not in days:
                continue
            value = days[day]
            tier = 0 if value == 0 else (1 if value <= 2 else 2 if value <= 5 else 3 if value <= 12 else 4)
            parts.append(rect(48 + 12 * week, 119 + 17 * row, 10, 14, PALETTE[tier], 2))
    parts.extend([
        text(48, 257, "{} contributions".format(sum(days.values())), 16, MINT, 700),
        text(250, 257, "{} active days".format(sum(1 for v in days.values() if v)), 16, TEXT, 700),
        text(441, 257, "{}-day current streak".format(streak_count(days, end)), 16, AMBER, 700),
        text(48, 302, "Less", 11, MUTED),
    ])
    for i, color in enumerate(PALETTE):
        parts.append(rect(86 + i * 15, 291, 11, 11, color, 2))
    parts.append(text(167, 302, "More", 11, MUTED))
    total = sum(size for _, size in languages)
    top_languages = languages[:5]
    maximum = top_languages[0][1] if top_languages else 1
    for i, (language, size) in enumerate(top_languages):
        y = 123 + i * 36
        pct = 100.0 * size / total if total else 0
        parts += [
            text(749, y, language[:25], 14, TEXT, 700),
            text(1138, y, "{:.1f}%".format(pct), 13, MUTED, 700, "end"),
            rect(749, y + 7, 390, 7, "#193b4a", 3),
            rect(749, y + 7, max(2, int(390 * size / maximum)), 7,
                 [MINT, "#79cdeb", AMBER, "#79a4e8", "#b1f4df"][i], 3),
        ]
    if not top_languages:
        parts.append(text(749, 153, "No public language data", 14, MUTED))
    parts.append(text(748, 302, "One vote per repo, by its largest detected language.", 11, MUTED))
    return svg_shell(
        326, "".join(parts), "Public GitHub activity over the last year",
        "{} contributions, {} active days, {}-day current streak. Most common primary public repository languages: {}.".format(
            sum(days.values()), sum(bool(v) for v in days.values()),
            streak_count(days, end), ", ".join("{} {:.1f}%".format(n, 100.0 * s / total)
                                                       for n, s in top_languages) if total else "none"
        )
    )


def main():
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    api = GitHub(token)
    now = dt.datetime.now(dt.timezone.utc)
    history = get_commit_history(api, USER, now)
    days = get_calendar(api, USER, now)
    prs = get_pr_metrics(api, USER, now.date(), min(history))
    languages = get_languages(api, USER)
    if not history or not languages:
        raise RuntimeError("Public GitHub history or language data unexpectedly empty")
    date = now.strftime("%Y-%m-%d UTC")
    impact = impact_svg(prs, history, date)
    activity = activity_svg(days, languages, date)
    ASSETS.mkdir(exist_ok=True)
    (ASSETS / "impact-stats.svg").write_text(impact, encoding="utf-8")
    (ASSETS / "activity-stats.svg").write_text(activity, encoding="utf-8")
    print("Generated {} authored public PRs, {} merged, {} upstream repositories, "
          "{} GitHub-counted commit contributions; {} activity days, {} languages.".format(
              prs["authored"], prs["merged"], prs["external"], sum(history.values()),
              len(days), len(languages)))


if __name__ == "__main__":
    main()
