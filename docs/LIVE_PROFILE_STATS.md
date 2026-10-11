# Live GitHub profile graphics

The Python endpoints in `api/impact.py` and `api/activity.py` compute the
same graphics as the checked-in profile assets **when an HTTP request reaches
the server**.

The profile README still points to the working daily snapshot images until a
deployed, verified URL is available. This is intentional: GitHub profile READMEs
cannot run JavaScript, and GitHub Pages cannot execute Python server-side.

## Deploy to Vercel

1. Connect the public repository `fjtrujy/fjtrujy` to a Vercel project. Keep
   the project root as `.`. No build command or Python dependencies are
   necessary; Vercel discovers `api/*.py` as Python functions.
2. Add a **server-side** environment variable named `PROFILE_GITHUB_TOKEN`
   in the Vercel project settings. Use a **separately created, least-privilege,
   read-only GitHub token**, with access to public data. Never paste a token
   into the README, a deployment URL, a Git commit, or a public environment
   variable. The API uses GitHub GraphQL for contributions and REST Search for
   public pull requests.
3. Deploy to production and verify both:
   - `https://YOUR-VERIFIED-HOST/api/impact`
   - `https://YOUR-VERIFIED-HOST/api/activity`

   Both must return HTTP 200, `Content-Type: image/svg+xml`, and nonempty SVG
   graphics. See `tests/test_live_profile_stats.py` for offline tests.
4. **Only after verification**, change the corresponding `<img src>` entries
   in `README.md` from `./assets/impact-stats.svg` and
   `./assets/activity-stats.svg` to the two verified HTTPS URLs. Update the
   description below the cards to link here rather than claim they update
   only through GitHub Actions.
5. Once the live images render reliably from GitHub's profile, remove the
   scheduled `profile-stats.yml` workflow if you do not want snapshots.
   It can remain as a fallback while the live endpoint is being verified.

An installed Vercel app or configured Vercel account is required to deploy.
Code alone does **not** create or authorize hosting or a working HTTPS endpoint.

## Runtime semantics

- **Public PRs:** total authored public PRs from GitHub's public Search API.
- **Merged PRs:** merged public PRs from the same Search API.
- **Upstream repos:** distinct repositories *outside* `fjtrujy` where an
  authored public PR was merged. This metric is computed by reading the
  full paginated search result. It is not GitHub's smaller
  `repositoriesContributedTo` metric and is not hardcoded in the SVG.
- **Commit contributions:** sum of GitHub's yearly contribution totals,
  from account creation through the current year; not a raw commit search.
- **Activity calendar:** GitHub contributions over the past 365 days.
- **Primary languages:** one vote per non-fork, non-archived public repository
  for its dominant language according to GitHub.

The server computes data on a Vercel CDN cache miss. The response uses
`s-maxage=3600` and `stale-while-revalidate=86400` to reduce GitHub API
pressure and keep warm requests fast. Failed requests return HTTP 503 with
`no-store` and without disclosing credentials.

**Important:** GitHub separately proxies and caches external README images
through Camo. Consequently, merely *visiting* the profile cannot guarantee
a fresh GitHub API call or an immediate change in the image. This limitation
also applies to third-party live stats services.

For genuinely immediate inspection, visit the deployed image URL directly;
CDN response caching can still apply. GitHub's own activity UI provides the
most direct view of its latest recorded contributions.

## Development

```sh
python3 -m unittest discover -s tests -v
GH_TOKEN="$(gh auth token)" python3 -c \
  'from scripts.live_profile_stats import render_impact; print(render_impact()[:200])'
```

The second command is for local use only. Do not reuse a broad developer token
as the hosting credential.
