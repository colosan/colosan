"""Render assets/stage.svg and README.md for the current mode (day/night)."""
import hashlib
import html
import re
from urllib.parse import quote

from common import ROOT, load_state, mode, repo, seeded

W, H = 800, 380
FLOOR_Y = 318


def esc(text):
    return html.escape(str(text), quote=True)


def md_text(text):
    """Escape visitor text for README: no HTML, no markdown links, no mentions."""
    text = html.escape(text, quote=True)
    text = re.sub(r"([\\`*_\[\]()#|~!>])", r"\\\1", text)
    return text.replace("@", "@​")


def issue_link(title, body=""):
    url = f"https://github.com/{repo()}/issues/new?title={quote(title)}"
    return url + (f"&body={quote(body)}" if body else "")


# ---------------------------------------------------------------- stage parts

def defs():
    return """
  <defs>
    <linearGradient id="fold" x1="0" x2="0.18" y1="0" y2="0" spreadMethod="reflect">
      <stop offset="0" stop-color="#8e1b2a"/><stop offset="1" stop-color="#c63345"/>
    </linearGradient>
    <linearGradient id="floor" x1="0" x2="0" y1="0" y2="1">
      <stop offset="0" stop-color="#a8703f"/><stop offset="1" stop-color="#6b4224"/>
    </linearGradient>
    <linearGradient id="beam" x1="0" x2="0" y1="0" y2="1">
      <stop offset="0" stop-color="#fff6d5" stop-opacity="0.35"/>
      <stop offset="1" stop-color="#fff6d5" stop-opacity="0.02"/>
    </linearGradient>
    <filter id="glow" x="-80%" y="-80%" width="260%" height="260%">
      <feGaussianBlur stdDeviation="3" result="b"/>
      <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
  </defs>"""


def curtains(open_width):
    """Side curtains; open_width is how far each curtain reaches into the stage."""
    w = open_width
    left = f'<path d="M0,30 H{w} Q{w - 40},170 {w - 10},{FLOOR_Y} H0 Z" fill="url(#fold)"/>'
    right = (
        f'<path d="M{W},30 H{W - w} Q{W - w + 40},170 {W - w + 10},{FLOOR_Y} H{W} Z" '
        f'fill="url(#fold)"/>'
    )
    tie = (
        f'<ellipse cx="{w - 22}" cy="200" rx="9" ry="5" fill="#e8b84a"/>'
        f'<ellipse cx="{W - w + 22}" cy="200" rx="9" ry="5" fill="#e8b84a"/>'
    )
    return left + right + tie


def valance():
    scallops = "".join(
        f'<circle cx="{x}" cy="34" r="20" fill="#a3202f"/>' for x in range(20, W + 1, 40)
    )
    return (
        f'<rect x="0" y="0" width="{W}" height="36" fill="#a3202f"/>{scallops}'
        f'<rect x="0" y="0" width="{W}" height="8" fill="#e8b84a"/>'
    )


def floor(label):
    return (
        f'<rect x="0" y="{FLOOR_Y}" width="{W}" height="{H - FLOOR_Y}" fill="url(#floor)"/>'
        f'<rect x="0" y="{FLOOR_Y}" width="{W}" height="4" fill="#3d2513" opacity="0.5"/>'
        f'<text x="{W / 2}" y="{H - 22}" text-anchor="middle" font-size="13" '
        f'letter-spacing="4" fill="#f3dfc1" opacity="0.85">{esc(label)}</text>'
    )


def frame(sky, middle, label, curtain_w):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
        f'font-family="ui-sans-serif, -apple-system, Segoe UI, Helvetica, Arial, sans-serif">'
        f"{defs()}{sky}{middle}{floor(label)}{curtains(curtain_w)}{valance()}</svg>\n"
    )


# ---------------------------------------------------------------- day

