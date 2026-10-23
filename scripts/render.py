"""Render the floating-island scene for each time of day.

The island's face is the real contribution graph (53 weeks x 7 days, in GitHub's own
greens); the sky, clouds, tree, house and waterfall are relit for dawn, morning,
noon and evening.

usage:
  python scripts/render.py now <out.svg>    # scene for the current hour in Seoul
  python scripts/render.py all <out_dir>    # all four scenes
"""
import json
import math
import os
import random
import re
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

W, H, SCALE = 384, 160, 3
TOP = 70                                  # grass line of the island
CELL, PITCH = 3, 4                        # contribution cell size / spacing
GRID_W, GRID_H = 53 * PITCH - 1, 7 * PITCH - 1
GX, GY = (W - GRID_W) // 2, TOP + 5
IL, IR = GX - 10, GX + GRID_W + 9         # island left/right edges
SEA_Y = 138                               # top of the front cloud sea
TREE_X, HOUSE_X, LAMP_X = 122, 236, 222
LOGIN = os.environ.get("GITHUB_REPOSITORY_OWNER", "colosan")

GH_LIGHT = ["#9be9a8", "#40c463", "#30a14e", "#216e39"]
GH_DARK = ["#0e4429", "#006d32", "#26a641", "#39d353"]


def rng(*parts):
    return random.Random(":".join(map(str, parts)))


# ---------------------------------------------------------------- contributions

LEVELS = {"NONE": 0, "FIRST_QUARTILE": 1, "SECOND_QUARTILE": 2, "THIRD_QUARTILE": 3, "FOURTH_QUARTILE": 4}


