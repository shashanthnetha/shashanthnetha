#!/usr/bin/env python3
"""
build_dashboard.py — generates assets/dashboard.svg

Minimal, premium dark dashboard card with live GitHub statistics.
No theme. No costume. Just clean typography and real data.

Zero external dependencies. Python 3 standard library only.
"""

import sys
import os
import json
import urllib.request
from datetime import datetime, timezone
from xml.sax.saxutils import escape as xml_escape

GRAPHQL_URL = "https://api.github.com/graphql"
REST_URL = "https://api.github.com"


def esc(text) -> str:
    if text is None:
        return ""
    return xml_escape(str(text), entities={'"': "&quot;", "'": "&#39;"})


def relative_time(iso_date: str) -> str:
    if not iso_date:
        return "—"
    try:
        then = datetime.fromisoformat(iso_date.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        seconds = int((now - then).total_seconds())
        if seconds < 0:
            return "just now"
        if seconds < 3600:
            return f"{max(seconds // 60, 1)}m ago"
        if seconds < 86400:
            return f"{seconds // 3600}h ago"
        if seconds < 86400 * 30:
            return f"{seconds // 86400}d ago"
        return then.strftime("%b %Y")
    except Exception:
        return "—"


def compute_streaks(days: list) -> tuple:
    longest = run = 0
    for d in days:
        if d.get("contributionCount", 0) > 0:
            run += 1
            longest = max(longest, run)
        else:
            run = 0
    current = 0
    idx = len(days) - 1
    if idx >= 0 and days[idx].get("contributionCount", 0) == 0:
        idx -= 1
    while idx >= 0 and days[idx].get("contributionCount", 0) > 0:
        current += 1
        idx -= 1
    return current, longest


def pick_top_languages(repos: list, limit: int = 3) -> str:
    counts = {}
    for r in repos:
        lang = None
        if isinstance(r.get("primaryLanguage"), dict):
            lang = r["primaryLanguage"].get("name")
        elif isinstance(r.get("language"), str):
            lang = r.get("language")
        if lang:
            counts[lang] = counts.get(lang, 0) + 1
    if not counts:
        return "Python, TypeScript"
    return ", ".join(l for l, _ in sorted(counts.items(), key=lambda x: -x[1])[:limit])


def pick_latest_activity(repos: list) -> tuple:
    if not repos:
        return "—", "—", "—"
    top = repos[0]
    name = top.get("name", "—")
    msg = ""
    when = relative_time(top.get("pushedAt") or top.get("pushed_at") or "")
    ref = top.get("defaultBranchRef")
    if ref and isinstance(ref, dict):
        nodes = (ref.get("target") or {}).get("history", {}).get("nodes", [])
        if nodes:
            msg = nodes[0].get("message", "").split("\n")[0]
            when = relative_time(nodes[0].get("committedDate", ""))
    if len(msg) > 40:
        msg = msg[:37] + "..."
    return name, msg, when


def fetch_live(username: str, token: str) -> dict:
    query = """
    query($login: String!) {
      user(login: $login) {
        name createdAt
        followers { totalCount }
        following { totalCount }
        pullRequests(first: 1) { totalCount }
        issues(first: 1) { totalCount }
        contributionsCollection {
          totalCommitContributions
          contributionCalendar {
            totalContributions
            weeks { contributionDays { date contributionCount } }
          }
        }
        repositories(first: 100, ownerAffiliations: OWNER, isFork: false,
                      orderBy: {field: PUSHED_AT, direction: DESC}) {
          totalCount
          nodes {
            name stargazerCount forkCount pushedAt
            primaryLanguage { name }
            defaultBranchRef {
              target { ... on Commit { history(first: 1) { nodes { message committedDate } } } }
            }
          }
        }
      }
    }
    """
    body = json.dumps({"query": query, "variables": {"login": username}}).encode()
    req = urllib.request.Request(GRAPHQL_URL, data=body, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": f"{username}-dashboard",
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        payload = json.load(resp)
    if "errors" in payload:
        raise RuntimeError(payload["errors"])

    u = payload["data"]["user"]
    cc = u.get("contributionsCollection") or {}
    cal = cc.get("contributionCalendar") or {}
    days = [d for w in (cal.get("weeks") or []) for d in w.get("contributionDays", [])]
    cur_streak, long_streak = compute_streaks(days)
    repos = u.get("repositories", {}).get("nodes", [])
    active_repo, commit_msg, active_when = pick_latest_activity(repos)

    return {
        "username": username,
        "name": u.get("name") or username,
        "followers": u.get("followers", {}).get("totalCount", 0),
        "following": u.get("following", {}).get("totalCount", 0),
        "repos": u.get("repositories", {}).get("totalCount", 0),
        "stars": sum(r.get("stargazerCount", 0) for r in repos),
        "forks": sum(r.get("forkCount", 0) for r in repos),
        "prs": u.get("pullRequests", {}).get("totalCount", 0),
        "issues": u.get("issues", {}).get("totalCount", 0),
        "contributions": cal.get("totalContributions", 0),
        "commits": cc.get("totalCommitContributions", 0),
        "streak": cur_streak,
        "longest_streak": long_streak,
        "languages": pick_top_languages(repos),
        "active_repo": active_repo,
        "commit_msg": commit_msg,
        "active_when": active_when,
        "live": True,
    }


def fetch_offline(username: str) -> dict:
    def get(path):
        req = urllib.request.Request(f"{REST_URL}{path}", headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"{username}-dashboard",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.load(resp)

    try:
        user = get(f"/users/{username}")
        repos = get(f"/users/{username}/repos?per_page=100&sort=pushed")
        non_forks = [r for r in repos if not r.get("fork")]
        active_repo, commit_msg, active_when = "—", "", "—"
        if non_forks:
            active_repo = non_forks[0].get("name", "—")
            active_when = relative_time(non_forks[0].get("pushed_at"))

        return {
            "username": username,
            "name": user.get("name") or username,
            "followers": user.get("followers", 0),
            "following": user.get("following", 0),
            "repos": user.get("public_repos", 0),
            "stars": sum(r.get("stargazers_count", 0) for r in repos),
            "forks": sum(r.get("forks_count", 0) for r in repos),
            "prs": None, "issues": None,
            "contributions": None, "commits": None,
            "streak": None, "longest_streak": None,
            "languages": pick_top_languages(repos),
            "active_repo": active_repo,
            "commit_msg": commit_msg,
            "active_when": active_when,
            "live": False,
        }
    except Exception as err:
        sys.stderr.write(f"Offline fetch failed: {err}\n")
        return {
            "username": username, "name": "Shashanth Netha",
            "followers": 10, "following": 17, "repos": 31,
            "stars": 50, "forks": 2,
            "prs": None, "issues": None,
            "contributions": None, "commits": None,
            "streak": None, "longest_streak": None,
            "languages": "TypeScript, Python",
            "active_repo": "—", "commit_msg": "", "active_when": "—",
            "live": False,
        }


def v(val, suffix=""):
    """Format metric value."""
    if val is None:
        return "—"
    if isinstance(val, int):
        return f"{val:,}{suffix}"
    return str(val)


def render_svg(d: dict) -> str:
    sans = "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"
    mono = "SFMono-Regular,Consolas,'Liberation Mono',Menlo,monospace"
    now = datetime.now(timezone.utc).strftime("%b %d, %Y · %H:%M UTC")

    # Metrics grid: 3 columns × 4 rows
    metrics = [
        ("REPOSITORIES", v(d["repos"]),       "STARS", v(d["stars"]),         "FORKS", v(d["forks"])),
        ("CONTRIBUTIONS", v(d["contributions"]), "COMMITS", v(d["commits"]),   "STREAK", v(d["streak"], "d") if d["streak"] is not None else "—"),
        ("PULL REQUESTS", v(d["prs"]),        "ISSUES", v(d["issues"]),       "LONGEST STREAK", v(d["longest_streak"], "d") if d["longest_streak"] is not None else "—"),
        ("FOLLOWERS", v(d["followers"]),      "FOLLOWING", v(d["following"]),  "LANGUAGES", esc(d["languages"])),
    ]

    col_x = [60, 320, 580]
    row_start = 70
    row_h = 72

    rows_svg = []
    for row_i, row in enumerate(metrics):
        y = row_start + row_i * row_h
        for col_i in range(3):
            label = row[col_i * 2]
            value = row[col_i * 2 + 1]
            x = col_x[col_i]
            rows_svg.append(
                f'<text x="{x}" y="{y}" font-family="{mono}" font-size="10" font-weight="500" fill="#525252" letter-spacing="1.5">{label}</text>'
                f'<text x="{x}" y="{y + 24}" font-family="{sans}" font-size="22" font-weight="600" fill="#ededed">{value}</text>'
            )

    # Active repo section
    active_y = row_start + 4 * row_h + 6
    active_label = f'{esc(d["active_repo"])}'
    active_detail = ""
    if d["commit_msg"]:
        active_detail = f'&quot;{esc(d["commit_msg"])}&quot; · {esc(d["active_when"])}'
    elif d["active_when"] != "—":
        active_detail = esc(d["active_when"])

    card_h = active_y + 60

    svg = f'''<svg width="840" height="{card_h}" viewBox="0 0 840 {card_h}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Live GitHub metrics for {esc(d['username'])}">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#111111"/>
      <stop offset="100%" stop-color="#0a0a0b"/>
    </linearGradient>
    <linearGradient id="accent" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="#e8a634" stop-opacity="0"/>
      <stop offset="15%" stop-color="#e8a634"/>
      <stop offset="85%" stop-color="#e8a634"/>
      <stop offset="100%" stop-color="#e8a634" stop-opacity="0"/>
    </linearGradient>
  </defs>

  <!-- Card -->
  <rect width="840" height="{card_h}" rx="12" fill="url(#bg)"/>
  <rect width="840" height="{card_h}" rx="12" fill="none" stroke="#1a1a1a" stroke-width="1"/>

  <!-- Top accent -->
  <line x1="60" y1="1" x2="780" y2="1" stroke="url(#accent)" stroke-width="2"/>

  <!-- Header -->
  <text x="60" y="38" font-family="{mono}" font-size="11" fill="#525252" letter-spacing="1.5">LIVE METRICS</text>
  <text x="780" y="38" text-anchor="end" font-family="{mono}" font-size="11" fill="#404040">{esc(now)}</text>

  <!-- Separator -->
  <line x1="60" y1="50" x2="780" y2="50" stroke="#1a1a1a" stroke-width="1"/>

  <!-- Metrics grid -->
  {"".join(rows_svg)}

  <!-- Separator before active section -->
  <line x1="60" y1="{active_y - 12}" x2="780" y2="{active_y - 12}" stroke="#1a1a1a" stroke-width="1"/>

  <!-- Currently active -->
  <text x="60" y="{active_y + 8}" font-family="{mono}" font-size="10" font-weight="500" fill="#525252" letter-spacing="1.5">LATEST ACTIVITY</text>
  <text x="60" y="{active_y + 32}" font-family="{sans}" font-size="16" font-weight="600" fill="#e8a634">{active_label}</text>
  <text x="60" y="{active_y + 50}" font-family="{mono}" font-size="12" fill="#525252">{active_detail}</text>

  <!-- Footer line -->
  <line x1="60" y1="{card_h - 6}" x2="780" y2="{card_h - 6}" stroke="#1a1a1a" stroke-width="0.5"/>
</svg>
'''
    return svg


def main():
    if len(sys.argv) < 2:
        sys.stderr.write("Usage: build_dashboard.py <username> [--offline]\n")
        sys.exit(1)

    username = sys.argv[1]
    offline = "--offline" in sys.argv
    token = os.environ.get("GITHUB_TOKEN")

    if offline or not token:
        data = fetch_offline(username)
    else:
        try:
            data = fetch_live(username, token)
        except Exception as err:
            sys.stderr.write(f"GraphQL failed ({err}), falling back to REST.\n")
            data = fetch_offline(username)

    svg = render_svg(data)
    out = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets", "dashboard.svg"))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(svg)
    print(f"Generated {out}")


if __name__ == "__main__":
    main()
