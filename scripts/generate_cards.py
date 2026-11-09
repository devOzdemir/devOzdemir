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
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
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

ACCENT = "#7dcfff"


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


STYLE = f"""<style>
  .t {{ {FONT}; font-weight:600; font-size:18px; fill:{TITLE}; }}
  .l {{ {FONT}; font-size:14px; fill:{TEXT}; }}
  .v {{ {FONT}; font-weight:700; font-size:14px; fill:{TEXT}; }}
  .s {{ {FONT}; font-size:12px; fill:{TEXT}; }}
  .big {{ {FONT}; font-weight:700; font-size:30px; fill:{TITLE}; }}
  .lab {{ {FONT}; font-size:14px; fill:{TITLE}; }}
  .rng {{ {FONT}; font-size:12px; fill:{ACCENT}; }}
</style>"""


def frame(w, h, title, inner):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">\n'
        f'{STYLE}\n<rect width="{w}" height="{h}" rx="6" fill="{BG}"/>\n'
        f'<text x="25" y="35" class="t">{escape(title)}</text>\n{inner}\n</svg>'
    )


def panel(x, y, w, h, title, inner):
    return (
        f'<g transform="translate({x},{y})"><rect width="{w}" height="{h}" rx="8" fill="{BG}"/>'
        f'<text x="25" y="35" class="t">{escape(title)}</text>{inner}</g>'
    )


def ring(cx, cy, r, color, top, bottom, top_cls="v", top_size=20):
    c = 2 * 3.14159 * r
    return (
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{MUTED}" stroke-width="6" opacity=".35"/>'
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{color}" stroke-width="6" stroke-linecap="round" '
        f'stroke-dasharray="{c:.1f}" stroke-dashoffset="0" transform="rotate(-90 {cx} {cy})">'
        f'<animate attributeName="stroke-dashoffset" from="{c:.1f}" to="0" dur="1.2s" fill="freeze"/></circle>'
        f'<text x="{cx}" y="{cy + (2 if bottom else 7)}" text-anchor="middle" class="{top_cls}" '
        f'style="font-size:{top_size}px">{top}</text>'
        + (f'<text x="{cx}" y="{cy + 20}" text-anchor="middle" class="s">{bottom}</text>' if bottom else "")
    )


def calendar_days(u):
    weeks = u["contributionsCollection"]["contributionCalendar"]["weeks"]
    return [(d["date"], d["contributionCount"]) for w in weeks for d in w["contributionDays"]]


def fmt(date):
    import datetime as dt
    d = dt.date.fromisoformat(date)
    return f"{d.strftime('%b')} {d.day}"


def streaks(days):
    longest, run, start, best = 0, 0, None, (None, None)
    for date, n in days:
        if n > 0:
            if run == 0:
                start = date
            run += 1
            if run > longest:
                longest, best = run, (start, date)
        else:
            run = 0
    i = len(days) - 1
    if i >= 0 and days[i][1] == 0:  # today may not have contributions yet
        i -= 1
    cur, end = 0, days[i][0] if i >= 0 else None
    while i >= 0 and days[i][1] > 0:
        cur += 1
        i -= 1
    cur_range = (days[i + 1][0], end) if cur else (None, None)
    return cur, cur_range, longest, best


def stats_inner(u, days):
    active = [n for _, n in days if n > 0]
    weeks = u["contributionsCollection"]["contributionCalendar"]["weeks"]
    active_weeks = sum(1 for w in weeks if any(d["contributionCount"] for d in w["contributionDays"]))
    rows = [
        ("♥", "Followers", f'{u["followers"]["totalCount"]:,}'),
        ("▣", "Public Repositories", f'{u["repositories"]["totalCount"]:,}'),
        ("▲", "Best Day", f"{max(active, default=0):,}"),
        ("≈", "Avg per Active Day", f"{(sum(active) / len(active) if active else 0):.1f}"),
        ("◷", "Active Weeks", f"{active_weeks} / {len(weeks)}"),
    ]
    inner = ""
    for i, (icon, label, val) in enumerate(rows):
        y = 72 + i * 26
        inner += (
            f'<g>'
            f'<text x="25" y="{y}" class="l" style="fill:{ICON}">{icon}</text>'
            f'<text x="50" y="{y}" class="l">{label}:</text>'
            f'<text x="225" y="{y}" class="v">{val}</text></g>'
        )
    pct = round(len(active) / len(days) * 100) if days else 0
    inner += ring(355, 112, 48, TITLE, f"{pct}%", "active days")
    return inner