def day_svg(state):
    game = state["game"]
    last = game["guesses"][-1] if game["guesses"] else None
    if last:
        arrow = "▲ UP" if last["hint"] == "UP" else "▼ DOWN"
        status = f"@{last['user']} picked {last['n']}  →  {arrow}"
    elif state.get("last_winner"):
        w = state["last_winner"]
        status = f"last round: @{w['user']} found {w['n']} in {w['tries']} tries"
    else:
        status = "be the first to guess!"

    clouds = "".join(
        f'<g opacity="0.9"><animateTransform attributeName="transform" type="translate" '
        f'values="{-160 - off},0; {W + 60},0" dur="{dur}s" begin="-{beg}s" repeatCount="indefinite"/>'
        f'<g transform="translate(0,{y})" fill="#ffffff">'
        f'<ellipse cx="0" cy="0" rx="36" ry="14"/><ellipse cx="24" cy="-8" rx="24" ry="14"/>'
        f'<ellipse cx="-20" cy="-4" rx="18" ry="11"/></g></g>'
        for y, dur, beg, off in ((80, 46, 10, 0), (130, 62, 40, 40), (60, 75, 55, 80))
    )
    rays = "".join(
        f'<rect x="-3" y="-58" width="6" height="16" rx="3" fill="#ffc93c" '
        f'transform="rotate({a})"/>'
        for a in range(0, 360, 30)
    )
    sky = (
        '<linearGradient id="daysky" x1="0" x2="0" y1="0" y2="1">'
        '<stop offset="0" stop-color="#7cc8f7"/><stop offset="1" stop-color="#dff3ff"/>'
        f'</linearGradient><rect width="{W}" height="{FLOOR_Y}" fill="url(#daysky)"/>'
        f'<g transform="translate(600,100)"><g>{rays}<animateTransform attributeName="transform" '
        'type="rotate" values="0;360" dur="40s" repeatCount="indefinite"/></g>'
        '<circle r="34" fill="#ffd95a"/></g>'
        f"{clouds}"
    )

    bx, by, bw, bh = 250, 112, 300, 170
    board = (
        # ropes from the valance
        f'<line x1="{bx + 40}" y1="30" x2="{bx + 40}" y2="{by}" stroke="#5b3a1e" stroke-width="3"/>'
        f'<line x1="{bx + bw - 40}" y1="30" x2="{bx + bw - 40}" y2="{by}" stroke="#5b3a1e" stroke-width="3"/>'
        '<g><animateTransform attributeName="transform" type="rotate" '
        f'values="-1 {W / 2} 30; 1 {W / 2} 30; -1 {W / 2} 30" dur="6s" repeatCount="indefinite"/>'
        f'<rect x="{bx}" y="{by}" width="{bw}" height="{bh}" rx="14" fill="#fff8e7" '
        'stroke="#5b3a1e" stroke-width="5"/>'
        f'<text x="{W / 2}" y="{by + 34}" text-anchor="middle" font-size="18" font-weight="700" '
        f'letter-spacing="3" fill="#c63345">UP &amp; DOWN · ROUND {game["round"]}</text>'
        f'<text x="{W / 2}" y="{by + 100}" text-anchor="middle" font-size="54" font-weight="800" '
        f'fill="#2b2118">{game["lo"]} ~ {game["hi"]}</text>'
        f'<text x="{W / 2}" y="{by + 140}" text-anchor="middle" font-size="14" '
        f'fill="#6b5a48">{esc(status)}</text></g>'
    )
    spot = f'<ellipse cx="{W / 2}" cy="{FLOOR_Y + 8}" rx="150" ry="10" fill="#000" opacity="0.12"/>'
    return frame(sky, spot + board, "MORNING STAGE", 120)


# ---------------------------------------------------------------- night

def star_shape(r):
    pts = []
    for i in range(10):
        rad = r if i % 2 == 0 else r * 0.45
        a = -90 + i * 36
        from math import cos, radians, sin

        pts.append(f"{rad * cos(radians(a)):.1f},{rad * sin(radians(a)):.1f}")
    return " ".join(pts)


def hanging_star(star, i, total):
    # Spread stars evenly across the stage, jitter a little, vary string length.
    lane = (i + 0.5) / total
    x = 150 + lane * (W - 300) + (seeded(star["user"], star["at"], "x") - 0.5) * 18
    length = 70 + seeded(star["user"], star["at"], "len") * 150
    sway = 2 + seeded(star["user"], star["at"], "sway") * 4
    dur = 3.5 + seeded(star["user"], star["at"], "dur") * 3
    r = 11 + seeded(star["user"], star["at"], "r") * 5
    hue = ["#ffe27a", "#fff2b8", "#ffd1a8", "#cfe8ff"][int(seeded(star["user"], "c") * 4)]
    return (
        f'<g transform="translate({x:.1f},0)"><g>'
        f'<animateTransform attributeName="transform" type="rotate" '
        f'values="-{sway:.1f} 0 30; {sway:.1f} 0 30; -{sway:.1f} 0 30" dur="{dur:.1f}s" '
        f'repeatCount="indefinite"/>'
        f'<line x1="0" y1="30" x2="0" y2="{length:.0f}" stroke="#c9c3e6" stroke-width="1" opacity="0.55"/>'
        f'<g transform="translate(0,{length + r:.0f})">'
        f'<polygon points="{star_shape(r)}" fill="{hue}" filter="url(#glow)">'
        f'<animate attributeName="opacity" values="1;0.55;1" dur="{dur * 0.8:.1f}s" '
        f'repeatCount="indefinite"/></polygon>'
        f'<text y="{r + 15:.0f}" text-anchor="middle" font-size="11" fill="#e9e4ff" '
        f'opacity="0.9">@{esc(star["user"])}</text></g></g></g>'
    )


