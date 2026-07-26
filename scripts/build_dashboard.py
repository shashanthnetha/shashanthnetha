#!/usr/bin/env python3
"""
build_dashboard.py — FIG. 2 of Specification No. US-2026-SHA-M3.

Generates assets/dashboard.svg as an engineering patent claims table
with live GitHub telemetry. Styled to match authentic patent filings:
warm paper background, serif headers, monospace data, numbered claims.

Zero external dependencies. Python 3 standard library only.

Usage:
    GITHUB_TOKEN=xxx python3 build_dashboard.py shashanthnetha
    python3 build_dashboard.py shashanthnetha --offline
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
        return "Python, TypeScript, JavaScript"
    sorted_langs = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    return ", ".join(lang for lang, _ in sorted_langs[:limit])


def pick_latest_activity(repos: list) -> tuple:
    if not repos:
        return "—", "—", "—"
    top = repos[0]
    repo_name = top.get("name", "—")
    commit_msg = ""
    pushed_at = top.get("pushedAt") or top.get("pushed_at") or ""
    when = relative_time(pushed_at)
    ref = top.get("defaultBranchRef")
    if ref and isinstance(ref, dict):
        target = ref.get("target") or {}
        history = target.get("history") or {}
        nodes = history.get("nodes") or []
        if nodes:
            commit_msg = nodes[0].get("message", "").split("\n")[0]
            when = relative_time(nodes[0].get("committedDate", pushed_at))
    if len(commit_msg) > 46:
        commit_msg = commit_msg[:43] + "..."
    return repo_name, commit_msg, when


def fetch_live(username: str, token: str) -> dict:
    query = """
    query($login: String!) {
      user(login: $login) {
        name
        createdAt
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
        "User-Agent": f"{username}-patent-spec",
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        payload = json.load(resp)
    if "errors" in payload:
        raise RuntimeError(payload["errors"])

    user = payload["data"]["user"]
    cc = user.get("contributionsCollection") or {}
    cal = cc.get("contributionCalendar") or {}
    days = [d for w in (cal.get("weeks") or []) for d in w.get("contributionDays", [])]
    current_streak, longest_streak = compute_streaks(days)
    repos = user.get("repositories", {}).get("nodes", [])
    stars = sum(r.get("stargazerCount", 0) for r in repos)
    forks = sum(r.get("forkCount", 0) for r in repos)
    active_repo, commit_msg, active_when = pick_latest_activity(repos)

    return {
        "name": user.get("name") or username,
        "username": username,
        "created_at": user.get("createdAt", ""),
        "followers": user.get("followers", {}).get("totalCount", 0),
        "following": user.get("following", {}).get("totalCount", 0),
        "repo_count": user.get("repositories", {}).get("totalCount", 0),
        "stars": stars, "forks": forks,
        "prs": user.get("pullRequests", {}).get("totalCount", 0),
        "issues": user.get("issues", {}).get("totalCount", 0),
        "contributions": cal.get("totalContributions", 0),
        "commits": cc.get("totalCommitContributions", 0),
        "current_streak": current_streak,
        "longest_streak": longest_streak,
        "top_lang": pick_top_languages(repos),
        "active_repo": active_repo, "commit_msg": commit_msg, "active_when": active_when,
        "is_live": True,
    }


def fetch_offline_seed(username: str) -> dict:
    def get_json(path):
        req = urllib.request.Request(f"{REST_URL}{path}", headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"{username}-patent-spec",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.load(resp)

    try:
        user = get_json(f"/users/{username}")
        repos = get_json(f"/users/{username}/repos?per_page=100&sort=pushed")
        non_forks = [r for r in repos if isinstance(r, dict) and not r.get("fork")]
        top_langs = pick_top_languages(repos)
        active_repo, commit_msg, active_when = "—", "awaiting first workflow execution", "—"
        if non_forks:
            non_forks.sort(key=lambda r: r.get("pushed_at", ""), reverse=True)
            active_repo = non_forks[0].get("name", "—")
            active_when = relative_time(non_forks[0].get("pushed_at"))
        return {
            "name": user.get("name") or username, "username": username,
            "created_at": user.get("created_at", ""),
            "followers": user.get("followers", 0),
            "following": user.get("following", 0),
            "repo_count": user.get("public_repos", 0),
            "stars": sum(r.get("stargazers_count", 0) for r in repos if isinstance(r, dict)),
            "forks": sum(r.get("forks_count", 0) for r in repos if isinstance(r, dict)),
            "prs": None, "issues": None,
            "contributions": None, "commits": None,
            "current_streak": None, "longest_streak": None,
            "top_lang": top_langs,
            "active_repo": active_repo, "commit_msg": commit_msg, "active_when": active_when,
            "is_live": False,
        }
    except Exception as err:
        sys.stderr.write(f"REST seed failed ({err}), using static fallback.\n")
        return {
            "name": "Shashanth Netha", "username": username,
            "created_at": "2025-01-01T00:00:00Z",
            "followers": 10, "following": 17, "repo_count": 31,
            "stars": 50, "forks": 2,
            "prs": None, "issues": None,
            "contributions": None, "commits": None,
            "current_streak": None, "longest_streak": None,
            "top_lang": "TypeScript, Python, JavaScript",
            "active_repo": "shashanthnetha", "commit_msg": "awaiting first run", "active_when": "—",
            "is_live": False,
        }


def fmt(val, fallback="pending verification"):
    """Format a metric value, using fallback for None."""
    if val is None:
        return fallback
    if isinstance(val, int):
        return f"{val:,}"
    return str(val)


def render_svg(data: dict) -> str:
    username = data["username"]
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Build claims table rows: (claim_num, field_label, value)
    claims = [
        ("1.1", "Public Repositories", fmt(data["repo_count"])),
        ("1.2", "Stars Received", fmt(data["stars"])),
        ("1.3", "Forks Created", fmt(data["forks"])),
        ("1.4", "Primary Languages", esc(data["top_lang"])),

        ("2.1", "Contributions (Past Year)", fmt(data["contributions"])),
        ("2.2", "Commits (Past Year)", fmt(data["commits"])),
        ("2.3", "Current Streak", f'{fmt(data["current_streak"])} days' if data["current_streak"] is not None else "pending verification"),
        ("2.4", "Longest Streak", f'{fmt(data["longest_streak"])} days' if data["longest_streak"] is not None else "pending verification"),

        ("3.1", "Pull Requests Created", fmt(data["prs"])),
        ("3.2", "Issues Filed", fmt(data["issues"])),
        ("3.3", "Followers", fmt(data["followers"])),
        ("3.4", "Following", fmt(data["following"])),

        ("4.1", "Active Repository", esc(data["active_repo"])),
        ("4.2", "Last Commit", esc(data["commit_msg"]) if data["commit_msg"] else "—"),
        ("4.3", "Last Activity", esc(data["active_when"])),
    ]

    # Claim group headers
    group_headers = {
        0: "CLAIM 1 — CODEBASE SCOPE",
        4: "CLAIM 2 — DEVELOPMENT VELOCITY",
        8: "CLAIM 3 — OPEN SOURCE ACTIVITY",
        12: "CLAIM 4 — CURRENT EMBODIMENT",
    }

    serif = "'Times New Roman',Georgia,serif"
    mono = "'Courier New',monospace"

    # Table geometry
    table_x = 60
    table_w = 760
    col_num_w = 60
    col_field_w = 340
    header_y = 100
    row_h = 22
    group_h = 30

    # Calculate total height
    total_rows = len(claims)
    total_groups = len(group_headers)
    table_h = total_rows * row_h + total_groups * group_h
    card_h = header_y + table_h + 80  # room for footer

    rows_svg = []
    y = header_y

    for i, (num, field, value) in enumerate(claims):
        # Insert group header if needed
        if i in group_headers:
            rows_svg.append(
                f'<rect x="{table_x}" y="{y}" width="{table_w}" height="{group_h}" fill="#e8e4db"/>'
                f'<text x="{table_x + 14}" y="{y + 20}" font-family="{serif}" font-size="11" font-weight="700" fill="#2c3e50" letter-spacing="1">{group_headers[i]}</text>'
                f'<line x1="{table_x}" y1="{y + group_h}" x2="{table_x + table_w}" y2="{y + group_h}" stroke="#2c3e50" stroke-width="0.6"/>'
            )
            y += group_h

        # Data row
        bg = '#faf8f3' if (i % 2 == 0) else '#f5f2eb'
        rows_svg.append(
            f'<rect x="{table_x}" y="{y}" width="{table_w}" height="{row_h}" fill="{bg}"/>'
            f'<line x1="{table_x}" y1="{y + row_h}" x2="{table_x + table_w}" y2="{y + row_h}" stroke="#d4d0c8" stroke-width="0.4"/>'
            f'<text x="{table_x + 14}" y="{y + 16}" font-family="{mono}" font-size="10" fill="#7a8a9a">{num}</text>'
            f'<text x="{table_x + col_num_w + 10}" y="{y + 16}" font-family="{serif}" font-size="11" fill="#2c3e50">{field}</text>'
            f'<text x="{table_x + col_num_w + col_field_w + 10}" y="{y + 16}" font-family="{mono}" font-size="11" font-weight="600" fill="#1a1a1a">{value}</text>'
        )
        y += row_h

    # Column separator lines
    col_lines = (
        f'<line x1="{table_x + col_num_w}" y1="{header_y}" x2="{table_x + col_num_w}" y2="{y}" stroke="#c8c4bc" stroke-width="0.5"/>'
        f'<line x1="{table_x + col_num_w + col_field_w}" y1="{header_y}" x2="{table_x + col_num_w + col_field_w}" y2="{y}" stroke="#c8c4bc" stroke-width="0.5"/>'
    )

    svg = f'''<svg width="880" height="{card_h}" viewBox="0 0 880 {card_h}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="FIG. 2 — Live Specification Claims for {esc(username)}">
  <defs>
    <clipPath id="sheet2">
      <rect x="0" y="0" width="880" height="{card_h}" rx="2"/>
    </clipPath>
    <pattern id="bluegrid2" width="24" height="24" patternUnits="userSpaceOnUse">
      <path d="M 24 0 L 0 0 0 24" fill="none" stroke="#c8d8e8" stroke-width="0.4"/>
    </pattern>
  </defs>

  <g clip-path="url(#sheet2)">
    <rect width="880" height="{card_h}" fill="#f5f2eb"/>
    <rect width="880" height="{card_h}" fill="url(#bluegrid2)" opacity="0.35"/>

    <!-- Outer drawing border -->
    <rect x="40" y="20" width="800" height="{card_h - 40}" fill="none" stroke="#2c3e50" stroke-width="1.2"/>

    <!-- Figure heading -->
    <text x="440" y="52" text-anchor="middle" font-family="{serif}" font-size="14" font-weight="700" fill="#1a1a1a" letter-spacing="2">FIG. 2 — SPECIFICATION CLAIMS (LIVE TELEMETRY)</text>
    <text x="440" y="70" text-anchor="middle" font-family="{serif}" font-size="10" fill="#7a8a9a">Data sourced from GitHub GraphQL API · Automatically verified daily at 03:17 UTC</text>

    <!-- Table column headers -->
    <rect x="{table_x}" y="{header_y - 22}" width="{table_w}" height="22" fill="#2c3e50"/>
    <text x="{table_x + 14}" y="{header_y - 6}" font-family="{serif}" font-size="10" font-weight="700" fill="#f5f2eb" letter-spacing="0.5">REF.</text>
    <text x="{table_x + col_num_w + 10}" y="{header_y - 6}" font-family="{serif}" font-size="10" font-weight="700" fill="#f5f2eb" letter-spacing="0.5">FIELD</text>
    <text x="{table_x + col_num_w + col_field_w + 10}" y="{header_y - 6}" font-family="{serif}" font-size="10" font-weight="700" fill="#f5f2eb" letter-spacing="0.5">VERIFIED VALUE</text>

    <!-- Table outer border -->
    <rect x="{table_x}" y="{header_y - 22}" width="{table_w}" height="{y - header_y + 22}" fill="none" stroke="#2c3e50" stroke-width="1"/>

    <!-- Table data rows -->
    {"".join(rows_svg)}

    <!-- Column separators -->
    {col_lines}

    <!-- Footer -->
    <text x="440" y="{y + 28}" text-anchor="middle" font-family="{serif}" font-size="10" fill="#7a8a9a">Specification No. US-2026-SHA-M3 · Sheet 2 of 2 · Last verified: {esc(now_utc)}</text>
    <text x="440" y="{y + 44}" text-anchor="middle" font-family="{serif}" font-size="9" fill="#a0a8b0">Self-hosted telemetry engine · github.com/{esc(username)}/{esc(username)} · No third-party services</text>
  </g>
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
        data = fetch_offline_seed(username)
    else:
        try:
            data = fetch_live(username, token)
        except Exception as err:
            sys.stderr.write(f"GraphQL failed ({err}). Falling back to REST.\n")
            data = fetch_offline_seed(username)

    svg = render_svg(data)
    out_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets", "dashboard.svg"))
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(svg)
    print(f"Generated {out_path}")


if __name__ == "__main__":
    main()