def langs_inner(u, width, count=8):
    totals = {}
    for repo in u["repositories"]["nodes"]:
        for e in repo["languages"]["edges"]:
            name, color = e["node"]["name"], e["node"]["color"] or MUTED
            size, _ = totals.get(name, (0, color))
            totals[name] = (size + e["size"], color)
    ranked = sorted(totals.items(), key=lambda kv: -kv[1][0])
    grand = sum(s for _, (s, _) in ranked) or 1
    top = [kv for kv in ranked[:count] if kv[1][0] / grand >= 0.001]
    bw, x = width - 50, 25
    out = f'<mask id="m"><rect x="25" y="58" width="{bw}" height="10" rx="5" fill="white"/></mask><g mask="url(#m)">'
    legend = ""
    for i, (name, (size, color)) in enumerate(top):
        w = size / grand * bw
        out += f'<rect x="{x:.2f}" y="58" width="{w:.2f}" height="10" fill="{color}"/>'
        x += w
        lx, ly = 25 + (i % 2) * (bw // 2), 98 + (i // 2) * 26
        legend += (
            f'<g>'
            f'<circle cx="{lx + 5}" cy="{ly - 4}" r="5" fill="{color}"/>'
            f'<text x="{lx + 16}" y="{ly}" class="l">{escape(name)} '
            f'<tspan style="fill:{MUTED}">{size / grand * 100:.1f}%</tspan></text></g>'
        )
    return out + "</g>" + legend


def streak_inner(u, days, width):
    total = u["contributionsCollection"]["contributionCalendar"]["totalContributions"]
    cur, cr, longest, lr = streaks(days)
    col = width / 3
    rng = lambda r: f"{fmt(r[0])} – {fmt(r[1])}" if r[0] else "—"
    out = (
        f'<line x1="{col:.0f}" y1="60" x2="{col:.0f}" y2="170" stroke="{MUTED}" opacity=".5"/>'
        f'<line x1="{2 * col:.0f}" y1="60" x2="{2 * col:.0f}" y2="170" stroke="{MUTED}" opacity=".5"/>'
    )
    cols = [
        (f"{total:,}", "Total Contributions", f"{fmt(days[0][0])}, {days[0][0][:4]} – Present" if days else ""),
        (None, "Current Streak", rng(cr)),
        (f"{longest:,}", "Longest Streak", rng(lr)),
    ]
    for i, (big, label, sub) in enumerate(cols):
        cx = col * i + col / 2
        if big is None:
            out += ring(round(cx), 98, 36, ICON, f"{cur}", None, "big", 26)
        else:
            out += f'<text x="{cx:.0f}" y="110" text-anchor="middle" class="big">{big}</text>'
        out += (
            f'<text x="{cx:.0f}" y="158" text-anchor="middle" class="lab">{label}</text>'
            f'<text x="{cx:.0f}" y="178" text-anchor="middle" class="rng">{sub}</text>'
        )
    return out


def overview_card(u):
    W, gap, top_h, bot_h = 900, 12, 210, 195
    half = (W - gap) // 2
    days = calendar_days(u)
    body = (
        panel(0, 0, half, top_h, "GitHub Stats", stats_inner(u, days))
        + panel(half + gap, 0, half, top_h, "Most Used Languages", langs_inner(u, half))
        + panel(0, top_h + gap, W, bot_h, "Contribution Streak (last 12 months)", streak_inner(u, days, W))
    )
    H = top_h + gap + bot_h
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">\n'
        f"{STYLE}\n{body}\n</svg>"
    )


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
    files = {"overview.svg": overview_card(u)}
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