def night_svg(state):
    stars = state["stars"]
    specks = "".join(
        f'<circle cx="{seeded("bg", k, "x") * W:.0f}" cy="{40 + seeded("bg", k, "y") * 240:.0f}" '
        f'r="{0.6 + seeded("bg", k, "r") * 1.2:.1f}" fill="#fff">'
        f'<animate attributeName="opacity" values="0.2;0.9;0.2" dur="{2 + seeded("bg", k, "d") * 4:.1f}s" '
        f'repeatCount="indefinite"/></circle>'
        for k in range(70)
    )
    sky = (
        '<linearGradient id="nightsky" x1="0" x2="0" y1="0" y2="1">'
        '<stop offset="0" stop-color="#0b1030"/><stop offset="1" stop-color="#2a2160"/>'
        f'</linearGradient><rect width="{W}" height="{FLOOR_Y}" fill="url(#nightsky)"/>{specks}'
        '<mask id="crescent"><rect width="100%" height="100%" fill="#fff"/>'
        '<circle cx="138" cy="270" r="20" fill="#000"/></mask>'
        '<circle cx="128" cy="278" r="18" fill="#fdf3c4" mask="url(#crescent)" filter="url(#glow)"/>'
    )
    beam = (
        f'<polygon points="{W / 2 - 20},36 {W / 2 + 20},36 {W / 2 + 160},{FLOOR_Y + 10} '
        f'{W / 2 - 160},{FLOOR_Y + 10}" fill="url(#beam)"/>'
        f'<ellipse cx="{W / 2}" cy="{FLOOR_Y + 10}" rx="165" ry="12" fill="#fff6d5" opacity="0.18"/>'
    )
    if stars:
        hung = "".join(hanging_star(s, i, len(stars)) for i, s in enumerate(stars))
    else:
        hung = (
            f'<text x="{W / 2}" y="190" text-anchor="middle" font-size="16" fill="#e9e4ff" '
            'opacity="0.8">the sky is empty — hang the first star ✦</text>'
        )
    label = f"NIGHT STAGE · {len(stars)} STAR{'S' if len(stars) != 1 else ''}"
    return frame(sky, beam + hung, label, 100)


# ---------------------------------------------------------------- README

def img_tag(svg):
    v = hashlib.sha1(svg.encode()).hexdigest()[:8]
    return f'<img src="assets/stage.svg?v={v}" width="100%" alt="stage">'


def number_grid(game):
    rows = []
    for r in range(10):
        cells = []
        for c in range(1, 11):
            n = r * 10 + c
            if game["lo"] <= n <= game["hi"]:
                cells.append(f'<td align="center"><a href="{issue_link(f"guess:{n}")}">{n}</a></td>')
            else:
                cells.append('<td align="center">·</td>')
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return "<table>\n" + "\n".join(rows) + "\n</table>"


def day_readme(state, svg):
    game = state["game"]
    log = "\n".join(
        f"- @{g['user']} → **{g['n']}** {'⬆️ UP' if g['hint'] == 'UP' else '⬇️ DOWN'}"
        for g in reversed(game["guesses"][-10:])
    ) or "- 아직 아무도 찔러보지 않았어요."
    ranks = sorted(state["wins"].items(), key=lambda kv: (-kv[1], kv[0]))[:10]
    fame = "\n".join(f"{i}. @{u} — {w}승" for i, (u, w) in enumerate(ranks, 1)) or "비어 있어요. 첫 이름이 되어주세요."
    return f"""<div align="center">

{img_tag(svg)}

### ☀️ 아침의 무대 — 숫자 업다운

비밀 숫자는 **{game['lo']} ~ {game['hi']}** 사이 어딘가에 있어요.<br>
숫자를 누르면 Issue 창이 열려요. 그대로 **Submit** 하면 1분쯤 뒤에 무대에 반영돼요.

{number_grid(game)}

</div>

<details>
<summary>📜 이번 라운드 기록</summary>

{log}

</details>

<details>
<summary>🏆 명예의 전당</summary>

{fame}

</details>

<p align="center"><sub>🌙 KST 19시가 되면 무대에 밤이 찾아오고, 하늘에 별을 걸 수 있어요.</sub></p>
"""


def night_readme(state, svg):
    stars = state["stars"]
    star_link = issue_link("star", "이 줄을 지우고 별에 적을 한마디를 써주세요")
    if stars:
        readings = "\n".join(
            f"<details><summary>⭐ @{s['user']} <sub>{s['at']}</sub></summary>\n\n"
            f"> {md_text(s['msg'])}\n\n</details>"
            for s in reversed(stars)
        )
    else:
        readings = "<p align=\"center\"><i>아직 걸린 별이 없어요.</i></p>"
    return f"""<div align="center">

{img_tag(svg)}

### 🌙 밤의 무대 — 별 걸기

**[⭐ 내 별 하나 걸기]({star_link})**

한마디를 적어 별을 걸면 무대 위에 매달려 흔들려요.<br>
아래 별을 눌러 다른 사람이 남긴 말을 읽어보세요.

</div>

{readings}

<p align="center"><sub>☀️ KST 07시가 되면 막이 바뀌고 아침 게임이 시작돼요.</sub></p>
"""


def main():
    state = load_state()
    if mode() == "day":
        svg = day_svg(state)
        readme = day_readme(state, svg)
    else:
        svg = night_svg(state)
        readme = night_readme(state, svg)
    (ROOT / "assets" / "stage.svg").write_text(svg, encoding="utf-8")
    (ROOT / "README.md").write_text(readme, encoding="utf-8")


if __name__ == "__main__":
    main()
