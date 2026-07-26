#!/usr/bin/env python3
"""
build_dashboard.py
-------------------
Generates assets/dashboard.svg — a self-hosted, FUI "Mission Control Telemetry"
card rendered from live profile data pulled directly from GitHub's GraphQL API.

Features:
- Single GraphQL API query with unauthenticated REST fallback
- Zero external dependencies (Python standard library only)
- High performance (< 0.5s execution)
- XML string escaping and character bounds checking
- Awwwards-grade FUI (Fictional User Interface) design language

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

# ---- FUI Palette Constants --------------------------------------------------
BG = "#08090c"
HEADER_BG = "#0e131b"
CARD_BG = "#0c1017"
BORDER = "#1b222d"
MUTED = "#525e6e"
TEXT = "#e6edf3"
CYAN = "#00f0ff"
GREEN = "#00ff9d"
GOLD = "#ffb700"
PURPLE = "#bc8cff"
RED = "#ff5f56"


def esc(text: str) -> str:
    """Safely escape text for XML/SVG placement."""
    if text is None:
        return ""
    return xml_escape(str(text), entities={'"': "&quot;", "'": "&#39;"})


def relative_time(iso_date: str) -> str:
    """Format ISO date to human-readable relative time (e.g. '5m ago')."""
    if not iso_date:
        return "recently"
    try:
        then = datetime.fromisoformat(iso_date.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        delta = now - then
        seconds = int(delta.total_seconds())
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
        return "recently"


def compute_streaks(days: list) -> tuple:
    """Compute current and longest contribution streaks."""
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


def pick_top_languages(repos: list, limit: int = 2) -> str:
    """Aggregate primary languages across repos."""
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
        return "TypeScript, Python"

    sorted_langs = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    top = [lang for lang, _ in sorted_langs[:limit]]
    return ", ".join(top)


def pick_latest_activity(repos: list) -> tuple:
    """Extract latest repository name, truncated commit message, and relative time."""
    if not repos:
        return "shashanthnetha", "updated mission telemetry", "recently"

    top = repos[0]
    repo_name = top.get("name", "shashanthnetha")
    commit_msg = ""
    pushed_at = top.get("pushedAt") or top.get("pushed_at") or ""
    when = relative_time(pushed_at)

    ref = top.get("defaultBranchRef")
    if ref and isinstance(ref, dict):
        target = ref.get("target") or {}
        history = target.get("history") or {}
        nodes = history.get("nodes") or []
        if nodes:
            node = nodes[0]
            commit_msg = node.get("message", "").split("\n")[0]
            when = relative_time(node.get("committedDate", pushed_at))

    if len(commit_msg) > 34:
        commit_msg = commit_msg[:31] + "..."

    return repo_name, commit_msg, when


def fetch_live(username: str, token: str) -> dict:
    """GraphQL single round-trip to fetch profile statistics."""
    query = """
    query($login: String!) {
      user(login: $login) {
        name
        login
        createdAt
        followers { totalCount }
        following { totalCount }
        pullRequests(first: 1) { totalCount }
        issues(first: 1) { totalCount }
        contributionsCollection {
          totalContributions
          totalCommitContributions
          totalPullRequestContributions
          totalIssueContributions
          contributionCalendar {
            totalContributions
            weeks {
              contributionDays {
                date
                contributionCount
              }
            }
          }
        }
        repositories(first: 100, ownerAffiliations: OWNER, isFork: false,
                      orderBy: {field: PUSHED_AT, direction: DESC}) {
          totalCount
          nodes {
            name
            stargazerCount
            forkCount
            pushedAt
            primaryLanguage { name }
            defaultBranchRef {
              target {
                ... on Commit {
                  history(first: 1) {
                    nodes { message committedDate }
                  }
                }
              }
            }
          }
        }
      }
    }
    """
    body = json.dumps({"query": query, "variables": {"login": username}}).encode("utf-8")
    req = urllib.request.Request(
        GRAPHQL_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": f"{username}-dashboard-builder",
        },
    )

    with urllib.request.urlopen(req, timeout=15) as resp:
        payload = json.load(resp)

    if "errors" in payload:
        raise RuntimeError(f"GraphQL Errors: {payload['errors']}")

    user = payload["data"]["user"]
    contrib_col = user.get("contributionsCollection") or {}
    calendar = contrib_col.get("contributionCalendar") or {}
    weeks = calendar.get("weeks") or []
    days = [d for w in weeks for d in w.get("contributionDays", [])]

    current_streak, longest_streak = compute_streaks(days)
    repos = user.get("repositories", {}).get("nodes", [])

    total_stars = sum(r.get("stargazerCount", 0) for r in repos)
    total_forks = sum(r.get("forkCount", 0) for r in repos)
    top_langs = pick_top_languages(repos)
    active_repo, commit_msg, active_when = pick_latest_activity(repos)

    return {
        "name": user.get("name") or username,
        "username": username,
        "created_at": user.get("createdAt", "2024-01-01T00:00:00Z"),
        "followers": user.get("followers", {}).get("totalCount", 0),
        "following": user.get("following", {}).get("totalCount", 0),
        "repo_count": user.get("repositories", {}).get("totalCount", len(repos)),
        "stars": total_stars,
        "forks": total_forks,
        "prs": user.get("pullRequests", {}).get("totalCount", 0),
        "issues": user.get("issues", {}).get("totalCount", 0),
        "contributions": calendar.get("totalContributions", 0),
        "commits": contrib_col.get("totalCommitContributions", 0),
        "current_streak": current_streak,
        "longest_streak": longest_streak,
        "top_lang": top_langs,
        "active_repo": active_repo,
        "commit_msg": commit_msg,
        "active_when": active_when,
        "is_live": True,
    }


def fetch_offline_seed(username: str) -> dict:
    """Fallback using unauthenticated REST API."""
    def get_json(path):
        req = urllib.request.Request(
            f"{REST_URL}{path}",
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": f"{username}-dashboard-builder",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.load(resp)

    try:
        user = get_json(f"/users/{username}")
        repos = get_json(f"/users/{username}/repos?per_page=100&sort=pushed")
        non_forks = [r for r in repos if isinstance(r, dict) and not r.get("fork")]

        top_langs = pick_top_languages(repos)
        active_repo, commit_msg, active_when = "shashanthnetha", "syncing mission workflow...", "recently"
        if non_forks:
            non_forks.sort(key=lambda r: r.get("pushed_at", ""), reverse=True)
            active_repo = non_forks[0].get("name", "shashanthnetha")
            active_when = relative_time(non_forks[0].get("pushed_at"))

        return {
            "name": user.get("name") or username,
            "username": username,
            "created_at": user.get("created_at", "2024-02-01T00:00:00Z"),
            "followers": user.get("followers", 0),
            "following": user.get("following", 0),
            "repo_count": user.get("public_repos", len(repos)),
            "stars": sum(r.get("stargazers_count", 0) for r in repos if isinstance(r, dict)),
            "forks": sum(r.get("forks_count", 0) for r in repos if isinstance(r, dict)),
            "prs": None,
            "issues": None,
            "contributions": None,
            "commits": None,
            "current_streak": None,
            "longest_streak": None,
            "top_lang": top_langs,
            "active_repo": active_repo,
            "commit_msg": commit_msg,
            "active_when": active_when,
            "is_live": False,
        }
    except Exception as err:
        sys.stderr.write(f"Warning: REST seed fetch failed ({err}). Using fallback static seed.\n")
        return {
            "name": "Shashanth Netha",
            "username": username,
            "created_at": "2024-02-01T00:00:00Z",
            "followers": 15,
            "following": 12,
            "repo_count": 31,
            "stars": 50,
            "forks": 10,
            "prs": None,
            "issues": None,
            "contributions": None,
            "commits": None,
            "current_streak": None,
            "longest_streak": None,
            "top_lang": "TypeScript, Python",
            "active_repo": "shashanthnetha",
            "commit_msg": "syncing mission workflow...",
            "active_when": "recently",
            "is_live": False,
        }


def render_svg(data: dict) -> str:
    """Render FUI Mission Control Console SVG."""
    username = data["username"]
    repos_str = f"{data['repo_count']} Public Repos · {data['stars']} ★ · {data['forks']} Forks"
    top_langs = esc(data["top_lang"])

    if data["contributions"] is not None:
        contrib_str = f"{data['contributions']:,} past year"
        if data["commits"]:
            contrib_str += f" ({data['commits']:,} commits)"
    else:
        contrib_str = "syncing live telemetry..."

    if data["current_streak"] is not None:
        streak_str = f"{data['current_streak']}d current · {data['longest_streak']}d longest streak"
    else:
        streak_str = "syncing live telemetry..."

    if data["prs"] is not None and data["issues"] is not None:
        prs_str = f"{data['prs']} PRs · {data['issues']} Issues created"
    else:
        prs_str = "active open source author"

    network_str = f"{data['followers']} Followers · {data['following']} Following"

    if data["commit_msg"]:
        active_str = f"{esc(data['active_repo'])} · &quot;{esc(data['commit_msg'])}&quot;"
    else:
        active_str = esc(data["active_repo"])

    active_time = esc(data["active_when"])
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    card_height = 360

    svg = f'''<svg width="920" height="{card_height}" viewBox="0 0 920 {card_height}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="SHASHANTH.OS FUI Mission Control Telemetry for {esc(username)}">
  <defs>
    <clipPath id="cardClip">
      <rect x="2" y="2" width="916" height="{card_height - 4}" rx="14"/>
    </clipPath>

    <filter id="cyanGlow" x="-30%" y="-30%" width="160%" height="160%">
      <feGaussianBlur stdDeviation="2.5" result="blur"/>
      <feMerge>
        <feMergeNode in="blur"/>
        <feMergeNode in="SourceGraphic"/>
      </feMerge>
    </filter>

    <filter id="emeraldGlow" x="-30%" y="-30%" width="160%" height="160%">
      <feGaussianBlur stdDeviation="2" result="blur"/>
      <feMerge>
        <feMergeNode in="blur"/>
        <feMergeNode in="SourceGraphic"/>
      </feMerge>
    </filter>

    <pattern id="scanlines" width="4" height="4" patternUnits="userSpaceOnUse">
      <rect width="4" height="1" fill="#ffffff" opacity="0.018"/>
    </pattern>

    <pattern id="grid" width="20" height="20" patternUnits="userSpaceOnUse">
      <path d="M 20 0 L 0 0 0 20" fill="none" stroke="#00f0ff" stroke-width="0.5" opacity="0.06"/>
    </pattern>
  </defs>

  <g clip-path="url(#cardClip)">
    <!-- Base FUI Frame -->
    <rect x="2" y="2" width="916" height="{card_height - 4}" rx="14" fill="{BG}" stroke="{BORDER}" stroke-width="1.5"/>
    <rect x="2" y="2" width="916" height="{card_height - 4}" fill="url(#grid)"/>

    <!-- Sci-Fi Corner Brackets -->
    <path d="M 12 28 L 12 12 L 28 12" fill="none" stroke="{CYAN}" stroke-width="2" opacity="0.8"/>
    <path d="M 908 28 L 908 12 L 892 12" fill="none" stroke="{CYAN}" stroke-width="2" opacity="0.8"/>
    <path d="M 12 {card_height - 28} L 12 {card_height - 12} L 28 {card_height - 12}" fill="none" stroke="{CYAN}" stroke-width="2" opacity="0.8"/>
    <path d="M 908 {card_height - 28} L 908 {card_height - 12} L 892 {card_height - 12}" fill="none" stroke="{CYAN}" stroke-width="2" opacity="0.8"/>

    <!-- Header Diagnostic Bar -->
    <rect x="2" y="2" width="916" height="36" fill="{HEADER_BG}"/>
    <line x1="2" y1="38" x2="918" y2="38" stroke="{BORDER}" stroke-width="1"/>

    <!-- Header Title & Telemetry Indicators -->
    <circle cx="24" cy="20" r="4" fill="{GREEN}" filter="url(#emeraldGlow)">
      <animate attributeName="opacity" values="1;0.4;1" dur="2s" repeatCount="indefinite"/>
    </circle>
    <text x="36" y="24" font-family="SFMono-Regular,Consolas,'Liberation Mono',Menlo,monospace" font-size="11" font-weight="700" fill="{GREEN}" letter-spacing="1">MISSION CONTROL TELEMETRY</text>
    <text x="460" y="24" text-anchor="middle" font-family="SFMono-Regular,Consolas,'Liberation Mono',Menlo,monospace" font-size="11" fill="{MUTED}" letter-spacing="1.5">LIVE GRAPHQL TELEMETRY ENGINE · DAILY CRON</text>
    <text x="896" y="24" text-anchor="end" font-family="SFMono-Regular,Consolas,'Liberation Mono',Menlo,monospace" font-size="11" fill="{CYAN}" letter-spacing="1">[{esc(username).upper()}]</text>

    <!-- LEFT MODULE: TELEMETRY RADAR & STATUS -->
    <g transform="translate(100, 186)">
      <!-- Target Lock Rings -->
      <circle cx="0" cy="0" r="75" fill="none" stroke="{BORDER}" stroke-width="1" stroke-dasharray="4 4"/>
      <circle cx="0" cy="0" r="55" fill="none" stroke="{CYAN}" stroke-width="1" opacity="0.25"/>

      <!-- Spinning Crosshairs -->
      <circle cx="0" cy="0" r="75" fill="none" stroke="{CYAN}" stroke-width="1.5" stroke-dasharray="25 50 10 35" opacity="0.7">
        <animateTransform attributeName="transform" type="rotate" from="0" to="360" dur="20s" repeatCount="indefinite"/>
      </circle>
      <circle cx="0" cy="0" r="55" fill="none" stroke="{GREEN}" stroke-width="1.5" stroke-dasharray="15 35 10 25" opacity="0.8">
        <animateTransform attributeName="transform" type="rotate" from="360" to="0" dur="14s" repeatCount="indefinite"/>
      </circle>

      <!-- Center Pulse Point -->
      <circle cx="0" cy="0" r="8" fill="{CYAN}" filter="url(#cyanGlow)">
        <animate attributeName="r" values="6;10;6" dur="2.5s" repeatCount="indefinite"/>
      </circle>
      <circle cx="0" cy="0" r="3" fill="#ffffff"/>

      <!-- Status Text -->
      <text x="0" y="95" text-anchor="middle" font-family="SFMono-Regular,Consolas,'Liberation Mono',Menlo,monospace" font-size="10" font-weight="700" fill="{GREEN}" letter-spacing="1">STATUS: ONLINE</text>
      <text x="0" y="110" text-anchor="middle" font-family="SFMono-Regular,Consolas,'Liberation Mono',Menlo,monospace" font-size="10" fill="{MUTED}" letter-spacing="1">COMPUTE: APPLE M3</text>
    </g>

    <!-- RIGHT MODULE: 4 TACTICAL TELEMETRY PANELS (2x2 GRID) -->
    <g transform="translate(215, 54)" font-family="SFMono-Regular,Consolas,'Liberation Mono',Menlo,monospace">

      <!-- Panel 1: Codebase Matrix -->
      <g transform="translate(0, 0)">
        <rect x="0" y="0" width="335" height="120" rx="8" fill="{CARD_BG}" stroke="{BORDER}" stroke-width="1"/>
        <path d="M 8 0 L 85 0" stroke="{CYAN}" stroke-width="2"/>
        <text x="14" y="24" font-size="11" font-weight="700" fill="{CYAN}" letter-spacing="1">01 // CODEBASE MATRIX</text>
        
        <text x="14" y="52" font-size="12" font-weight="600" fill="{TEXT}">{repos_str}</text>
        <text x="14" y="74" font-size="11" fill="{MUTED}">Top Stack: <tspan fill="{GOLD}" font-weight="600">{top_langs}</tspan></text>
        <text x="14" y="96" font-size="10" fill="{GREEN}">✓ Synchronized via GitHub GraphQL</text>
      </g>

      <!-- Panel 2: Engineering Velocity -->
      <g transform="translate(350, 0)">
        <rect x="0" y="0" width="335" height="120" rx="8" fill="{CARD_BG}" stroke="{BORDER}" stroke-width="1"/>
        <path d="M 8 0 L 105 0" stroke="{GREEN}" stroke-width="2"/>
        <text x="14" y="24" font-size="11" font-weight="700" fill="{GREEN}" letter-spacing="1">02 // ENGINEERING VELOCITY</text>

        <text x="14" y="52" font-size="12" font-weight="600" fill="{TEXT}">{contrib_str}</text>
        <text x="14" y="74" font-size="11" fill="{MUTED}">Streak: <tspan fill="{GREEN}" font-weight="600">{streak_str}</tspan></text>
        <text x="14" y="96" font-size="10" fill="{CYAN}">⚡ High Frequency Development</text>
      </g>

      <!-- Panel 3: Workflow Telemetry -->
      <g transform="translate(0, 134)">
        <rect x="0" y="0" width="335" height="120" rx="8" fill="{CARD_BG}" stroke="{BORDER}" stroke-width="1"/>
        <path d="M 8 0 L 95 0" stroke="{GOLD}" stroke-width="2"/>
        <text x="14" y="24" font-size="11" font-weight="700" fill="{GOLD}" letter-spacing="1">03 // WORKFLOW TELEMETRY</text>

        <text x="14" y="52" font-size="12" font-weight="600" fill="{TEXT}">{prs_str}</text>
        <text x="14" y="74" font-size="11" fill="{MUTED}">Network: <tspan fill="{TEXT}">{network_str}</tspan></text>
        <text x="14" y="96" font-size="10" fill="{GOLD}">★ Active Open Source Contributor</text>
      </g>

      <!-- Panel 4: Active Mission -->
      <g transform="translate(350, 134)">
        <rect x="0" y="0" width="335" height="120" rx="8" fill="{CARD_BG}" stroke="{BORDER}" stroke-width="1"/>
        <path d="M 8 0 L 115 0" stroke="{PURPLE}" stroke-width="2"/>
        <text x="14" y="24" font-size="11" font-weight="700" fill="{PURPLE}" letter-spacing="1">04 // ACTIVE MISSION TELEMETRY</text>

        <text x="14" y="52" font-size="12" font-weight="600" fill="{CYAN}">{active_str}</text>
        <text x="14" y="74" font-size="11" fill="{MUTED}">Last Commit Pushed: <tspan fill="{TEXT}">{active_time}</tspan></text>
        <text x="14" y="96" font-size="10" fill="{MUTED}">Updated {esc(now_utc)}</text>
      </g>

    </g>

    <!-- BOTTOM SIGNAL MATRIX BAR -->
    <g transform="translate(215, 322)">
      <rect x="0" y="0" width="14" height="14" rx="3" fill="{RED}"/>
      <rect x="20" y="0" width="14" height="14" rx="3" fill="{GREEN}" filter="url(#emeraldGlow)"/>
      <rect x="40" y="0" width="14" height="14" rx="3" fill="{GOLD}"/>
      <rect x="60" y="0" width="14" height="14" rx="3" fill="{CYAN}" filter="url(#cyanGlow)"/>
      <rect x="80" y="0" width="14" height="14" rx="3" fill="{PURPLE}"/>
      <rect x="100" y="0" width="14" height="14" rx="3" fill="{TEXT}"/>

      <text x="130" y="11" font-family="SFMono-Regular,Consolas,'Liberation Mono',Menlo,monospace" font-size="11" fill="{MUTED}">SHASHANTH.OS // SELF-HOSTED GRAPHQL TELEMETRY ENGINE · NO THIRD-PARTY SERVICES</text>
    </g>

    <!-- Scanline overlay -->
    <rect x="2" y="38" width="916" height="{card_height - 40}" fill="url(#scanlines)"/>
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
            sys.stderr.write(f"GraphQL fetch failed ({err}). Falling back to REST seed.\n")
            data = fetch_offline_seed(username)

    svg_content = render_svg(data)

    out_path = os.path.join(os.path.dirname(__file__), "..", "assets", "dashboard.svg")
    out_path = os.path.abspath(out_path)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(svg_content)

    print(f"Successfully generated {out_path}")


if __name__ == "__main__":
    main()
