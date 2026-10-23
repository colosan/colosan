"""Render the pixel-art profile scene: assets/night.svg (dark mode) and assets/day.svg (light mode).

A bloom of light opens over an indigo void. Feathers and stray bits fall, and a red
thread hangs down to a blinking terminal cursor. The ground is the real contribution
graph lit from above; the sky's sparkles are reseeded every day.
"""
import json
import math
import os
import random
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
W, H = 320, 160          # logical pixels
SCALE = 3
CELL, GAP = 3, 2         # contribution graph cell size and spacing
GRID_TOP = H - 4 - 7 * (CELL + GAP) + GAP
GROUND = GRID_TOP - 3
TITLE = os.environ.get("SCENE_TITLE", "COLOSAN")
TAU = math.tau
CX = W // 2
TODAY = (datetime.now(timezone.utc) + timedelta(hours=9)).strftime("%Y-%m-%d")


def rng(*parts):
    return random.Random(":".join(map(str, parts)))


# ---------------------------------------------------------------- data

def fetch_days():
    """Contribution counts as weeks of 7 days (oldest first), or None if unavailable."""
    token = os.environ.get("GITHUB_TOKEN")
    login = os.environ.get("GITHUB_REPOSITORY_OWNER")
    if not token or not login:
        return None
    query = """query($login:String!){user(login:$login){contributionsCollection{
      contributionCalendar{weeks{contributionDays{contributionCount weekday}}}}}}"""
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": {"login": login}}).encode(),
        headers={"Authorization": f"bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.load(r)
        weeks = data["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]
        out = []
        for w in weeks:
            days = [None] * 7
            for d in w["contributionDays"]:
                days[d["weekday"]] = d["contributionCount"]
            out.append(days)
        return out
    except Exception as e:  # keep the scene alive even if the API hiccups
        print("contributions unavailable:", e)
        return None


def placeholder_days():
    r = rng("placeholder")
    return [[max(0, int(r.gauss(3, 4))) if r.random() < 0.7 else 0 for _ in range(7)] for _ in range(53)]


# ---------------------------------------------------------------- pixel layer

class Px:
    """Sparse pixel buffer emitted as horizontally merged rects."""

    def __init__(self):
        self.p = {}

    def set(self, x, y, c):
        self.p[(int(x), int(y))] = c

    def rect(self, x, y, w, h, c):
        for yy in range(int(y), int(y + h)):
            for xx in range(int(x), int(x + w)):
                self.set(xx, yy, c)

    def sprite(self, x, y, rows, colors):
        for dy, row in enumerate(rows):
            for dx, ch in enumerate(row):
                if ch in colors:
                    self.set(x + dx, y + dy, colors[ch])

    def svg(self):
        rows = {}
        for (x, y), c in self.p.items():
            rows.setdefault(y, []).append((x, c))
        out = []
        for y in sorted(rows):
            run = sorted(rows[y])
            sx, sc, n = run[0][0], run[0][1], 1
            for x, c in run[1:] + [(None, None)]:
                if x == sx + n and c == sc:
                    n += 1
                    continue
                out.append(f'<rect x="{sx}" y="{y}" width="{n}" height="1" fill="{sc}"/>')
                if x is not None:
                    sx, sc, n = x, c, 1
        return "".join(out)


def g(content, cls=None, style=None, **attrs):
    a = "".join(f' {k.replace("_", "-")}="{v}"' for k, v in attrs.items())
    if cls:
        a += f' class="{cls}"'
    if style:
        a += f' style="{style}"'
    return f"<g{a}>{content}</g>"


# ---------------------------------------------------------------- palettes

PAL = {
    "night": {
        "sky": ["#121329", "#171834", "#1c1e40", "#21244b", "#252955", "#232650", "#1b1c3d"],
        "burst": ["#ffffff", "#eceaf8", "#cfcdee", "#a3a6dd", "#7177c6"],
        "streak": "#4c56b8",
        "beam": "#e9e7ff",
        "dot": ["#5d6099", "#7d80bd", "#a9abe0"],
        "spark": ["#ffffff", "#dcdaf6", "#8e92d8"],
        "feather": {"a": "#ffffff", "b": "#d6d4f2", "c": "#9da0da"},
        "bit": "#8f93d6",
        "ground": "#101126", "mist": "#6e72b8",
        "levels": ["#191a36", "#272b5e", "#3b4290", "#636bc4", "#b9bcf2"],
        "glow": "#c9c8ff",
        "title": "#e7e5f8", "title_shadow": "#2c2e66", "prompt": "#8e92d8", "shine": "#ffffff",
    },
    "day": {
        "sky": ["#f6f5fc", "#eeedf9", "#e2e1f5", "#d3d3ef", "#c2c3e7", "#b0b3de", "#a1a5d6"],
        "burst": ["#ffffff", "#ffffff", "#f3f2fc", "#d9d8f2", "#b2b5e3"],
        "streak": "#7d86d4",
        "beam": "#ffffff",
        "dot": ["#c9c9ec", "#b4b6e3", "#9fa3d9"],
        "spark": ["#ffffff", "#e7e6f8", "#a7aade"],
        "feather": {"a": "#ffffff", "b": "#e4e3f6", "c": "#8f94d2"},
        "bit": "#7d82c8",
        "ground": "#3d4280", "mist": "#ffffff",
        "levels": ["#454b8a", "#565da0", "#737ac0", "#9da2dc", "#e4e4fa"],
        "glow": "#ffffff",
        "title": "#2d2f63", "title_shadow": "#c5c6ea", "prompt": "#6f75c2", "shine": "#ffffff",
    },
}
RED, RED_HI = "#c0283c", "#e2556a"

CSS = """
.tw{animation:tw 3s steps(1,end) infinite}
@keyframes tw{0%,100%{opacity:1}50%{opacity:.15}}
.big{animation:big 2.8s steps(1,end) infinite}
.small{animation:big 2.8s steps(1,end) infinite;animation-delay:-1.4s}
@keyframes big{0%,100%{opacity:1}50%{opacity:0}}
.breathe{animation:breathe 6s ease-in-out infinite}
@keyframes breathe{0%,100%{opacity:.45}50%{opacity:1}}
.pulse{animation:pulse 9s steps(1,end) infinite}
@keyframes pulse{0%,100%{transform:translateY(0)}33%{transform:translateY(1px)}66%{transform:translateY(2px)}}
.fall{animation:fall 22s steps(180) infinite}
@keyframes fall{0%{transform:translateY(0);opacity:0}6%{opacity:1}86%{opacity:1}100%{transform:translateY(150px);opacity:0}}
.sway{animation:sway 4s steps(1,end) infinite}
@keyframes sway{0%,100%{transform:translateX(0)}25%{transform:translateX(2px)}50%{transform:translateX(3px)}75%{transform:translateX(1px)}}
.flipA{animation:flip 1.6s steps(1,end) infinite}
.flipB{animation:flip 1.6s steps(1,end) infinite;animation-delay:-.8s}
@keyframes flip{0%,100%{opacity:1}50%{opacity:0}}
.threadA{animation:flip 3.2s steps(1,end) infinite}
.threadB{animation:flip 3.2s steps(1,end) infinite;animation-delay:-1.6s}
.cursor{animation:flip 1.1s steps(1,end) infinite}
.rise{animation:rise 16s steps(90) infinite}
@keyframes rise{0%{transform:translateY(0);opacity:0}15%{opacity:1}80%{opacity:.8}100%{transform:translateY(-90px);opacity:0}}
.mist{animation:mist 80s steps(320) infinite}
@keyframes mist{to{transform:translateX(-320px)}}
"""


# ---------------------------------------------------------------- dithering

def dither_defs(colors, prefix):
    """Patterns blending colors[i] into colors[i+1] at 25/50/75%."""
    masks = {1: [(0, 0)], 2: [(0, 0), (1, 1)], 3: [(0, 0), (1, 1), (1, 0)]}
    out = []
    for i in range(len(colors) - 1):
        a, b = colors[i], colors[i + 1]
        for k, pts in masks.items():
            dots = "".join(f'<rect x="{x}" y="{y}" width="1" height="1" fill="{b}"/>' for x, y in pts)
            out.append(
                f'<pattern id="{prefix}{i}_{k}" width="2" height="2" patternUnits="userSpaceOnUse">'
                f'<rect width="2" height="2" fill="{a}"/>{dots}</pattern>'
            )
    return "".join(out)


def banded(colors, prefix, y0, y1):
    n = len(colors)
    band = (y1 - y0) / n
    out = []
    for i, c in enumerate(colors):
        top = round(y0 + i * band)
        bot = round(y0 + (i + 1) * band)
        out.append(f'<rect x="0" y="{top}" width="{W}" height="{bot - top}" fill="{c}"/>')
        if i < n - 1:
            for k in (1, 2, 3):
                out.append(f'<rect x="0" y="{bot - 4 + k}" width="{W}" height="1" fill="url(#{prefix}{i}_{k})"/>')
    return "".join(out)


def checker(pid, color):
    return (f'<pattern id="{pid}" width="2" height="2" patternUnits="userSpaceOnUse">'
            f'<rect width="1" height="1" fill="{color}"/></pattern>')


# ---------------------------------------------------------------- scene pieces

def burst(pal):
    """Feathery bloom of light opening downward from above the frame."""
    cy = -26
    core, rim = Px(), Px()
    lobes = [(5, 0.10, 0.3), (9, 0.07, 1.7), (14, 0.05, 0.9), (23, 0.035, 2.4)]
    bands = [(0.7, 0), (0.74, (0, 1)), (0.84, 1), (0.87, (1, 2)), (0.94, 2), (0.96, (2, 3)), (1.0, 3)]
    for y in range(0, 72):
        for x in range(0, W):
            dx, dy = (x - CX) / 2.6, (y - cy)
            r = math.hypot(dx, dy)
            th = math.atan2(dy, dx)
            t = r / (70 * (1 + sum(a * math.sin(k * th + p) for k, a, p in lobes)))
            if t > 1.12:
                continue
            on = (x + y) % 2 == 0
            if t >= 1.0:
                if on:
                    rim.set(x, y, pal["burst"][4])
                continue
            for limit, idx in bands:
                if t < limit:
                    c = pal["burst"][idx] if isinstance(idx, int) else pal["burst"][idx[0] if on else idx[1]]
                    break
            # Thin radial brush strokes near the rim, like feathers.
            if 0.74 < t < 0.98 and abs(math.sin(th * 46 + 3 * math.sin(th * 5))) < 0.07:
                c = pal["streak"] if t > 0.86 else pal["burst"][3]
            core.set(x, y, c)
    return g(rim.svg(), cls="breathe") + g(core.svg(), cls="pulse")


def beam():
    pts = f"{CX - 30},40 {CX + 30},40 {CX + 80},{GROUND} {CX - 80},{GROUND}"
    return f'<polygon points="{pts}" fill="url(#beamdots)" opacity=".06" class="breathe"/>'


def sky_dots(pal):
    r = rng("dots", TODAY)
    p, tw = Px(), []
    for _ in range(140):
        x, y = r.randrange(1, W - 1), r.randrange(20, GROUND - 6)
        c = r.choice(pal["dot"])
        if r.random() < 0.7:
            p.set(x, y, c)
        else:
            tw.append(g(f'<rect x="{x}" y="{y}" width="1" height="1" fill="{c}"/>', cls="tw",
                        style=f"animation-delay:-{r.uniform(0, 3):.2f}s;animation-duration:{r.uniform(2, 5):.1f}s"))
    return p.svg() + "".join(tw)


def sparkle(x, y, size, pal, delay):
    white, mid, far = pal["spark"]
    big, small = Px(), Px()
    for s in (big, small):
        s.set(x, y, white)
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        small.set(x + dx, y + dy, mid)
        reach = size + (size // 2 if dy else 0)  # crosses are taller than wide
        for i in range(1, reach + 1):
            c = white if i == 1 else mid if i <= reach * 0.6 else far
            big.set(x + dx * i, y + dy * i, c)
    return (g(big.svg(), cls="big", style=f"animation-delay:-{delay:.2f}s")
            + g(small.svg(), cls="small", style=f"animation-delay:-{delay + 1.4:.2f}s"))


def sparkles(pal):
    r = rng("sparkles", TODAY)
    spots = [(22, GROUND - 14, 5), (298, GROUND - 26, 4)]
    for _ in range(9):
        spots.append((r.randrange(10, W - 10), r.randrange(30, GROUND - 20), r.choice((2, 3, 3, 4))))
    return "".join(sparkle(x, y, size, pal, r.uniform(0, 2.8)) for x, y, size in spots)


FEATHER_A = ["..ab", ".abb", "abb.", "bc..", "c..."]
FEATHER_B = ["ba..", "bba.", ".bba", "..cb", "...c"]
BITS = {
    "0": ["###", "#.#", "#.#", "#.#", "###"],
    "1": [".#.", "##.", ".#.", ".#.", "###"],
}


def falling(pal):
    r = rng("falling")
    out = []
    for i in range(14):
        x = r.choice((r.randrange(CX - 100, CX - 24), r.randrange(CX + 24, CX + 100)))
        y = r.randrange(-6, 12)
        a, b = Px(), Px()
        if i % 2 == 0:
            a.sprite(x, y, FEATHER_A, pal["feather"])
            b.sprite(x, y, FEATHER_B, pal["feather"])
        else:
            a.sprite(x, y, BITS["0"], {"#": pal["bit"]})
            b.sprite(x, y, BITS["1"], {"#": pal["bit"]})
        flip = g(a.svg(), cls="flipA") + g(b.svg(), cls="flipB")
        dur = r.uniform(18, 30)
        sway = g(flip, cls="sway", style=f"animation-delay:-{r.uniform(0, 4):.1f}s")
        out.append(g(sway, cls="fall", style=f"animation-duration:{dur:.1f}s;animation-delay:-{r.uniform(0, dur):.1f}s"))
    return "".join(out)


FONT = {
    "A": [".###.", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"],
    "C": [".###.", "#...#", "#....", "#....", "#....", "#...#", ".###."],
    "L": ["#....", "#....", "#....", "#....", "#....", "#....", "#####"],
    "N": ["#...#", "##..#", "#.#.#", "#..##", "#...#", "#...#", "#...#"],
    "O": [".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."],
    "S": [".####", "#....", "#....", ".###.", "....#", "....#", "####."],
    ">": ["#....", ".#...", "..#..", "...#.", "..#..", ".#...", "#...."],
}


def glyph_cells(text, x0, y0, s, gap):
    cells = []
    for i, ch in enumerate(text):
        for gy, row in enumerate(FONT.get(ch, FONT["O"])):
            for gx, on in enumerate(row):
                if on == "#":
                    cells.append((x0 + (i * (5 + gap) + gx) * s, y0 + gy * s))
    return cells


def prompt(pal, y0=88):
    """`> NAME` with a blinking block cursor; returns (svg, cursor top-center)."""
    s, gap = 2, 1
    name_w = (len(TITLE) * (5 + gap) - gap) * s
    total = (6 + 1) * s + name_w + 3 * s + 3 * s
    x0 = CX - total // 2
    arrow = glyph_cells(">", x0, y0, s, gap)
    nx = x0 + 7 * s
    name = glyph_cells(TITLE, nx, y0, s, gap)
    cx = nx + name_w + 2 * s
    rect = lambda cells, d=0: "".join(f'<rect x="{x + d}" y="{y + d}" width="{s}" height="{s}"/>' for x, y in cells)
    keyframes = (f"@keyframes shine{{0%{{transform:translateX(0)}}35%,100%{{transform:translateX({name_w + 14}px)}}}}"
                 ".shine{animation:shine 6s steps(30) infinite}")
    svg = (
        f"<style>{keyframes}</style>"
        f'<clipPath id="tclip">{rect(name)}</clipPath>'
        f'<g fill="{pal["title_shadow"]}">{rect(name, 1)}{rect(arrow, 1)}</g>'
        f'<g fill="{pal["prompt"]}">{rect(arrow)}</g>'
        f'<g fill="{pal["title"]}">{rect(name)}</g>'
        f'<g clip-path="url(#tclip)"><rect class="shine" x="{nx - 8}" y="{y0}" width="4" height="{7 * s}" fill="{pal["shine"]}"/></g>'
        f'<rect class="cursor" x="{cx}" y="{y0}" width="{3 * s}" height="{7 * s}" fill="{RED}"/>'
    )
    return svg, (cx + 3 * s // 2, y0)


def thread(end, sway):
    """Red thread from inside the light down to the cursor."""
    p = Px()
    x0, y0 = CX - 4, 30
    x1, y1 = end
    mx, my = (x0 + x1) / 2 + sway, (y0 + y1) / 2 + 8
    prev = None
    for i in range(261):
        t = i / 260
        x = (1 - t) ** 2 * x0 + 2 * (1 - t) * t * mx + t * t * x1
        y = (1 - t) ** 2 * y0 + 2 * (1 - t) * t * my + t * t * y1
        pt = (round(x), round(y))
        if pt != prev:
            p.set(*pt, RED_HI if i % 37 == 0 else RED if t > 0.08 else "#e9a3ae")
            prev = pt
    return p.svg()


def contributions(days, pal):
    """The contribution graph as glowing ground, lit hardest under the beam."""
    days = (days or placeholder_days())[-53:]
    flat = [c for w in days for c in w if c is not None]
    peak = max(flat) if flat else 0
    peak_seen = False
    x0 = (W - (53 * (CELL + GAP) - GAP)) // 2
    ground = f'<rect x="0" y="{GROUND}" width="{W}" height="{H - GROUND}" fill="{pal["ground"]}"/>'
    cells, glows = Px(), []
    r = rng("cells")
    for wi, week in enumerate(days):
        for di, count in enumerate(week):
            if count is None:
                continue
            x, y = x0 + wi * (CELL + GAP), GRID_TOP + di * (CELL + GAP)
            level = 0 if count == 0 else min(4, 1 + int(3.999 * math.sqrt(count / peak))) if peak else 0
            color = pal["levels"][level]
            if count == peak and peak and not peak_seen:
                color, peak_seen = RED, True
            cells.rect(x, y, CELL, CELL, color)
            if level == 4:
                glows.append(g(f'<rect x="{x}" y="{y}" width="{CELL}" height="{CELL}" fill="{pal["glow"]}"/>', cls="tw",
                               style=f"animation-delay:-{r.uniform(0, 6):.1f}s;animation-duration:{r.uniform(4, 9):.1f}s"))
            if color == RED:
                halo = Px()
                for dy in range(-2, CELL + 2):
                    for dx in range(-2, CELL + 2):
                        if (dx + dy) % 2 == 0 and not (0 <= dx < CELL and 0 <= dy < CELL):
                            halo.set(x + dx, y + dy, RED)
                glows.append(g(halo.svg(), cls="breathe", opacity=0.45,
                               style=f"animation-delay:-{r.uniform(0, 6):.1f}s"))
    # Light from the beam pools on the middle of the graph.
    return ground + cells.svg() + "".join(glows)


def mist(pal):
    p = Px()
    for x in range(W * 2):
        t = x / W
        top = GROUND - 7 + round(2 * math.sin(TAU * 3 * t) + math.sin(TAU * 7 * t + 1))
        for y in range(top, GROUND + 1):
            if (x + y) % 2 == 0:
                p.set(x, y, pal["mist"])
    return g(g(p.svg(), cls="mist"), opacity=0.18)


def motes(pal):
    r = rng("motes")
    out = []
    for _ in range(16):
        x, y = r.randrange(20, W - 20), r.randrange(GRID_TOP, H - 6)
        dur = r.uniform(12, 22)
        out.append(g(f'<rect x="{x}" y="{y}" width="1" height="1" fill="{pal["spark"][1]}"/>', cls="rise",
                     style=f"animation-duration:{dur:.1f}s;animation-delay:-{r.uniform(0, dur):.1f}s"))
    return "".join(out)


def frame_clip():
    pts = [(0, 4), (1, 4), (1, 2), (2, 2), (2, 1), (4, 1), (4, 0)]
    path = []
    for corner in range(4):
        for x, y in pts:
            path.append([(x, y), (W - y, x), (W - x, H - y), (y, H - x)][corner])
    return '<clipPath id="frame"><polygon points="' + " ".join(f"{x},{y}" for x, y in path) + '"/></clipPath>'


# ---------------------------------------------------------------- compose

def scene(mode, days):
    pal = PAL[mode]
    prompt_svg, cursor = prompt(pal)
    threads = g(thread(cursor, -12), cls="threadA") + g(thread(cursor, -5), cls="threadB")
    body = (
        banded(pal["sky"], "ds", 0, GROUND)
        + sky_dots(pal)
        + beam()
        + burst(pal)
        + sparkles(pal)
        + threads
        + prompt_svg
        + falling(pal)
        + mist(pal)
        + contributions(days, pal)
        + motes(pal)
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W * SCALE}" height="{H * SCALE}" '
        f'shape-rendering="crispEdges"><style>{CSS}</style>'
        f'<defs>{dither_defs(pal["sky"], "ds")}{checker("beamdots", pal["beam"])}{frame_clip()}</defs>'
        f'<g clip-path="url(#frame)">{body}</g></svg>\n'
    )


def main():
    days = fetch_days()
    (ROOT / "assets").mkdir(exist_ok=True)
    for mode in ("day", "night"):
        (ROOT / "assets" / f"{mode}.svg").write_text(scene(mode, days), encoding="utf-8")


if __name__ == "__main__":
    main()
