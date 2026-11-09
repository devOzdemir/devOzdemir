"""Generate profile SVG cards (stats, top languages, repo pins) from the GitHub API.

Stdlib only. Usage: GITHUB_TOKEN=... python3 generate_cards.py <user> <out_dir> <repo> [<repo> ...]
Only public data is rendered; private contributions appear as a count only
(and only if "Include private contributions" is enabled on the profile).
"""

import json
import os
import sys
import textwrap
import urllib.request
from html import escape

BG = "#1a1b27"
TITLE = "#70a5fd"
TEXT = "#a9b1d6"
ICON = "#bf91f3"
MUTED = "#565f89"
FONT = "font-family:'Segoe UI',Ubuntu,'Helvetica Neue',Sans-Serif"

QUERY = """
query($login: String!) {
  user(login: $login) {
    followers { totalCount }
    pullRequests { totalCount }
    issues { totalCount }
    contributionsCollection {
      totalCommitContributions
      restrictedContributionsCount
      contributionCalendar { totalContributions }
    }
    repositories(ownerAffiliations: OWNER, privacy: PUBLIC, isFork: false, first: 100) {
      totalCount
      nodes {
        name
        description
        stargazerCount
        forkCount
        primaryLanguage { name color }
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
  }
}
"""


def gql(token, login):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": QUERY, "variables": {"login": login}}).encode(),
        headers={"Authorization": f"bearer {token}", "User-Agent": "profile-cards"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        body = json.load(r)
    if "errors" in body:
        raise SystemExit(f"GraphQL error: {body['errors']}")
    return body["data"]["user"]


def frame(w, h, title, inner):
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">
<style>
  .t {{ {FONT}; font-weight:600; font-size:18px; fill:{TITLE}; }}
  .l {{ {FONT}; font-size:14px; fill:{TEXT}; }}
  .v {{ {FONT}; font-weight:700; font-size:14px; fill:{TEXT}; }}
  .s {{ {FONT}; font-size:12px; fill:{TEXT}; }}
  .fade {{ animation: f .6s ease-in-out backwards; }}
  @keyframes f {{ from {{ opacity:0; }} }}
</style>
<rect width="{w}" height="{h}" rx="6" fill="{BG}"/>
<text x="25" y="35" class="t">{escape(title)}</text>
{inner}
</svg>"""


def stats_card(u):
    cc = u["contributionsCollection"]
    repos = u["repositories"]
    stars = sum(n["stargazerCount"] for n in repos["nodes"])
    rows = [
        ("♥", "Followers", u["followers"]["totalCount"]),
        ("★", "Total Stars", stars),
        ("⬤", "Commits (this year)", cc["totalCommitContributions"] + cc["restrictedContributionsCount"]),
        ("⇄", "Pull Requests", u["pullRequests"]["totalCount"]),
        ("!", "Issues", u["issues"]["totalCount"]),
        ("▣", "Public Repositories", repos["totalCount"]),
    ]
    inner = ""
    for i, (icon, label, val) in enumerate(rows):
        y = 70 + i * 25
        inner += (
            f'<g class="fade" style="animation-delay:{150 * i}ms">'
            f'<text x="25" y="{y}" class="l" fill="{ICON}" style="fill:{ICON}">{icon}</text>'
            f'<text x="50" y="{y}" class="l">{label}:</text>'
            f'<text x="230" y="{y}" class="v">{val:,}</text></g>'
        )
    total = cc["contributionCalendar"]["totalContributions"]
    cx, cy, r = 360, 105, 45
    inner += (
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{MUTED}" stroke-width="6" opacity=".35"/>'
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{TITLE}" stroke-width="6" '
        f'stroke-dasharray="283" stroke-dashoffset="0" transform="rotate(-90 {cx} {cy})">'
        f'<animate attributeName="stroke-dashoffset" from="283" to="0" dur="1.2s" fill="freeze"/></circle>'
        f'<text x="{cx}" y="{cy + 2}" text-anchor="middle" class="v" style="font-size:20px">{total:,}</text>'
        f'<text x="{cx}" y="{cy + 20}" text-anchor="middle" class="s">contributions</text>'
    )
    return frame(450, 210, "devOzdemir's GitHub Stats", inner)


def langs_card(u, count=8):
    totals = {}
    for repo in u["repositories"]["nodes"]:
        for e in repo["languages"]["edges"]:
            name, color = e["node"]["name"], e["node"]["color"] or MUTED
            size, _ = totals.get(name, (0, color))
            totals[name] = (size + e["size"], color)
    ranked = sorted(totals.items(), key=lambda kv: -kv[1][0])
    grand = sum(s for _, (s, _) in ranked) or 1
    top = [kv for kv in ranked[:count] if kv[1][0] / grand >= 0.001]
    width, x = 330, 25
    bar = f'<mask id="m"><rect x="25" y="55" width="{width}" height="8" rx="4" fill="white"/></mask><g mask="url(#m)">'
    legend = ""
    for i, (name, (size, color)) in enumerate(top):
        w = size / grand * width
        bar += f'<rect x="{x:.2f}" y="55" width="{w:.2f}" height="8" fill="{color}"/>'
        x += w
        lx, ly = 25 + (i % 2) * 175, 90 + (i // 2) * 25
        legend += (
            f'<g class="fade" style="animation-delay:{150 * i}ms">'
            f'<circle cx="{lx + 5}" cy="{ly - 4}" r="5" fill="{color}"/>'
            f'<text x="{lx + 15}" y="{ly}" class="s">{escape(name)} {size / grand * 100:.1f}%</text></g>'
        )
    bar += "</g>"
    rows = (len(top) + 1) // 2
    return frame(380, 75 + rows * 25 + 15, "Most Used Languages", bar + legend)


def pin_card(repo):
    desc = repo["description"] or "No description provided"
    lines = textwrap.wrap(desc, 55)[:2]
    inner = "".join(
        f'<text x="25" y="{62 + i * 18}" class="s">{escape(t)}</text>' for i, t in enumerate(lines)
    )
    y = 120
    x = 25
    lang = repo["primaryLanguage"]
    if lang:
        inner += (
            f'<circle cx="{x + 6}" cy="{y - 4}" r="6" fill="{lang["color"] or MUTED}"/>'
            f'<text x="{x + 18}" y="{y}" class="s">{escape(lang["name"])}</text>'
        )
        x += 18 + 7 * len(lang["name"]) + 20
    inner += f'<text x="{x}" y="{y}" class="s"><tspan style="fill:{ICON}">★</tspan> {repo["stargazerCount"]}</text>'
    inner += f'<text x="{x + 50}" y="{y}" class="s"><tspan style="fill:{ICON}">⑂</tspan> {repo["forkCount"]}</text>'
    return frame(400, 140, repo["name"], inner)


def main():
    login, out_dir, pins = sys.argv[1], sys.argv[2], sys.argv[3:]
    u = gql(os.environ["GITHUB_TOKEN"], login)
    os.makedirs(out_dir, exist_ok=True)
    files = {"stats.svg": stats_card(u), "top-langs.svg": langs_card(u)}
    by_name = {r["name"]: r for r in u["repositories"]["nodes"]}
    for name in pins:
        if name in by_name:
            files[f"pin-{name}.svg"] = pin_card(by_name[name])
        else:
            print(f"warning: public repo {name!r} not found, skipping", file=sys.stderr)
    for fname, svg in files.items():
        with open(os.path.join(out_dir, fname), "w", encoding="utf-8") as f:
            f.write(svg)
        print("wrote", fname)


if __name__ == "__main__":
    main()