def weeks_from_days(days):
    """[(date, level)] -> 53 weeks of 7 levels (Sunday first, None outside the calendar)."""
    days = sorted(days)
    start = days[0][0] - timedelta(days=(days[0][0].weekday() + 1) % 7)
    weeks = {}
    for d, level in days:
        i = (d - start).days
        weeks.setdefault(i // 7, [None] * 7)[i % 7] = level
    out = [weeks.get(i, [None] * 7) for i in range(max(weeks) + 1)][-53:]
    return [[None] * 7] * (53 - len(out)) + out


def fetch_graphql(token):
    query = ("query($l:String!){user(login:$l){contributionsCollection{contributionCalendar"
             "{weeks{contributionDays{date contributionLevel}}}}}}")
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": {"l": LOGIN}}).encode(),
        headers={"Authorization": f"bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        weeks = json.load(r)["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]
    return weeks_from_days([(date.fromisoformat(d["date"]), LEVELS[d["contributionLevel"]])
                            for w in weeks for d in w["contributionDays"]])


def fetch_public():
    req = urllib.request.Request(f"https://github.com/users/{LOGIN}/contributions",
                                 headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        html = r.read().decode()
    days = []
    for td in re.findall(r"<td[^>]*ContributionCalendar-day[^>]*>", html):
        d, lv = re.search(r'data-date="([\d-]+)"', td), re.search(r'data-level="(\d)"', td)
        if d and lv:
            days.append((date.fromisoformat(d.group(1)), int(lv.group(1))))
    return weeks_from_days(days) if days else None


def load_levels():
    token = os.environ.get("GITHUB_TOKEN")
    sources = ([lambda: fetch_graphql(token)] if token else []) + [fetch_public]
    for source in sources:
        try:
            weeks = source()
            if weeks:
                return weeks
        except Exception as e:  # keep the scene alive even if GitHub hiccups
            print("contributions:", e, file=sys.stderr)
    r = rng("placeholder")
    return [[min(4, max(0, int(r.gauss(0.6, 1.3)))) for _ in range(7)] for _ in range(53)]


# ---------------------------------------------------------------- pixel buffer

class Px:
    """Sparse pixel buffer emitted as horizontally merged rects."""

    def __init__(self):
        self.p = {}

    def set(self, x, y, c):
        if c:
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

    def __contains__(self, xy):
        return xy in self.p

    def svg(self):
        """One <path> per color; runs are merged across rows into rectangles."""
        rows = {}
        for (x, y), c in self.p.items():
            rows.setdefault(y, []).append((x, c))
        active, done = {}, []
        for y in sorted(rows):
            items = sorted(rows[y])
            runs = []
            sx, sc, n = items[0][0], items[0][1], 1
            for x, c in items[1:] + [(None, None)]:
                if x == sx + n and c == sc:
                    n += 1
                    continue
                runs.append((sx, n, sc))
                if x is not None:
                    sx, sc, n = x, c, 1
            nxt = {}
            for run in runs:
                prev = active.pop(run, None)
                nxt[run] = [prev[0], prev[1] + 1] if prev and prev[0] + prev[1] == y else [y, 1]
                if prev and prev[0] + prev[1] != y:
                    done.append((run, prev))
            done.extend(active.items())
            active = nxt
        done.extend(active.items())
        by_color = {}
        for (x, w, c), (y0, h) in done:
            by_color.setdefault(c, []).append(f"M{x} {y0}h{w}v{h}h-{w}z")
        return "".join(f'<path fill="{c}" d="{"".join(d)}"/>' for c, d in by_color.items())


def g(content, cls=None, style=None, **attrs):
    a = "".join(f' {k.replace("_", "-")}="{v}"' for k, v in attrs.items())
    if cls:
        a += f' class="{cls}"'
    if style:
        a += f' style="{style}"'
    return f"<g{a}>{content}</g>"


def disc(cx, cy, r):
    return {(x, y)
            for y in range(math.floor(cy - r) - 1, math.ceil(cy + r) + 1)
            for x in range(math.floor(cx - r) - 1, math.ceil(cx + r) + 1)
            if (x + .5 - cx) ** 2 + (y + .5 - cy) ** 2 <= r * r}


def fill(cells, color):
    p = Px()
    for x, y in cells:
        p.set(x, y, color)
    return p.svg()


BAYER = [-.05, .03, .05, -.03]


def foliage(blobs, tones, light_x):
    """Clustered leaves: blobs [(cx, cy, r)] back to front, tones dark -> light."""
    owner = {}
    for i, (cx, cy, r) in enumerate(blobs):
        for xy in disc(cx, cy, r):
            owner[xy] = i
    lx, ly, lz = light_x * .55, -.72, .45
    n = math.sqrt(lx * lx + ly * ly + lz * lz)
    lx, ly, lz = lx / n, ly / n, lz / n
    px = Px()
    for (x, y), i in owner.items():
        cx, cy, r = blobs[i]
        nx, ny = (x + .5 - cx) / r, (y + .5 - cy) / r
        nz = math.sqrt(max(0.0, 1 - nx * nx - ny * ny))
        v = nx * lx + ny * ly + nz * lz + BAYER[(y % 2) * 2 + x % 2]
        t = 0 if v < -.2 else 1 if v < .15 else 2 if v < .45 else 3 if v < .72 else 4
        away = owner.get((x - light_x, y))
        below = owner.get((x, y + 1))
        if below is None:
            t = 0
        elif below != i or away != i:
            t = max(0, t - 1)
        px.set(x, y, tones[t])
    return px, owner


# ---------------------------------------------------------------- palettes

PAL = {
    "dawn": dict(
        sky=["#090a1f", "#0d0f2a", "#121536", "#181b43", "#1f2250", "#272a5d", "#302f68", "#3b3773"],
        light=1, orb=("moon", 320, 28, 8), orb_core="#f6efd6", orb_mid="#ddd2ad", halo="#8c95ff",
        stars=(110, 126), star_colors=["#ffffff", "#cdd5ff", "#ffeccc"], star_dim="#555a96",
        cloud=("#4b5194", "#353a7a", "#272b63"),
        sea_back="#2d3171", sea=("#717ac2", "#3f458b", "#2b2f6b"),
        rock=("#625690", "#4a4273", "#38315e", "#29244c", "#1b1737"),
        mortar="#211c3f", soil="#2e2851", levels=GH_DARK,
        grass=("#409070", "#2b6b56", "#1d4d42"),
        leaves=["#0e2a32", "#153b42", "#1d4e51", "#2a6664", "#4c8d98"],
        blossom=("#8f72a8", "#c0a2d8"),
        trunk=("#4a3d62", "#2e2546"),
        house=dict(r="#55406e", h="#6d5a92", q="#4a3762", R="#382a52", N="#241e3c", D="#241e3c", c="#4a4068", C="#2e2848", w="#4c4670", W="#383258",
                   T="#241e3c", n="#ffd27a", d="#2c2442", k="#ffd27a", s="#3a3456", S="#2a2444"),
        window_glow="#ffb347", lamp_on=True, lamp=("#fff1c4", "#ffb347", "#3a3456"),
        water=("#c9d0ff", "#7480cc", "#4a539c"),
        smoke=None, vine=("#245246", "#3e7a62"),
        flowers=["#c9b8ff", "#8fd0ff"],
        petals=None, birds=None, fireflies=True, shooting=True, grid_fx="glow", sheen=None,
    ),
    "morning": dict(
        sky=["#7c9be0", "#8faae6", "#a5b6ea", "#bdbfea", "#d6c6e8", "#eacde3", "#f7d5dc", "#ffe1d0"],
        light=-1, orb=("sun", 54, 114, 8), orb_core="#fffbee", orb_mid="#ffe6b8", halo="#ffc9a8",
        stars=None, star_colors=None, star_dim=None,
        cloud=("#fff8f5", "#f6d9e3", "#dcbad6"),
        sea_back="#efd9e9", sea=("#fff7f7", "#f3d7e4", "#d8b9d6"),
        rock=("#dcaaa4", "#b88693", "#966b81", "#755269", "#583e56"),
        mortar="#684961", soil="#866379", levels=GH_LIGHT,
        grass=("#c4f293", "#88d470", "#58a75f"),
        leaves=["#2b5a52", "#3a785e", "#549866", "#7cba72", "#c1e49b"],
        blossom=("#ff9fbf", "#ffd6e3"),
        trunk=("#a27168", "#734d59"),
        house=dict(r="#978bd4", h="#b6adea", q="#867ac6", R="#6c61a8", N="#7a5f78", D="#7a5f78", c="#c9a0a8", C="#9a7480", w="#fff3ea", W="#e4cbd5",
                   T="#7a5f78", n="#aac6f2", d="#9a6878", k="#ffd27a", s="#c4a8b8", S="#a48aa0"),
        window_glow=None, lamp_on=False, lamp=("#fff2d6", None, "#7a5f78"),
        water=("#ffffff", "#bed7f7", "#93ade6"),
        smoke="#ffffff", vine=("#4f8f6a", "#7ab27e"),
        flowers=["#ff9fbf", "#fff3a8", "#ffffff"],
        petals=("#ffb3cc", "#ffe3ec"), birds="#6b6b9e", fireflies=False, shooting=False, grid_fx="dew", sheen=None,
    ),
    "noon": dict(
        sky=["#2c6ddb", "#357ae2", "#4088e8", "#4f98ee", "#64aaf2", "#7fbcf6", "#9dcff9", "#c0e2fc"],
        light=1, orb=("sun", 304, 24, 9), orb_core="#ffffff", orb_mid="#fff4c4", halo="#fff1b0",
        stars=None, star_colors=None, star_dim=None,
        cloud=("#ffffff", "#e8f1fd", "#c3d7f3"),
        sea_back="#dceafc", sea=("#ffffff", "#e7f0fc", "#c1d5f2"),
        rock=("#e6c092", "#c4996e", "#9e7655", "#7a5b43", "#5a4334"),
        mortar="#6c503e", soil="#8b6a4e", levels=GH_LIGHT,
        grass=("#b8ee78", "#76c74f", "#46963f"),
        leaves=["#1c5035", "#296e40", "#3c9049", "#61b357", "#a4dc79"],
        blossom=("#ffb0c8", "#ffe2ec"),
        trunk=("#a2724d", "#6c4834"),
        house=dict(r="#6d86da", h="#93a8ee", q="#5d76cc", R="#4b61af", N="#6a5444", D="#6a5444", c="#c4a48a", C="#94735e", w="#fff8ec", W="#e6d5bf",
                   T="#6a5444", n="#c6e5ff", d="#8a5c3e", k="#ffd27a", s="#cdb9a0", S="#a8927a"),
        window_glow=None, lamp_on=False, lamp=("#fffbe8", None, "#6a5444"),
        water=("#ffffff", "#92d3ff", "#56a3e8"),
        smoke=None, vine=("#3f8a4a", "#6cb05e"),
        flowers=["#ffb3c8", "#fff07a", "#ffffff", "#b8a6ff"],
        petals=("#ffc4d6", "#ffffff"), birds="#3d4f7c", fireflies=False, shooting=False, grid_fx="sheen", sheen="#ffffff",
    ),
    "evening": dict(
        sky=["#221e58", "#2f2766", "#423075", "#5c3a85", "#7c458e", "#a2528f", "#c9618c", "#e8778a", "#fa9483", "#ffb47a"],
        light=1, orb=("bigsun", 340, 126, 15), orb_core="#fff2c8", orb_mid="#ffc884", halo="#ff9a72",
        stars=(26, 40), star_colors=["#ffffff", "#ffe0f0"], star_dim="#6a5a9a",
        cloud=("#ffc59c", "#df8a97", "#8b4e8d"),
        sea_back="#c97b9b", sea=("#ffd3a8", "#ea97a3", "#a0619b"),
        rock=("#f39a84", "#a8607f", "#764775", "#523466", "#36244c"),
        mortar="#432e5a", soil="#5a3d6c", levels=GH_DARK,
        grass=("#e8c272", "#7e9a5e", "#4d6a52"),
        leaves=["#28284a", "#383b5a", "#51575f", "#8a7a62", "#f2aa74"],
        blossom=("#ff9ab4", "#ffc8b4"),
        trunk=("#8a5060", "#4e3048"),
        house=dict(r="#875392", h="#c07a9a", q="#764886", R="#5c3a76", N="#3c2a4c", D="#3c2a4c", c="#a0687a", C="#6a4460", w="#f2c0a6", W="#9a6884",
                   T="#3c2a4c", n="#ffd27a", d="#4a3052", k="#ffd27a", s="#7a5878", S="#5a4060"),
        window_glow="#ffb347", lamp_on=True, lamp=("#fff1c4", "#ffa860", "#3c2a4c"),
        water=("#ffe2c4", "#d49ab8", "#8a64a8"),
        smoke="#d8a8c0", vine=("#4a6a52", "#7a8a5a"),
        flowers=["#ffd27a", "#ff9ab4"],
        petals=("#ffb36e", "#ffd9a0"), birds=None, fireflies=False, shooting=False, grid_fx="sheen", sheen="#ffd9b0",
    ),
}

CSS = """
.tw{animation:tw 3s steps(1,end) infinite}
@keyframes tw{0%,100%{opacity:1}50%{opacity:.2}}
.pulse{animation:pulse 5s ease-in-out infinite}
@keyframes pulse{0%,100%{opacity:.5}50%{opacity:1}}
.bob{animation:bob 3.2s steps(1,end) infinite}
@keyframes bob{0%,100%{transform:translateY(0)}50%{transform:translateY(-1px)}}
.left{animation:left 300s steps(384) infinite}
@keyframes left{to{transform:translateX(-384px)}}
.right{animation:right 420s steps(384) infinite}
@keyframes right{from{transform:translateX(-384px)}to{transform:translateX(0)}}
.fa{animation:fa 1.2s steps(1,end) infinite}
.fb{animation:fa 1.2s steps(1,end) infinite;animation-delay:-.6s}
@keyframes fa{0%,49.9%{opacity:1}50%,100%{opacity:0}}
.flow{animation:flow .6s steps(6) infinite}
@keyframes flow{to{transform:translateY(6px)}}
.smoke{animation:smoke 5.4s steps(13) infinite;opacity:0}
@keyframes smoke{0%{transform:translate(0,0);opacity:0}12%{opacity:.75}100%{transform:translate(5px,-13px);opacity:0}}
.flicker{animation:flicker 2.6s steps(1,end) infinite}
@keyframes flicker{0%,100%{opacity:1}30%{opacity:.78}55%{opacity:.95}80%{opacity:.7}}
.shoot{animation:shoot 14s linear infinite;opacity:0}
@keyframes shoot{0%{transform:translate(0,0);opacity:0}1%{opacity:1}6%{transform:translate(-64px,32px);opacity:0}100%{opacity:0}}
.fly{animation:fly 72s steps(444) infinite}
@keyframes fly{from{transform:translateX(-30px)}to{transform:translateX(414px)}}
.sheen{animation:sheen 9s steps(66) infinite}
@keyframes sheen{0%{transform:translateX(0)}45%,100%{transform:translateX(264px)}}
"""


# ---------------------------------------------------------------- sky

def sky(p):
    colors = p["sky"]
    n = len(colors)
    band = H / n
    pats, rows = [], []
    for i in range(n - 1):
        a, b = colors[i], colors[i + 1]
        for k, pts in ((1, [(0, 0)]), (2, [(0, 0), (1, 1)]), (3, [(0, 0), (1, 1), (1, 0)])):
            dots = "".join(f'<rect x="{x}" y="{y}" width="1" height="1" fill="{b}"/>' for x, y in pts)
            pats.append(f'<pattern id="sk{i}_{k}" width="2" height="2" patternUnits="userSpaceOnUse">'
                        f'<rect width="2" height="2" fill="{a}"/>{dots}</pattern>')
    for i, c in enumerate(colors):
        top, bot = round(i * band), round((i + 1) * band)
        rows.append(f'<rect x="0" y="{top}" width="{W}" height="{bot - top}" fill="{c}"/>')
        if i < n - 1:
            for k in (1, 2, 3):
                rows.append(f'<rect x="0" y="{bot - 4 + k}" width="{W}" height="1" fill="url(#sk{i}_{k})"/>')
    return "".join(pats), "".join(rows)


def stars(p):
    if not p["stars"]:
        return ""
    count, ymax = p["stars"]
    r = rng("stars", ymax)
    dim, out = Px(), []
    for _ in range(count):
        x, y = r.randrange(2, W - 2), r.randrange(2, ymax)
        c = r.choice(p["star_colors"])
        k = r.random()
        if k < .5:
            dim.set(x, y, p["star_dim"])
        elif k < .9:
            out.append(g(f'<rect x="{x}" y="{y}" width="1" height="1" fill="{c}"/>', cls="tw",
                         style=f"animation-duration:{r.uniform(2, 5):.1f}s;animation-delay:-{r.uniform(0, 5):.1f}s"))
        else:
            s = Px()
            s.set(x, y, "#ffffff")
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                s.set(x + dx, y + dy, c)
            out.append(g(s.svg(), cls="tw", style=f"animation-duration:{r.uniform(3, 6):.1f}s;animation-delay:-{r.uniform(0, 6):.1f}s"))
    if p["shooting"]:
        for x, y, delay in ((250, 10, 2), (170, 6, 9)):
            s = Px()
            for k in range(7):
                s.set(x + k * 2, y - k, "#ffffff" if k == 0 else "#c9d1ff" if k < 3 else "#6a70b0")
                s.set(x + k * 2 + 1, y - k, "#c9d1ff" if k < 3 else "#6a70b0")
            out.append(g(s.svg(), cls="shoot", style=f"animation-delay:{delay}s"))
    return dim.svg() + "".join(out)


def orb(p):
    kind, cx, cy, r = p["orb"]
    halo = "".join(f'<g opacity="{op}">{fill(disc(cx, cy, r + e), p["halo"])}</g>'
                   for e, op in ((2, .3), (4, .17), (7, .09), (11, .05), (16, .03)))
    body = Px()
    if kind == "moon":
        cut = disc(cx + 3, cy - 2, r - .5)
        for x, y in disc(cx, cy, r) - cut:
            body.set(x, y, p["orb_core"])
        for x, y in ((cx - 5, cy + 1), (cx - 3, cy + 4), (cx - 4, cy - 2)):
            if (int(x), int(y)) in body:
                body.set(x, y, p["orb_mid"])
    elif kind == "bigsun":
        for x, y in disc(cx, cy, r):
            body.set(x, y, p["orb_core"] if y < cy - 4 else p["orb_mid"] if y < cy + 2 else p["halo"])
    else:
        for x, y in disc(cx, cy, r):
            d = math.hypot(x + .5 - cx, y + .5 - cy)
            body.set(x, y, p["orb_core"] if d < r - 2 else p["orb_mid"])
    return g(halo, cls="pulse") + body.svg()


# ---------------------------------------------------------------- clouds

def cloud_cells(w, h, seed):
    r = rng("cloud", seed)
    n = max(3, w // 7)
    blobs = []
    for i in range(n):
        t = (i + .5) / n
        rad = h * .5 * (.55 + .6 * math.sin(math.pi * t)) * r.uniform(.85, 1.15)
        blobs.append((2 + t * (w - 4), h - rad * .8, rad))
    return {(x, y) for y in range(h) for x in range(w)
            if any((x + .5 - cx) ** 2 + (y + .5 - cy) ** 2 <= rad * rad for cx, cy, rad in blobs)}


def shade_cloud(cells, hi, mid, lo, ox=0, oy=0, light_x=-1, into=None):
    p = into or Px()
    for x, y in cells:
        c = mid
        if (x, y + 1) not in cells or (x, y + 2) not in cells:
            c = lo
        if (x, y - 1) not in cells or ((x, y - 2) not in cells and (x + y) % 2 == 0):
            c = hi
        elif (x + light_x, y) not in cells:
            c = hi
        p.set(x + ox, y + oy, c)
    return p


SKY_CLOUDS = [(18, 24, 38, 10, "a"), (176, 12, 28, 7, "b"), (292, 54, 44, 10, "c"), (40, 70, 24, 6, "d"), (356, 34, 22, 6, "e")]


def sky_clouds(p):
    hi, mid, lo = p["cloud"]
    layers = []
    for speed, picks in (("left", SKY_CLOUDS[:3]), ("right", SKY_CLOUDS[3:])):
        buf = Px()
        for x, y, w, h, seed in picks:
            cells = cloud_cells(w, h, seed)
            for ox in (x, x + W):
                shade_cloud(cells, hi, mid, lo, ox, y, p["light"], buf)
        layers.append(g(buf.svg(), cls=speed))
    return "".join(layers)


def puff_row(y0, rad_range, seed):
    """Top edge of one row of round puffs (periodic over W) and which puff owns each column."""
    r = rng("puffs", seed)
    n = round(W / (sum(rad_range) / 2 * 1.5))
    centers = [((i + r.uniform(-.25, .25)) * W / n, r.uniform(*rad_range)) for i in range(n)]
    tops, owners = [], []
    for x in range(W):
        best, owner = y0 + rad_range[0] * .5, -1
        for i, (cx, rad) in enumerate(centers):
            dx = ((x + .5 - cx + W / 2) % W) - W / 2
            if abs(dx) < rad:
                y = y0 + rad * .5 - math.sqrt(rad * rad - dx * dx)
                if y < best:
                    best, owner = y, i
        tops.append(math.ceil(best))
        owners.append((owner, ((x + .5 - centers[owner][0] + W / 2) % W) - W / 2 if owner >= 0 else 0,
                       centers[owner][1] if owner >= 0 else 1))
    return tops, owners


def cloud_sea(y0, seed, colors, rows=2):
    """Rows of big round puffs, nearer rows lower; spans 2W so it can scroll seamlessly."""
    hi, mid, lo = colors
    shapes = [((9, 19), 0), ((8, 16), 10)]
    rowdata = [puff_row(y0 + dy, rad, f"{seed}{k}") for k, (rad, dy) in enumerate(shapes[:rows])]
    p = Px()
    for x in range(W * 2):
        xm = x % W
        cols = [t[xm] for t, _ in rowdata]
        for y in range(min(cols), H):
            k = max(i for i, t in enumerate(cols) if y >= t)
            tops, owners = rowdata[k]
            owner, dx, rad = owners[xm]
            d = y - cols[k]
            crease = owners[(xm + 1) % W][0] != owner or owners[xm - 1][0] != owner
            c = mid
            if d == 0 or (d == 1 and abs(dx) < rad * .45):
                c = hi                      # lit cap of the puff
            elif crease and d < 5:
                c = lo                      # fold between two puffs
            elif k + 1 < rows and y == cols[k + 1] - 1:
                c = lo                      # shadow where a nearer puff overlaps
            elif d > rad * .9 and (x + y) % 2 == 0:
                c = lo                      # underside of the puff
            p.set(x, y, c)
    return p.svg()


# ---------------------------------------------------------------- floating things

def small_rock(cx, top, w, p):
    hi, lit, mid, dark, deep = p["rock"]
    px = Px()
    hw = w / 2
    for x in range(int(cx - hw), int(cx + hw)):
        u = (x + .5 - cx) / hw
        depth = 2 + w * .45 * (1 - abs(u) ** 1.3)
        side = u * -p["light"]  # >0 on the lit side
        for y in range(top + 1, int(top + depth) + 1):
            c = lit if side > .45 else dark if side < -.45 else mid
            if y >= int(top + depth) - (0 if abs(u) > .5 else 1):
                c = deep
            px.set(x, y, c)
        px.set(x, top, p["grass"][0] if side > 0 else p["grass"][1])
        if (x * 7) % 5 == 0:
            px.set(x, top - 1, p["grass"][1])
    return px.svg()


# ---------------------------------------------------------------- island

def island_bottom(x, spikes):
    cx, hw = (IL + IR) / 2, (IR - IL) / 2
    u = min(1.0, abs(x + .5 - cx) / hw)
    y = TOP + 35 + 22 * (1 - u ** 1.7) ** .85
    edge = min(x - IL, IR - x)
    if edge < 4:
        y -= 4 - edge
    for sx, h, hw_ in spikes:
        dx = abs(x - sx)
        if dx < hw_:
            y += h * (1 - dx / hw_)
    return int(y)


def island_spikes():
    r = rng("spikes")
    out, x = [], IL + 18
    while x < IR - 18:
        center = 1 - abs(x - (IL + IR) / 2) / ((IR - IL) / 2)
        out.append((x, r.uniform(2, 3 + 5 * center), r.uniform(2, 3.5)))
        x += r.randint(9, 16)
    return out


def island(p, levels):
    hi, lit, mid, dark, deep = p["rock"]
    lx = p["light"]
    spikes = island_spikes()
    bottoms = {x: island_bottom(x, spikes) for x in range(IL, IR + 1)}
    shape = {(x, y) for x, b in bottoms.items() for y in range(TOP, b + 1)}
    shape -= {(IL, TOP), (IL + 1, TOP), (IL, TOP + 1), (IR, TOP), (IR - 1, TOP), (IR, TOP + 1)}
    r = rng("rock")
    body = Px()
    for x, y in shape:
        wob = round(1.2 * math.sin(x / 9.0) + .8 * math.sin(x / 4.3 + 1))
        strata = (y + wob - TOP) % 6 == 0
        c = dark if y > TOP + 44 else mid
        if strata:
            c = deep if c == dark else dark
        lit_d = (x - IL) if lx < 0 else (IR - x)
        shade_d = (IR - x) if lx < 0 else (x - IL)
        if lit_d < 1:
            c = hi
        elif lit_d < 4 and y < TOP + 44:
            c = mid if strata else lit
        if shade_d < 3:
            c = deep if shade_d < 1 else dark
        if (x, y + 1) not in shape:
            c = deep
        elif (x, y + 2) not in shape:
            c = dark
        elif r.random() < .015 and c in (mid, dark):
            c = lit
        body.set(x, y, c)

    # The contribution graph as stone blocks set into the island's face; green = grass.
    panel = Px()
    panel.rect(GX - 1, GY - 1, GRID_W + 2, GRID_H + 2, p["mortar"])
    cells = []
    for wi, week in enumerate(levels):
        for di, level in enumerate(week):
            if level is None:
                continue
            x, y = GX + wi * PITCH, GY + di * PITCH
            panel.rect(x, y, CELL, CELL, p["soil"] if level == 0 else p["levels"][level - 1])
            cells.append((x, y, level))

    vines_a, vines_b = Px(), Px()
    vr = rng("vines")
    for x in sorted(vr.sample(range(IL + 12, IR - 12), 10)):
        y0 = bottoms[x] + 1
        length = vr.randint(3, 9)
        for k in range(length):
            vines_a.set(x, y0 + k, p["vine"][0])
            vines_b.set(x + (1 if k >= length // 2 else 0), y0 + k, p["vine"][0])
        vines_a.set(x - 1, y0 + length - 1, p["vine"][1])
        vines_b.set(x, y0 + length, p["vine"][1])

    return (body.svg() + panel.svg() + grid_fx(p, cells)
            + g(vines_a.svg(), cls="fa", style="animation-duration:3s")
            + g(vines_b.svg(), cls="fb", style="animation-duration:3s;animation-delay:-1.5s"))


def grid_fx(p, cells):
    r = rng("gridfx")
    fx = p["grid_fx"]
    if fx == "glow":
        out = []
        for x, y, level in cells:
            if level >= 2:
                out.append(g(f'<rect x="{x - 1}" y="{y - 1}" width="{CELL + 2}" height="{CELL + 2}" fill="#7ee787"/>',
                             cls="pulse", opacity=.16 + .08 * level,
                             style=f"animation-duration:{r.uniform(3, 6):.1f}s;animation-delay:-{r.uniform(0, 6):.1f}s"))
        return "".join(out)
    if fx == "dew":
        out = []
        for x, y, level in r.sample(cells, min(16, len(cells))):
            out.append(g(f'<rect x="{x}" y="{y}" width="1" height="1" fill="#ffffff"/>', cls="tw",
                         style=f"animation-duration:{r.uniform(2, 4.5):.1f}s;animation-delay:-{r.uniform(0, 4):.1f}s"))
        return "".join(out)
    if fx == "sheen":
        clip = "".join(f'<rect x="{x}" y="{y}" width="{CELL}" height="{CELL}"/>' for x, y, _ in cells)
        band = (f'<polygon class="sheen" points="{GX - 30},{GY - 2} {GX - 22},{GY - 2} {GX - 34},{GY + GRID_H + 2} '
                f'{GX - 42},{GY + GRID_H + 2}" fill="{p["sheen"]}" opacity=".55"/>')
        return f'<clipPath id="cells">{clip}</clipPath><g clip-path="url(#cells)">{band}</g>'
    return ""


def grass(p):
    hi, mid, dark = p["grass"]
    px = Px()
    r = rng("grass")
    for x in range(IL, IR + 1):
        corner = x in (IL, IR)
        y0 = TOP + (1 if corner else 0)
        px.set(x, y0, hi)
        px.set(x, y0 + 1, mid)
        px.set(x, y0 + 2, dark)
        if corner:
            for k in range(3, r.randint(4, 7)):
                px.set(x, TOP + k, dark)
            continue
        k = r.random()
        if k < .3:
            px.set(x, TOP - 1, mid)
        if k < .07:
            px.set(x, TOP - 2, hi)
        if GX - 1 <= x <= GX + GRID_W:
            if r.random() < .22:
                px.set(x, TOP + 3, dark)
            if r.random() < .05:
                px.set(x, TOP + 4, dark)
    for x in range(HOUSE_X + 15, TREE_X + 22, -7):  # stepping stones from the door
        px.set(x, TOP, p["house"]["s"])
        px.set(x - 1, TOP, p["house"]["s"])
        px.set(x, TOP + 1, p["house"]["S"])
    for i, dx in enumerate((14, 21, 66, 75, 90, 103, 117, 128, 178, 196, 205)):
        px.set(IL + dx, TOP - 1, p["flowers"][i % len(p["flowers"])])
        px.set(IL + dx, TOP, mid)
    return px.svg()


TREE_BLOBS = [(0, -25, 8.5), (-9, -20, 7.5), (9, -20, 7.5), (-14, -11, 8), (14, -11, 8),
              (0, -14, 11), (-7, -4, 8), (7, -4, 8), (-19, -3, 5.5), (19, -2, 5.5)]


def tree(p):
    tx, ty = TREE_X, TOP - 13
    trunk = Px()
    lit, dark = p["trunk"]
    for y in range(ty - 2, TOP):
        trunk.set(tx - 1, y, lit if p["light"] < 0 else dark)
        trunk.set(tx, y, lit)
        trunk.set(tx + 1, y, dark if p["light"] < 0 else lit)
        trunk.set(tx + 2 * (1 if p["light"] < 0 else -1), y, dark) if y > TOP - 6 else None
    for x in range(tx - 4, tx + 5):
        trunk.set(x, TOP - 1, dark if abs(x - tx) > 1 else lit)
    for x in range(tx - 2, tx + 3):
        trunk.set(x, TOP - 2, dark if abs(x - tx) > 1 else lit)

    blobs = [(tx + .5 + dx, ty + dy, r) for dx, dy, r in TREE_BLOBS]
    leaves, owner = foliage(blobs, p["leaves"], p["light"])
    r = rng("tree")
    inner = sorted(xy for xy, c in leaves.p.items() if c in p["leaves"][2:])
    for x, y in r.sample(inner, 18):
        leaves.set(x, y, p["blossom"][0])
        if (x, y - 1) in owner:
            leaves.set(x, y - 1, p["blossom"][1])

    # Wind: a few top-edge leaves flick sideways and back.
    edge = sorted(xy for xy in owner if (xy[0], xy[1] - 1) not in owner)
    a, b = Px(), Px()
    for x, y in r.sample(edge, 18):
        c = leaves.p.pop((x, y))
        a.set(x, y, c)
        b.set(x + 1, y, c)
    wind = g(a.svg(), cls="fa", style="animation-duration:2.4s") + g(b.svg(), cls="fb", style="animation-duration:2.4s;animation-delay:-1.2s")

    # A swing hanging from the right-hand bough, rocking gently.
    swing_a, swing_b = Px(), Px()
    for frame, shift in ((swing_a, 0), (swing_b, 1)):
        for y in range(TOP - 12, TOP - 4):
            off = shift if y > TOP - 9 else 0
            frame.set(tx + 10 + off, y, dark)
            frame.set(tx + 15 + off, y, dark)
        frame.rect(tx + 9 + shift, TOP - 4, 8, 1, lit)
        frame.rect(tx + 9 + shift, TOP - 3, 8, 1, dark)
    swing = g(swing_a.svg(), cls="fa", style="animation-duration:2.8s") + g(swing_b.svg(), cls="fb", style="animation-duration:2.8s;animation-delay:-1.4s")

    bush, _ = foliage([(IL + 8, TOP - 2, 3.5), (IL + 13, TOP - 3, 4.5), (IL + 19, TOP - 2, 3.5)], p["leaves"], p["light"])
    bush2, _ = foliage([(IR - 20, TOP - 2, 3.5), (IR - 15, TOP - 3, 4)], p["leaves"], p["light"])
    return swing + trunk.svg() + leaves.svg() + wind + bush.svg() + bush2.svg()


HOUSE = [
    "........RRRR........",
    ".......RrrrrR...CC..",
    "......RqqqqqqR..Cc..",
    ".....RrrrrrrrrR.Cc..",
    "....RqqqqqqqqqqRCc..",
    "...RrrrrrrrrrrrrRc..",
    "..RqqqqqqqqqqqqqqR..",
    ".RrrrrrrrrrrrrrrrrR.",
    "RRRRRRRRRRRRRRRRRRRR",
    ".TwwwwwwwwwwwwwwwWT.",
    ".TwNNNNwwwwwwDDDDWT.",
    ".TwNnnNwwwwwwDddDWT.",
    ".TwNnnNwwwwwwDddDWT.",
    ".TwNNNNwwwwwwDdkDWT.",
    ".TwwwwwwwwwwwDddDWT.",
    ".SsSsSsSsSsSsDddDsS.",
]
LAMP = [".T.", "TlT", "TlT", ".T.", ".P.", ".P.", ".P.", ".P.", ".P.", ".P.", ".P.", "PPP"]
assert all(len(row) == len(HOUSE[0]) for row in HOUSE)


def house(p):
    hx, hy = HOUSE_X, TOP - len(HOUSE)
    px = Px()
    rows = [list(row) for row in HOUSE]
    for row in rows:  # roof highlight along the lit slope
        idx = [i for i, ch in enumerate(row) if ch in "rq"]
        if idx:
            row[idx[0] if p["light"] < 0 else idx[-1]] = "h"
    px.sprite(hx, hy, ["".join(r_) for r_ in rows], p["house"])
    out = px.svg()
    if p["window_glow"]:
        out += g("".join(f'<g opacity="{op}">{fill(disc(hx + 5, hy + 12, rad), p["window_glow"])}</g>'
                         for rad, op in ((3, .3), (5, .14), (8, .06))), cls="flicker")
    if p["smoke"]:
        for i in range(3):
            s = Px()
            s.rect(hx + 16, hy, 2, 2, p["smoke"])
            out += g(s.svg(), cls="smoke", style=f"animation-delay:-{i * 1.8:.1f}s")

    lx, ly = LAMP_X, TOP - len(LAMP)
    lamp = Px()
    light, glow, pole = p["lamp"]
    lamp.sprite(lx, ly, LAMP, {"T": pole, "P": pole, "l": light if p["lamp_on"] else "#c8c2b4"})
    out += lamp.svg()
    if p["lamp_on"]:
        halo = "".join(f'<g opacity="{op}">{fill(disc(lx + 1.5, ly + 2, rad), glow)}</g>'
                       for rad, op in ((3, .35), (5, .18), (8, .09), (12, .04)))
        spill = Px()
        for x in range(lx - 5, lx + 8):
            spill.set(x, TOP, light)
        out += g(halo, cls="flicker") + g(spill.svg(), opacity=.35, cls="flicker")
    return out


def waterfall(p):
    hi, mid, dark = p["water"]
    x0 = IR + 1
    base = Px()
    for y in range(TOP + 1, SEA_Y + 6):
        base.set(x0, y, dark)
        base.set(x0 + 1, y, mid)
        base.set(x0 + 2, y, mid if y % 5 else dark)
    for x in range(IR - 8, IR + 1):  # the stream that feeds it
        base.set(x, TOP, mid)
    base.set(IR - 4, TOP, hi)
    base.set(IR + 1, TOP, hi)
    streaks = Px()
    for y in range(TOP - 8, SEA_Y + 8):
        for col in range(3):
            if (y + col * 2) % 6 == 0:
                streaks.set(x0 + col, y, hi)
    clip = f'<clipPath id="fall"><rect x="{x0}" y="{TOP + 1}" width="3" height="{SEA_Y + 5 - TOP}"/></clipPath>'
    return base.svg() + clip + g(g(streaks.svg(), cls="flow"), clip_path="url(#fall)")


def splash(p):
    hi = p["water"][0]
    a, b = Px(), Px()
    x0 = IR + 1
    for x, y in ((x0 - 2, SEA_Y), (x0 + 4, SEA_Y - 1), (x0 + 1, SEA_Y - 2), (x0 + 6, SEA_Y + 1)):
        a.set(x, y, hi)
    for x, y in ((x0 - 1, SEA_Y - 1), (x0 + 3, SEA_Y - 2), (x0 + 5, SEA_Y), (x0 - 3, SEA_Y + 1)):
        b.set(x, y, hi)
    return g(a.svg(), cls="fa", style="animation-duration:.8s") + g(b.svg(), cls="fb", style="animation-duration:.8s;animation-delay:-.4s")


# ---------------------------------------------------------------- drifting life

def petals(p):
    if not p["petals"]:
        return ""
    r = rng("petals")
    out, css = [], []
    for i in range(7):
        x, y = TREE_X + r.randint(-18, 18), r.randint(36, 60)
        dur = r.uniform(9, 15)
        drift = r.uniform(18, 40)
        fall_ = r.uniform(40, 70)
        name = f"pt{i}"
        css.append(f"@keyframes {name}{{0%{{transform:translate(0,0);opacity:0}}8%{{opacity:1}}"
                   f"30%{{transform:translate({drift * .2:.0f}px,{fall_ * .3:.0f}px)}}"
                   f"55%{{transform:translate({drift * .55:.0f}px,{fall_ * .55:.0f}px)}}"
                   f"80%{{transform:translate({drift * .75:.0f}px,{fall_ * .8:.0f}px);opacity:1}}"
                   f"100%{{transform:translate({drift:.0f}px,{fall_:.0f}px);opacity:0}}}}")
        a, b = Px(), Px()
        a.set(x, y, p["petals"][0])
        a.set(x + 1, y, p["petals"][1])
        b.set(x, y, p["petals"][1])
        b.set(x, y + 1, p["petals"][0])
        flutter = g(a.svg(), cls="fa", style="animation-duration:.9s") + g(b.svg(), cls="fb", style="animation-duration:.9s;animation-delay:-.45s")
        out.append(g(flutter, style=f"animation:{name} {dur:.1f}s steps(40) infinite;animation-delay:-{r.uniform(0, dur):.1f}s;opacity:0"))
    return f"<style>{''.join(css)}</style>" + "".join(out)


def birds(p):
    if not p["birds"]:
        return ""
    up, down = Px(), Px()
    for bx, by in ((0, 0), (9, 4), (17, 1)):
        up.sprite(bx, by, ["#...#", ".#.#.", "..#.."], {"#": p["birds"]})
        down.sprite(bx, by + 1, ["##.##", "..#.."], {"#": p["birds"]})
    flap = g(up.svg(), cls="fa", style="animation-duration:.7s") + g(down.svg(), cls="fb", style="animation-duration:.7s;animation-delay:-.35s")
    return g(g(flap, transform="translate(0,34)"), cls="fly")


def fireflies(p):
    if not p["fireflies"]:
        return ""
    r = rng("fireflies")
    out, css = [], []
    for i in range(10):
        x = r.choice((r.randint(TREE_X - 26, TREE_X + 26), r.randint(TREE_X + 30, HOUSE_X)))
        y = r.randint(TOP - 26, TOP - 2)
        pts = [(0, 0)] + [(r.randint(-7, 7), r.randint(-5, 5)) for _ in range(3)] + [(0, 0)]
        frames = "".join(f"{k * 25}%{{transform:translate({dx}px,{dy}px)}}" for k, (dx, dy) in enumerate(pts))
        css.append(f"@keyframes ff{i}{{{frames}}}")
        body = (f'<g opacity=".35"><rect x="{x - 1}" y="{y}" width="3" height="1" fill="#e9ff9c"/>'
                f'<rect x="{x}" y="{y - 1}" width="1" height="3" fill="#e9ff9c"/></g>'
                f'<rect x="{x}" y="{y}" width="1" height="1" fill="#f6ffd0"/>')
        dur = r.uniform(9, 16)
        blink = g(body, cls="tw", style=f"animation-duration:{r.uniform(1.5, 3):.1f}s;animation-delay:-{r.uniform(0, 3):.1f}s")
        out.append(g(blink, style=f"animation:ff{i} {dur:.1f}s steps(30) infinite;animation-delay:-{r.uniform(0, dur):.1f}s"))
    return f"<style>{''.join(css)}</style>" + "".join(out)


# ---------------------------------------------------------------- compose

def frame_clip():
    pts = [(0, 3), (1, 3), (1, 1), (3, 1), (3, 0)]
    path = []
    for corner in range(4):
        for x, y in pts:
            path.append([(x, y), (W - y, x), (W - x, H - y), (y, H - x)][corner])
    return '<clipPath id="frame"><polygon points="' + " ".join(f"{x},{y}" for x, y in path) + '"/></clipPath>'


def scene(name, levels):
    p = PAL[name]
    sky_defs, sky_rows = sky(p)
    sea_back = cloud_sea(SEA_Y - 11, "back", (p["sea_back"], p["sea_back"], p["sea_back"]), rows=1)
    sea_front = cloud_sea(SEA_Y, "front", p["sea"])
    rocks = (g(small_rock(20, 104, 10, p), cls="bob", style="animation-duration:2.6s;animation-delay:-1s")
             + g(small_rock(348, 62, 9, p), cls="bob", style="animation-duration:3.6s")
             + g(small_rock(52, 80, 6, p), cls="bob", style="animation-duration:3s;animation-delay:-2s"))
    floating = island(p, levels) + grass(p) + tree(p) + house(p) + waterfall(p)
    body = (
        sky_rows + stars(p) + orb(p) + sky_clouds(p)
        + g(sea_back, cls="right") + birds(p)
        + g(floating, cls="bob") + rocks
        + g(sea_front, cls="left") + splash(p)
        + petals(p) + fireflies(p)
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W * SCALE}" height="{H * SCALE}" '
        f'shape-rendering="crispEdges"><style>{CSS}</style>'
        f'<defs>{sky_defs}{frame_clip()}</defs><g clip-path="url(#frame)">{body}</g></svg>\n'
    )


def current_scene(now=None):
    h = (now or datetime.now(timezone.utc) + timedelta(hours=9)).hour
    return "dawn" if h < 6 else "morning" if h < 12 else "noon" if h < 18 else "evening"


def main():
    mode, target = sys.argv[1], Path(sys.argv[2])
    levels = load_levels()
    if mode == "now":
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(scene(current_scene(), levels), encoding="utf-8")
    else:
        target.mkdir(parents=True, exist_ok=True)
        for name in PAL:
            (target / f"{name}.svg").write_text(scene(name, levels), encoding="utf-8")


if __name__ == "__main__":
    main()
