"""Render the floating-island scene for each time of day.

The island's cliff face is the real contribution graph (53 weeks x 7 days, in GitHub's
own greens) laid as bevelled blocks; the sky, clouds, tree, cottage and waterfall are
relit for dawn, morning, noon and evening.

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

W, H, SCALE = 420, 200, 3
TOP = 100                                 # front lip of the island's grass plateau
DEPTH = 13                                # how far back the plateau reaches
CELL, PITCH = 4, 5                        # contribution block size / spacing
GRID_W, GRID_H = 53 * PITCH - 1, 7 * PITCH - 1
GX, GY = (W - GRID_W) // 2, TOP + 6
FL, FR = GX - 9, GX + GRID_W + 8          # island face left/right
LEDGE = GY + GRID_H + 1
SEA_Y = 178
TREE_X, HOUSE_X, LAMP_X = FL + 52, FL + 176, FL + 160
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


# ---------------------------------------------------------------- colour + pixels

def rgb(c):
    return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))


def mix(a, b, t):
    pa, pb = rgb(a), rgb(b)
    return "#" + "".join(f"{max(0, min(255, round(x + (y - x) * t))):02x}" for x, y in zip(pa, pb))


class Px:
    """Sparse pixel buffer; emits one <path> per colour with runs merged into rectangles."""

    def __init__(self):
        self.p = {}

    def set(self, x, y, c):
        if c:
            self.p[(int(x), int(y))] = c

    def get(self, x, y):
        return self.p.get((int(x), int(y)))

    def rect(self, x, y, w, h, c):
        for yy in range(int(y), int(y + h)):
            for xx in range(int(x), int(x + w)):
                self.set(xx, yy, c)

    def sprite(self, x, y, rows, colors):
        for dy, row in enumerate(rows):
            for dx, ch in enumerate(row):
                if ch in colors:
                    self.set(x + dx, y + dy, colors[ch])

    def merge(self, other):
        self.p.update(other.p)
        return self

    def svg(self):
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
                if prev and prev[0] + prev[1] == y:
                    nxt[run] = [prev[0], prev[1] + 1]
                else:
                    if prev:
                        done.append((run, prev))
                    nxt[run] = [y, 1]
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


def ellipse(cx, cy, rx, ry):
    for y in range(math.floor(cy - ry) - 1, math.ceil(cy + ry) + 1):
        for x in range(math.floor(cx - rx) - 1, math.ceil(cx + rx) + 1):
            if ((x + .5 - cx) / rx) ** 2 + ((y + .5 - cy) / ry) ** 2 <= 1:
                yield x, y


def fill(cells, color):
    p = Px()
    for x, y in cells:
        p.set(x, y, color)
    return p.svg()


def glow(cx, cy, color, rings=((3, .32), (5, .18), (8, .09), (12, .045))):
    return "".join(f'<g opacity="{op}">{fill(ellipse(cx, cy, r, r), color)}</g>' for r, op in rings)


BAYER = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]


def shade_blobs(blobs, ramp, light, bias=0.0, rim=None, bounce=None, dither=.1, crease=True, into=None):
    """Volumetric clusters: ellipses (cx, cy, rx, ry) back to front, lit by `light`, ramp dark -> light."""
    owner = {}
    for i, b in enumerate(blobs):
        for xy in ellipse(*b):
            owner[xy] = i
    lx, ly, lz = light
    n = math.sqrt(lx * lx + ly * ly + lz * lz)
    lx, ly, lz = lx / n, ly / n, lz / n
    sx = 1 if lx > 0 else -1
    k = len(ramp)
    px = into or Px()
    for (x, y), i in owner.items():
        cx, cy, rx, ry = blobs[i]
        nx, ny = (x + .5 - cx) / rx, (y + .5 - cy) / ry
        nz = math.sqrt(max(0.0, 1 - nx * nx - ny * ny))
        v = nx * lx + ny * ly + nz * lz + bias + (BAYER[y % 4][x % 4] / 16 - .5) * dither
        t = max(0, min(k - 1, int((v + .35) / 1.3 * k)))
        if crease and any(owner.get(nb, -1) > i for nb in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1))):
            t = max(0, t - 1)                       # contact shadow under a nearer clump
        c = ramp[t]
        if (x, y + 1) not in owner and bounce and t < k - 2:
            c = bounce                              # light bounced up from the clouds
        elif rim and v > .1 and ((x + sx, y) not in owner or (x, y - 1) not in owner):
            c = rim                                 # rim light on the lit silhouette
        px.set(x, y, c)
    return px, owner


def chunk(cx, cy, rx, ry, r, spike=0.0):
    """A convex rock chunk; `spike` drags its bottom vertex down into a point."""
    n = r.randint(5, 7)
    pts = []
    for i in range(n):
        a = (i + r.uniform(-.25, .25)) * 2 * math.pi / n
        pts.append((cx + rx * r.uniform(.82, 1.05) * math.cos(a), cy + ry * r.uniform(.78, 1.05) * math.sin(a)))
    if spike:
        i = min(range(n), key=lambda j: abs(pts[j][0] - cx) - pts[j][1])
        pts[i] = (cx + r.uniform(-1.5, 1.5), cy + ry + spike)
    return pts


def shade_rocks(polys, ramp, light, bias=0.0, bevel=2.3, rim=None, bounce=None, into=None):
    """Faceted rock: each chunk gets a flat face plus bevelled edges lit by their own normals."""
    lx, ly, lz = light
    n = math.sqrt(lx * lx + ly * ly + lz * lz)
    lx, ly, lz = lx / n, ly / n, lz / n
    sx = 1 if lx > 0 else -1
    k = len(ramp)
    owner, edges_of = {}, []
    for i, pts in enumerate(polys):
        cx = sum(x for x, _ in pts) / len(pts)
        cy = sum(y for _, y in pts) / len(pts)
        edges = []
        for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
            ln = math.hypot(x1 - x0, y1 - y0) or 1
            nx, ny = (y1 - y0) / ln, -(x1 - x0) / ln
            if (x0 - cx) * nx + (y0 - cy) * ny < 0:
                nx, ny = -nx, -ny
            edges.append((x0, y0, nx, ny))
        edges_of.append(edges)
        xs, ys = [x for x, _ in pts], [y for _, y in pts]
        for y in range(math.floor(min(ys)), math.ceil(max(ys)) + 1):
            for x in range(math.floor(min(xs)), math.ceil(max(xs)) + 1):
                if all((x + .5 - ex) * nx + (y + .5 - ey) * ny <= 0 for ex, ey, nx, ny in edges):
                    owner[(x, y)] = i
    px = into or Px()
    for (x, y), i in owner.items():
        d, nx, ny = min((-((x + .5 - ex) * enx + (y + .5 - ey) * eny), enx, eny) for ex, ey, enx, eny in edges_of[i])
        n3 = (nx * .78, ny * .78, .62) if d < bevel else (0, -.3, .95)
        v = n3[0] * lx + n3[1] * ly + n3[2] * lz + bias
        t = max(0, min(k - 1, int((v + .35) / 1.3 * k)))
        if any(owner.get(nb, -1) > i for nb in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1))):
            t = max(0, t - 1)
        c = ramp[t]
        if (x, y + 1) not in owner and bounce:
            c = bounce
        elif rim and v > .15 and ((x + sx, y) not in owner or (x, y - 1) not in owner):
            c = rim
        px.set(x, y, c)
    return px, owner


# ---------------------------------------------------------------- palettes

PAL = {
    "dawn": dict(
        sky=["#070818", "#0a0c22", "#0e112c", "#131737", "#191d43", "#20244f", "#272a5b", "#302f66", "#3a3570", "#463c79"],
        light=(.5, -.6, .6), orb=("moon", 366, 36, 9), orb_ramp=["#cfc6a4", "#e9e1c4", "#fbf6e4"], halo="#8c95ff",
        stars=(150, 160), milky=True, shooting=True,
        cloud=["#1c1f4a", "#272b5e", "#353a74", "#474e8e", "#6870b0"],
        sea=["#1b1e4a", "#262a60", "#363c7c", "#4c549a", "#7078bc"], bank=["#20244f", "#2a2e60"],
        rock=["#100e22", "#1a1733", "#262246", "#342e5a", "#463e70", "#5a548c"], rim="#8f9ae0", bounce="#363c7c",
        grass=["#0f2a2e", "#173a3a", "#1f4d47", "#2a6457", "#3d7f68", "#6aa894"],
        leaves=["#0a1c26", "#0f2a32", "#163a40", "#1f4d50", "#2e6566", "#5a8fa0"],
        blossom=["#8a72b0", "#c0a8e0"], trunk=["#151226", "#221c36", "#302848", "#4a4068"],
        house=dict(wall=["#24203e", "#2e2a4c", "#3a3458"], side=["#3a3a66", "#4a4c80"],
                   roof=["#120f24", "#211b3a", "#2e264e", "#6a6aa8"], trim="#120f22", glass=["#ffb347", "#ffe08a"],
                   door=["#1e1a34", "#2a2444"], stone=["#262238", "#363250"], chimney=["#24203e", "#3a3a66"], flower="#a890d0"),
        windows_lit=True, lamp_on=True, glow="#ffb347",
        block=["#15122a", "#1e1a36", "#2a2548"], mortar="#0e0c1e", levels=GH_DARK,
        water=["#2a3170", "#4a54a0", "#7a86d0", "#c9d0ff"], smoke=None,
        flowers=["#c9b8ff", "#8fd0ff"], petals=None, birds=None, butterflies=False, fireflies=True,
        rays=False, streaks=False, grid_fx="glow", sheen=None,
    ),
    "morning": dict(
        sky=["#6f8fda", "#7c99de", "#8ba3e2", "#9cade5", "#aeb6e7", "#c1bee7", "#d3c5e5", "#e3cbe1", "#f0d0dc", "#f8d6d6", "#fde0d2"],
        light=(-.75, -.45, .5), orb=("sun", 44, 152, 9), orb_ramp=["#ffd9a8", "#ffefcc", "#fffaf0"], halo="#ffc9a8",
        stars=None, milky=False, shooting=False,
        cloud=["#b8a2cf", "#d4b9db", "#ebd0e4", "#f9e6ee", "#fff8f6"],
        sea=["#c4aad4", "#dcc2df", "#efd7e7", "#fbe9f0", "#fff8f8"], bank=["#dcc4e2", "#ecd2e4"],
        rock=["#3e2f4f", "#5a4064", "#7a5472", "#9c6a7e", "#c08a8e", "#e2b0a4"], rim="#ffd8c0", bounce="#d8bcd8",
        grass=["#3c7458", "#4f9160", "#6aae68", "#8fca76", "#b8e28c", "#e0f3ae"],
        leaves=["#2a4f4e", "#346a58", "#45875f", "#62a56a", "#8cc27c", "#c2e2a0"],
        blossom=["#ff9fbf", "#ffd6e3"], trunk=["#4f3446", "#704a52", "#946460", "#b8846e"],
        house=dict(wall=["#d9bfc8", "#efdade", "#fff2ee"], side=["#b49bb0", "#cbb3c4"],
                   roof=["#2e2a66", "#4f4b9c", "#6a66b8", "#a6a2e4"], trim="#6a4a62", glass=["#8fa8e0", "#d9e6ff"],
                   door=["#7a5068", "#9c6a80"], stone=["#a690a6", "#c4b0c0"], chimney=["#9a7488", "#c8a0ae"], flower="#ff7aa0"),
        windows_lit=False, lamp_on=False, glow="#ffcf70",
        block=["#5e4458", "#7e5e74", "#9c7a90"], mortar="#4a3650", levels=GH_LIGHT,
        water=["#8fa4e0", "#b0c6f2", "#d4e4fb", "#ffffff"], smoke="#fff4f4",
        flowers=["#ff9fbf", "#fff3a8", "#ffffff"], petals=["#ffb3cc", "#ffe3ec"], birds="#6b6b9e", butterflies=False,
        fireflies=False, rays=True, streaks=False, grid_fx="dew", sheen=None,
    ),
    "noon": dict(
        sky=["#2a5fd0", "#2f6ad8", "#3676df", "#3f83e6", "#4b92ec", "#5aa1f1", "#6cb0f5", "#82bff8", "#9bcdfa", "#b8dcfc", "#d6ebfd"],
        light=(.55, -.75, .45), orb=("sun", 360, 34, 10), orb_ramp=["#fff3c0", "#fffbe6", "#ffffff"], halo="#fff4c8",
        stars=None, milky=False, shooting=False,
        cloud=["#9fb4e4", "#bccdee", "#d8e5f7", "#edf3fc", "#ffffff"],
        sea=["#a6bde8", "#c2d4f1", "#dce8f9", "#eef5fd", "#ffffff"], bank=["#b4d2f8", "#c8e0fa"],
        rock=["#3a2c3e", "#5a3f45", "#7d5848", "#a0744f", "#c4955f", "#e2bc7e"], rim=None, bounce="#b8c8e6",
        grass=["#2e6b3c", "#3f8a42", "#58a845", "#7cc44e", "#a8dc63", "#d4f08a"],
        leaves=["#1f4a3a", "#2b6343", "#3b7f49", "#56a050", "#7fc05c", "#b5df7a"],
        blossom=["#f58fb0", "#ffd0e0"], trunk=["#4a2e2e", "#6e4636", "#946044", "#b98058"],
        house=dict(wall=["#cdb8a2", "#e8dac6", "#fff6e8"], side=["#c7b29e", "#e2d0bc"],
                   roof=["#22306e", "#3a4ea6", "#4e67c2", "#8aa2ec"], trim="#5a3f3a", glass=["#6fa6dc", "#c8e6ff"],
                   door=["#6e4636", "#946044"], stone=["#8f8a86", "#b5afa8"], chimney=["#8a6a5e", "#b8988a"], flower="#ff7aa0"),
        windows_lit=False, lamp_on=False, glow="#ffcf70",
        block=["#5e4234", "#7e5c44", "#9c7858"], mortar="#45302a", levels=GH_LIGHT,
        water=["#3f7fd6", "#5aa6ee", "#8fd0ff", "#e8f8ff"], smoke=None,
        flowers=["#ff8fb0", "#fff07a", "#ffffff", "#b8a6ff"], petals=["#ffc4d6", "#ffffff"], birds="#3d4f7c",
        butterflies=True, fireflies=False, rays=False, streaks=False, grid_fx="sheen", sheen="#ffffff",
    ),
    "evening": dict(
        sky=["#1e1b4f", "#28215c", "#352869", "#473077", "#5d3883", "#77418c", "#934a90", "#b25490", "#cd608d", "#e46f88", "#f48582", "#fca07c"],
        light=(.8, -.25, .5), orb=("bigsun", 366, 158, 16), orb_ramp=["#ff9a6a", "#ffc884", "#fff0c2"], halo="#ff9a72",
        stars=(30, 50), milky=False, shooting=False,
        cloud=["#5a3e7e", "#8a4f8c", "#c06890", "#ea9a98", "#ffd0a8"],
        sea=["#6a4583", "#9a5690", "#cc7193", "#f0a39a", "#ffd5ad"], bank=["#b5598f", "#d06a8e"],
        rock=["#24183a", "#3a2550", "#553463", "#744571", "#965676", "#c07080"], rim="#ffa47e", bounce="#a85a8a",
        grass=["#2e3f44", "#3e5548", "#556e4e", "#7c8a56", "#b5a060", "#f0c674"],
        leaves=["#231f3f", "#302c4c", "#423f58", "#5f5960", "#937a66", "#f2a872"],
        blossom=["#ff9ab4", "#ffc8b4"], trunk=["#2a1d38", "#43294a", "#64395a", "#a85a66"],
        house=dict(wall=["#5e4470", "#76548a", "#8e6a9a"], side=["#c48a8e", "#f2b89a"],
                   roof=["#24183a", "#45305e", "#5e3f74", "#e08a74"], trim="#2a1d38", glass=["#ffb347", "#ffe08a"],
                   door=["#3e2a50", "#56386a"], stone=["#4e3e60", "#6a5478"], chimney=["#5e4470", "#d89a8e"], flower="#ffb0c0"),
        windows_lit=True, lamp_on=True, glow="#ffa860",
        block=["#2e2140", "#3e2c54", "#53406c"], mortar="#22172f", levels=GH_DARK,
        water=["#6a4f98", "#a874b0", "#e8a8b8", "#ffe0c8"], smoke="#c99ab8",
        flowers=["#ffd27a", "#ff9ab4"], petals=["#ffb36e", "#ffd9a0"], birds=None, butterflies=False,
        fireflies=False, rays=False, streaks=True, grid_fx="sheen", sheen="#ffd9b0",
    ),
}

CSS = """
.tw{animation:tw 3s steps(1,end) infinite}
@keyframes tw{0%,100%{opacity:1}50%{opacity:.2}}
.pulse{animation:pulse 5s ease-in-out infinite}
@keyframes pulse{0%,100%{opacity:.45}50%{opacity:1}}
.bob{animation:bob 3.4s steps(1,end) infinite}
@keyframes bob{0%,100%{transform:translateY(0)}50%{transform:translateY(-1px)}}
.left{animation:left 320s steps(420) infinite}
@keyframes left{to{transform:translateX(-420px)}}
.right{animation:right 460s steps(420) infinite}
@keyframes right{from{transform:translateX(-420px)}to{transform:translateX(0)}}
.drift{animation:drift 40s steps(8) infinite}
@keyframes drift{0%,100%{transform:translateX(0)}50%{transform:translateX(4px)}}
.fa{animation:fa 1.2s steps(1,end) infinite}
.fb{animation:fa 1.2s steps(1,end) infinite;animation-delay:-.6s}
@keyframes fa{0%,49.9%{opacity:1}50%,100%{opacity:0}}
.flow{animation:flow .5s steps(5) infinite}
@keyframes flow{to{transform:translateY(5px)}}
.smoke{animation:smoke 6s steps(16) infinite;opacity:0}
@keyframes smoke{0%{transform:translate(0,0);opacity:0}12%{opacity:.8}100%{transform:translate(6px,-16px);opacity:0}}
.flicker{animation:flicker 2.6s steps(1,end) infinite}
@keyframes flicker{0%,100%{opacity:1}30%{opacity:.8}55%{opacity:.95}80%{opacity:.72}}
.shoot{animation:shoot 14s linear infinite;opacity:0}
@keyframes shoot{0%{transform:translate(0,0);opacity:0}1%{opacity:1}6%{transform:translate(-72px,36px);opacity:0}100%{opacity:0}}
.fly{animation:fly 80s steps(500) infinite}
@keyframes fly{from{transform:translateX(-40px)}to{transform:translateX(460px)}}
.sheen{animation:sheen 9s steps(70) infinite}
@keyframes sheen{0%{transform:translateX(0)}45%,100%{transform:translateX(330px)}}
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
    out = []
    if p["milky"]:
        # A faint band of the Milky Way, dense with dim stars.
        r = rng("milky")
        dust = Px()
        for _ in range(520):
            x = r.uniform(0, W)
            y = 6 + .2 * x + r.gauss(0, 9)
            if 0 <= y < 150:
                dust.set(x, y, r.choice(["#3a3f7a", "#4a4f8c", "#5a5f9a", "#8088c4"]))
        band = " ".join(f"{x},{6 + .2 * x + off}" for x, off in ((0, -14), (W, -14), (W, 14), (0, 14)))
        out.append(f'<polygon points="{band}" fill="#6a70c0" opacity=".07"/>'
                   f'<polygon points="{" ".join(f"{x},{6 + .2 * x + off}" for x, off in ((0, -6), (W, -6), (W, 6), (0, 6)))}" fill="#9aa0e0" opacity=".06"/>'
                   + dust.svg())
    if p["stars"]:
        count, ymax = p["stars"]
        r = rng("stars", ymax)
        dim = Px()
        for _ in range(count):
            x, y = r.randrange(2, W - 2), r.randrange(2, ymax)
            k = r.random()
            if k < .55:
                dim.set(x, y, mix(p["sky"][min(len(p["sky"]) - 1, y * len(p["sky"]) // H)], "#ffffff", .35))
            elif k < .92:
                out.append(g(f'<rect x="{x}" y="{y}" width="1" height="1" fill="{r.choice(["#ffffff", "#d6dcff", "#fff0d0"])}"/>',
                             cls="tw", style=f"animation-duration:{r.uniform(2, 5):.1f}s;animation-delay:-{r.uniform(0, 5):.1f}s"))
            else:
                s = Px()
                s.set(x, y, "#ffffff")
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    s.set(x + dx, y + dy, "#aab4ff")
                out.append(g(s.svg(), cls="tw", style=f"animation-duration:{r.uniform(3, 6):.1f}s;animation-delay:-{r.uniform(0, 6):.1f}s"))
        out.insert(0, dim.svg())
    if p["shooting"]:
        for x, y, delay in ((300, 12, 2), (190, 8, 9)):
            s = Px()
            for k in range(9):
                c = "#ffffff" if k == 0 else "#c9d1ff" if k < 3 else "#6a70b0"
                s.set(x + k * 2, y - k, c)
                s.set(x + k * 2 + 1, y - k, c)
            out.append(g(s.svg(), cls="shoot", style=f"animation-delay:{delay}s"))
    return "".join(out)


def orb(p):
    kind, cx, cy, r = p["orb"]
    lo, mid, hi = p["orb_ramp"]
    halo = "".join(f'<g opacity="{op}">{fill(ellipse(cx, cy, r + e, r + e), p["halo"])}</g>'
                   for e, op in ((2, .3), (5, .16), (9, .08), (15, .045), (23, .025)))
    body = Px()
    if kind == "moon":
        cut = set(ellipse(cx + 4, cy - 2, r - .5, r - .5))
        for x, y in set(ellipse(cx, cy, r, r)) - cut:
            edge = (x + 1, y) in cut or (x, y - 1) in cut
            body.set(x, y, mid if edge else hi)
        for x, y in ((cx - 6, cy + 1), (cx - 4, cy + 4), (cx - 5, cy - 3), (cx - 2, cy + 6)):
            if (int(x), int(y)) in body.p:
                body.set(x, y, lo)
    else:
        for x, y in ellipse(cx, cy, r, r):
            d = math.hypot(x + .5 - cx, y + .5 - cy) / r
            body.set(x, y, hi if d < .55 else mid if d < .85 else lo)
    extra = ""
    if p["rays"]:
        rays = []
        for i, ang in enumerate((-62, -47, -33, -21, -10)):
            a1, a2 = math.radians(ang - 2.2), math.radians(ang + 2.2)
            far = 520
            pts = f"{cx},{cy} {cx + far * math.cos(a1):.0f},{cy + far * math.sin(a1):.0f} {cx + far * math.cos(a2):.0f},{cy + far * math.sin(a2):.0f}"
            rays.append(f'<polygon points="{pts}" fill="url(#raydots)" class="pulse" style="animation-duration:{6 + i * 1.3:.1f}s;animation-delay:-{i * 1.7:.1f}s"/>')
        extra = f'<g opacity=".22">{"".join(rays)}</g>'
    if p["streaks"]:
        extra += "".join(f'<rect x="{x}" y="{y}" width="{w}" height="1" fill="{mid}" opacity="{op}"/>'
                         for x, y, w, op in ((236, 150, 184, .3), (270, 156, 150, .26), (190, 143, 120, .16), (300, 162, 120, .34)))
    return extra + g(halo, cls="pulse") + body.svg()


# ---------------------------------------------------------------- clouds

def cumulus(cx, base, w, h, seed):
    """Blobs for one fluffy cloud with a flat-ish bottom."""
    r = rng("cumulus", seed)
    blobs = []
    n = max(3, int(w / 9))
    for i in range(n):  # bottom row
        t = (i + .5) / n
        blobs.append((cx - w / 2 + t * w, base - h * .25, w / n * .9, h * .3))
    for i in range(max(2, n - 2)):  # billows
        t = (i + .5) / max(2, n - 2)
        bump = math.sin(math.pi * t)
        rad = h * (.35 + .45 * bump) * r.uniform(.85, 1.1)
        blobs.append((cx - w * .38 + t * w * .76, base - h * .3 - rad * .7, rad * 1.1, rad))
    return blobs


SKY_CLOUDS = [(66, 50, 58, 20, "a"), (206, 30, 38, 13, "b"), (300, 62, 46, 15, "c")]


def sky_clouds(p):
    out = []
    for i, (cx, base, w, h, seed) in enumerate(SKY_CLOUDS):
        blobs = cumulus(cx, base, w, h, seed)
        px, owner = shade_blobs(blobs, p["cloud"], p["light"], bias=.15, dither=.15, crease=True)
        px.p = {xy: c for xy, c in px.p.items() if xy[1] < base}
        out.append(g(px.svg(), cls="drift", style=f"animation-duration:{40 + i * 13}s;animation-delay:-{i * 9}s"))
    return "".join(out)


def periodic_row(cy, rx_range, ry_range, spacing, seed):
    r = rng("row", seed)
    n = max(1, round(W / spacing))
    blobs = []
    for i in range(n):
        x = (i + r.uniform(-.25, .25)) * W / n
        b = (x, cy + r.uniform(-2, 2), r.uniform(*rx_range), r.uniform(*ry_range))
        for shift in (-W, 0, W, 2 * W):
            blobs.append((b[0] + shift, b[1], b[2], b[3]))
    return sorted(blobs)


def cloud_sea(p):
    """Three rows of big puffs, nearer rows lower; spans 2W so it can scroll seamlessly."""
    blobs = (periodic_row(SEA_Y + 4, (20, 28), (11, 14), 34, "s0")
             + periodic_row(SEA_Y + 13, (16, 22), (9, 12), 28, "s1")
             + periodic_row(SEA_Y + 21, (13, 18), (8, 10), 23, "s2"))
    px, _ = shade_blobs(blobs, p["sea"][1:], (p["light"][0] * .3, -1, .5), bias=.25, dither=.05)
    px.p = {xy: c for xy, c in px.p.items() if 0 <= xy[0] < 2 * W}
    base = Px()
    base.rect(0, SEA_Y + 16, 2 * W, H - SEA_Y - 16, p["sea"][1])
    return base.merge(px).svg()


def horizon_bank(p):
    blobs = periodic_row(SEA_Y - 8, (26, 40), (12, 18), 46, "bank")
    px, _ = shade_blobs(blobs, p["bank"], (0, -1, .3), bias=.1, dither=.2, crease=False)
    px.p = {xy: c for xy, c in px.p.items() if 0 <= xy[0] < 2 * W}
    return px.svg()


# ---------------------------------------------------------------- island

def plateau_back(x):
    """Back edge of the grass plateau (rounded where it meets the sides)."""
    end = 24
    d = min(x - FL, FR - x)
    k = 1.0 if d >= end else math.sqrt(max(0.0, 1 - ((end - d) / end) ** 2))
    return TOP - round(DEPTH * k + .8 * math.sin(x / 7.0) * k)


def island_body(p):
    """Faceted rock: a tapering underside of chunks and spikes, buttresses at the sides."""
    r = rng("rock")
    mid = (FL + FR) / 2
    rows = [(LEDGE + 31, mid - 24, mid + 24, (6, 8), (6, 7), (6, 11)),
            (LEDGE + 23, FL + 88, FR - 88, (8, 11), (6, 8), (2, 8)),
            (LEDGE + 15, FL + 44, FR - 44, (10, 13), (6, 8), (0, 6)),
            (LEDGE + 7, FL + 16, FR - 16, (11, 14), (5, 7), (0, 3)),
            (LEDGE + 2, FL + 10, FR - 10, (10, 13), (3, 4), (0, 0))]
    # One solid core so the chunks read as a single mass rather than loose rubble.
    polys = [[(FL + 6, LEDGE - 1), (FR - 6, LEDGE - 1), (FR - 30, LEDGE + 12), (mid + 70, LEDGE + 22),
              (mid + 18, LEDGE + 34), (mid - 18, LEDGE + 34), (mid - 70, LEDGE + 22), (FL + 30, LEDGE + 12)]]
    for cy, x0, x1, rxr, ryr, spikes in rows:
        x = x0
        while x <= x1:
            rx = r.uniform(*rxr)
            spike = r.uniform(*spikes) if r.random() < .55 else 0
            polys.append(chunk(x, cy + r.uniform(-1.5, 1.5), rx, r.uniform(*ryr), r, spike))
            x += rx * r.uniform(1.2, 1.6)
    px, _ = shade_rocks(polys, p["rock"], p["light"], bias=-.28, bounce=p["bounce"])
    sides = []
    for side_x in (FL + 3, FR - 3):
        y = TOP + 5
        while y < LEDGE + 2:
            ry = r.uniform(4, 6)
            sides.append(chunk(side_x + r.uniform(-1, 1), y + ry * .6, r.uniform(4.5, 6), ry, r))
            y += ry * r.uniform(1.3, 1.7)
    shade_rocks(sides, p["rock"], p["light"], bias=-.02, rim=p["rim"], into=px)
    px.rect(GX - 2, TOP + 2, GRID_W + 4, LEDGE - TOP, p["rock"][1])   # soil behind the blocks
    return px


def blocks(p, levels):
    """The contribution graph as bevelled stone and moss blocks."""
    px = Px()
    px.rect(GX - 1, GY - 1, GRID_W + 2, GRID_H + 2, p["mortar"])
    lit_left = p["light"][0] < 0
    cells = []
    r = rng("blocks")
    dark_ref, light_ref = p["mortar"], "#ffffff"
    for wi, week in enumerate(levels):
        for di, level in enumerate(week):
            if level is None:
                continue
            x, y = GX + wi * PITCH, GY + di * PITCH
            if level == 0:
                lo, base, hi = p["block"]
            else:
                base = p["levels"][level - 1]
                hi, lo = mix(base, light_ref, .32), mix(base, dark_ref, .35)
            for dy in range(CELL):
                for dx in range(CELL):
                    ex = dx if lit_left else CELL - 1 - dx
                    c = base
                    if dy == 0 or ex == 0:
                        c = hi
                    if dy == CELL - 1 or ex == CELL - 1:
                        c = lo
                    if (dy == 0 and ex == CELL - 1) or (dy == CELL - 1 and ex == 0):
                        c = base
                    px.set(x + dx, y + dy, c)
            if level == 0 and r.random() < .12:
                px.set(x + 1 + r.randint(0, 1), y + 2, lo)        # a crack
            if level >= 3 and r.random() < .6:                    # grass sprouting from busy days
                px.set(x + r.randint(0, CELL - 1), y - 1, mix(base, light_ref, .45))
            cells.append((x, y, level))
    return px, cells


def grid_fx(p, cells):
    r = rng("gridfx")
    fx = p["grid_fx"]
    if fx == "glow":
        out = []
        for x, y, level in cells:
            if level >= 2:
                out.append(g(f'<rect x="{x - 1}" y="{y - 1}" width="{CELL + 2}" height="{CELL + 2}" fill="#7ee787"/>',
                             cls="pulse", opacity=.12 + .07 * level,
                             style=f"animation-duration:{r.uniform(3, 6):.1f}s;animation-delay:-{r.uniform(0, 6):.1f}s"))
        return "".join(out)
    if fx == "dew":
        out = []
        for x, y, level in r.sample(cells, min(22, len(cells))):
            out.append(g(f'<rect x="{x + 1}" y="{y + 1}" width="1" height="1" fill="#ffffff"/>', cls="tw",
                         style=f"animation-duration:{r.uniform(2, 4.5):.1f}s;animation-delay:-{r.uniform(0, 4):.1f}s"))
        return "".join(out)
    if fx == "sheen":
        clip = "".join(f'<rect x="{x}" y="{y}" width="{CELL}" height="{CELL}"/>' for x, y, _ in cells)
        band = (f'<polygon class="sheen" points="{GX - 40},{GY - 2} {GX - 30},{GY - 2} {GX - 44},{GY + GRID_H + 2} '
                f'{GX - 54},{GY + GRID_H + 2}" fill="{p["sheen"]}" opacity=".45"/>')
        return f'<clipPath id="cells">{clip}</clipPath><g clip-path="url(#cells)">{band}</g>'
    return ""


def plateau(p, shadows):
    """Grass top seen from slightly above, with a lip that spills over the cliff."""
    gr = p["grass"]
    r = rng("plateau")
    px = Px()
    for x in range(FL, FR + 1):
        back = plateau_back(x)
        for y in range(back, TOP):
            depth = (y - back) / max(1, TOP - back)
            stripe = ((x + 2 * (TOP - y)) // 14) % 2
            c = gr[3] if stripe else gr[2]
            if y == back:
                c = gr[5] if (x + y) % 3 else gr[4]
            elif y == back + 1:
                c = gr[4]
            elif depth > .85:
                c = gr[3]
            if r.random() < .05:
                c = gr[1]
                px.set(x, y - 1, gr[4]) if y - 1 > back else None
            px.set(x, y, c)
        # front lip: grass spilling over the edge, then a fringe of drips and roots
        px.set(x, TOP, gr[4] if x % 4 else gr[5])
        px.set(x, TOP + 1, gr[2])
        px.set(x, TOP + 2, gr[1])
        drop = r.random()
        if drop < .45:
            px.set(x, TOP + 3, gr[1])
        if drop < .16:
            px.set(x, TOP + 4, gr[0])
        if drop < .05:
            px.set(x, TOP + 5, gr[0])
    for x in (FL, FR):  # rounded front corners
        px.p.pop((x, TOP), None)
    for sx, sy, srx, sry in shadows:  # contact shadows cast by things on the plateau
        for x, y in ellipse(sx, sy, srx, sry):
            c = px.get(x, y)
            if c in gr[2:]:
                px.set(x, y, gr[max(0, gr.index(c) - 2)])
    return px


def stream_and_fall(p):
    lo, mid, hi, foam = p["water"]
    st = Px()
    sparkles = []
    pts = [(FR - 34, TOP - 9), (FR - 24, TOP - 7), (FR - 14, TOP - 5), (FR - 4, TOP - 3), (FR + 1, TOP - 1)]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        for i in range(0, 11):
            t = i / 10
            x, y = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
            st.set(x, y, mid)
            st.set(x + 1, y, mid)
            st.set(x, y + 1, lo)
            st.set(x + 1, y + 1, lo)
    for x, y in pts[1:4]:
        sparkles.append(g(f'<rect x="{x}" y="{y}" width="1" height="1" fill="{foam}"/>', cls="tw", style="animation-duration:1.6s"))
    x0 = FR + 1
    fall = Px()
    for y in range(TOP - 1, SEA_Y + 8):
        for i, c in enumerate((lo, mid, hi, mid, lo)):
            fall.set(x0 + i, y, c)
    for x in range(x0 - 1, x0 + 6):
        fall.set(x, TOP - 1, foam if x % 2 else hi)
    streaks = Px()
    for y in range(TOP - 10, SEA_Y + 10):
        for i in range(5):
            if (y + i * 3) % 5 == 0:
                streaks.set(x0 + i, y, foam if i in (1, 2, 3) else hi)
    clip = f'<clipPath id="fall"><rect x="{x0}" y="{TOP}" width="5" height="{SEA_Y + 8 - TOP}"/></clipPath>'
    return st.svg() + "".join(sparkles) + fall.svg() + clip + g(g(streaks.svg(), cls="flow"), clip_path="url(#fall)")


def splash(p):
    foam = p["water"][3]
    x0 = FR + 3
    a, b = Px(), Px()
    for x, y in ((x0 - 4, SEA_Y + 1), (x0 + 5, SEA_Y), (x0 + 1, SEA_Y - 2), (x0 + 8, SEA_Y + 2), (x0 - 7, SEA_Y + 3)):
        a.set(x, y, foam)
    for x, y in ((x0 - 2, SEA_Y - 1), (x0 + 3, SEA_Y - 3), (x0 + 7, SEA_Y + 1), (x0 - 6, SEA_Y + 1), (x0 + 10, SEA_Y + 3)):
        b.set(x, y, foam)
    mist = f'<g opacity=".4">{fill([(x, y) for x, y in ellipse(x0, SEA_Y + 1, 10, 4) if (x + y) % 3 == 0], foam)}</g>'
    return mist + g(a.svg(), cls="fa", style="animation-duration:.8s") + g(b.svg(), cls="fb", style="animation-duration:.8s;animation-delay:-.4s")


def vines(p):
    a, b = Px(), Px()
    r = rng("vines")
    gr = p["grass"]
    spots = [(x, LEDGE + 3 + r.randint(0, 6)) for x in r.sample(range(FL + 24, FR - 24), 9)]
    spots += [(FL + 3, TOP + 3), (FL + 6, TOP + 3), (FR - 4, TOP + 3)]
    for x, y0 in spots:
        length = r.randint(5, 13)
        for k in range(length):
            sway = 1 if k > length // 2 else 0
            a.set(x, y0 + k, gr[1])
            b.set(x + sway, y0 + k, gr[1])
            if k % 3 == 1:
                a.set(x - 1, y0 + k, gr[3])
                b.set(x + sway + 1, y0 + k, gr[3])
    return g(a.svg(), cls="fa", style="animation-duration:3.2s") + g(b.svg(), cls="fb", style="animation-duration:3.2s;animation-delay:-1.6s")


# ---------------------------------------------------------------- things on the plateau

TREE_BLOBS = [(0, -31, 12, 10), (-13, -26, 10, 9), (13, -27, 10, 9), (-22, -16, 9, 8), (22, -17, 9, 8),
              (-8, -18, 11, 10), (9, -19, 11, 10), (0, -10, 14, 10), (-17, -6, 10, 7), (17, -7, 10, 7),
              (-27, -4, 6, 5), (27, -5, 6, 5), (-6, -2, 9, 6), (8, -2, 9, 6)]


def tree(p):
    tx, base = TREE_X, TOP - 7
    ty = base - 17
    lx = p["light"][0]
    tr = p["trunk"]
    trunk = Px()
    for y in range(ty - 4, base + 1):
        t = (y - ty) / (base - ty)
        half = 1.6 + 1.4 * max(0, t) + (2.5 * (t - .8) / .2 if t > .8 else 0)
        for x in range(math.floor(tx - half), math.ceil(tx + half) + 1):
            u = (x + .5 - tx) / max(half, 1) * (1 if lx > 0 else -1)
            c = tr[3] if u > .45 else tr[2] if u > -.1 else tr[1] if u > -.6 else tr[0]
            trunk.set(x, y, c)
    for i in range(7):  # branches into the canopy
        trunk.set(tx - i, ty - i, tr[1])
        trunk.set(tx + 1 + i, ty - 1 - i, tr[2])

    blobs = [(tx + .5 + dx, ty + dy, rx, ry) for dx, dy, rx, ry in TREE_BLOBS]
    leaves, owner = shade_blobs(blobs, p["leaves"], p["light"], bias=.05, rim=p["rim"], dither=.1)
    r = rng("tree")
    lit = sorted(xy for xy, c in leaves.p.items() if c in p["leaves"][3:])
    for x, y in r.sample(lit, min(26, len(lit))):
        leaves.set(x, y, p["blossom"][0])
        if (x, y - 1) in owner:
            leaves.set(x, y - 1, p["blossom"][1])

    edge = sorted(xy for xy in owner if (xy[0], xy[1] - 1) not in owner)
    a, b = Px(), Px()
    for x, y in r.sample(edge, min(22, len(edge))):
        c = leaves.p.pop((x, y))
        a.set(x, y, c)
        b.set(x + 1, y, c)
    wind = g(a.svg(), cls="fa", style="animation-duration:2.4s") + g(b.svg(), cls="fb", style="animation-duration:2.4s;animation-delay:-1.2s")

    sa, sb = Px(), Px()   # a swing hanging from the right bough
    for frame, shift in ((sa, 0), (sb, 1)):
        for y in range(ty - 1, base - 4):
            off = shift if y > ty + 6 else 0
            frame.set(tx + 15 + off, y, tr[0])
            frame.set(tx + 22 + off, y, tr[0])
        frame.rect(tx + 14 + shift, base - 4, 10, 1, tr[3])
        frame.rect(tx + 14 + shift, base - 3, 10, 1, tr[1])
    swing = g(sa.svg(), cls="fa", style="animation-duration:2.8s") + g(sb.svg(), cls="fb", style="animation-duration:2.8s;animation-delay:-1.4s")
    shadow_x = tx - 4 if lx > 0 else tx + 4
    return swing + trunk.svg() + leaves.svg() + wind, (shadow_x, base, 16, 3)


def bush(p, cx, base, w, seed):
    r = rng("bush", seed)
    blobs = []
    n = max(2, int(w / 5))
    for i in range(n):
        t = (i + .5) / n
        h = 3 + 3 * math.sin(math.pi * t)
        blobs.append((cx - w / 2 + t * w, base - h * .6, w / n * .85 + 1, h))
    px, owner = shade_blobs(blobs, p["leaves"], p["light"], bias=.1, rim=p["rim"], dither=.1)
    for x, y in r.sample(sorted(owner), max(1, len(owner) // 18)):
        px.set(x, y, p["blossom"][0])
    px.p = {xy: c for xy, c in px.p.items() if xy[1] <= base}
    return px.svg(), (cx, base, w * .6, 2)


def house(p):
    hp = p["house"]
    hx, hb = HOUSE_X, TOP - 6
    fw, fh, rh, o = 17, 11, 10, 2
    dx_, dy_ = 11, -5
    lit_front = p["light"][0] < 0
    wall, side, roof = hp["wall"], hp["side"], hp["roof"]
    px = Px()

    for i in range(1, dx_ + 1):  # side wall, receding to the right
        x = hx + fw - 1 + i
        yo = round(i * dy_ / dx_)
        for y in range(hb - fh + yo, hb + 1 + yo):
            row = y - yo - (hb - fh)
            c = side[0] if lit_front else side[1]
            if row % 3 == 2:
                c = mix(c, hp["trim"], .35)
            if y == hb + yo:
                c = hp["stone"][0]
            px.set(x, y, c)
    for i in range(4, 8):  # side window
        x = hx + fw - 1 + i
        yo = round(i * dy_ / dx_)
        for y in range(hb - 8 + yo, hb - 4 + yo):
            edge = i in (4, 7) or y in (hb - 8 + yo, hb - 5 + yo)
            px.set(x, y, hp["trim"] if edge else hp["glass"][0])

    peak = (hx + fw // 2, hb - fh - rh)
    eave = (hx + fw - 1 + o, hb - fh + 1)
    ax, ay = eave[0] - peak[0], eave[1] - peak[1]
    det = ax * dy_ - ay * dx_
    for y in range(peak[1] + dy_ - 1, eave[1] + 2):  # roof plane along the side
        for x in range(peak[0] - 1, eave[0] + dx_ + 2):
            qx, qy = x + .5 - peak[0], y + .5 - peak[1]
            s = (qx * dy_ - qy * dx_) / det
            t = (ax * qy - ay * qx) / det
            if 0 <= s <= 1 and 0 <= t <= 1:
                course = s * 6
                c = roof[2] if int(course) % 2 else roof[1]
                if course - int(course) < .18:
                    c = roof[0]
                if t > .93 or s > .94:
                    c = roof[0]
                if s < .08:
                    c = roof[3]                     # ridge catches the light
                if not lit_front and int(course) % 2 and (x + y) % 5 == 0:
                    c = roof[3]
                px.set(x, y, c)

    gable_top = hb - fh
    for y in range(peak[1], gable_top):  # front gable with its bargeboards
        t = (y - peak[1] + 1) / (gable_top - peak[1])
        half = t * (fw / 2 + o)
        for x in range(math.floor(peak[0] + .5 - half), math.ceil(peak[0] + .5 + half)):
            inner = abs(x + .5 - (peak[0] + .5)) < half - 2.2
            c = (wall[2] if lit_front else wall[1]) if inner else roof[0]
            if not inner and x + .5 < peak[0] + .5 and lit_front:
                c = roof[3]
            px.set(x, y, c)
    for x in range(hx - o, hx + fw + o):
        px.set(x, gable_top, roof[0])
    for x in range(hx, hx + fw):  # front wall
        for y in range(gable_top + 1, hb + 1):
            c = wall[2] if lit_front else wall[1]
            if (y - gable_top) % 3 == 0:
                c = wall[1] if lit_front else wall[0]
            if x in (hx, hx + fw - 1):
                c = hp["trim"]
            if y == hb:
                c = hp["stone"][(x // 2) % 2]
            px.set(x, y, c)
    px.set(peak[0], peak[1] + 4, hp["trim"])
    for dx in (-1, 0, 1):  # round attic window
        px.set(peak[0] + dx, peak[1] + 5, hp["glass"][0] if dx == 0 else hp["trim"])
    px.set(peak[0], peak[1] + 6, hp["trim"])
    door = hp["door"]
    for y in range(hb - 7, hb):
        for x in range(hx + 10, hx + 14):
            edge = x in (hx + 10, hx + 13) or y == hb - 7
            px.set(x, y, door[0] if edge else door[1])
    px.set(hx + 12, hb - 4, "#ffd27a")
    for y in range(hb - 9, hb - 5):  # front window
        for x in range(hx + 2, hx + 7):
            edge = x in (hx + 2, hx + 6) or y in (hb - 9, hb - 6)
            px.set(x, y, hp["trim"] if edge else hp["glass"][0])
    px.set(hx + 3, hb - 8, hp["glass"][1])
    px.set(hx + 4, hb - 8, hp["glass"][1])
    for x in range(hx + 1, hx + 8):  # flower box
        px.set(x, hb - 5, hp["trim"])
        px.set(x, hb - 4, hp["trim"])
    for x in (hx + 2, hx + 4, hx + 6):
        px.set(x, hb - 6, hp["flower"])
    px.set(hx + 3, hb - 6, p["grass"][3])
    px.set(hx + 5, hb - 6, p["grass"][3])

    ch = (round(peak[0] + .3 * ax + .6 * dx_), round(peak[1] + .3 * ay + .6 * dy_))
    chim = hp["chimney"]
    for y in range(ch[1] - 7, ch[1] + 1):
        px.set(ch[0] - 1, y, chim[0] if not lit_front else chim[1])
        px.set(ch[0], y, chim[1] if not lit_front else chim[0])
        px.set(ch[0] + 1, y, chim[1] if not lit_front else chim[0])
    for x in range(ch[0] - 2, ch[0] + 3):
        px.set(x, ch[1] - 8, hp["trim"])

    out = px.svg()
    if p["windows_lit"]:
        out += g(glow(hx + 4.5, hb - 7.5, p["glow"]) + glow(hx + fw + 5, hb - 9, p["glow"], ((3, .25), (6, .1))), cls="flicker")
    if p["smoke"]:
        for i in range(3):
            s = Px()
            s.rect(ch[0] - 1, ch[1] - 11, 2, 2, p["smoke"])
            s.set(ch[0] + 1, ch[1] - 10, p["smoke"])
            out += g(s.svg(), cls="smoke", style=f"animation-delay:-{i * 2:.1f}s")
    return out, (hx + fw / 2 + 4, hb + 1, 16, 3)


LAMP = ["...t...", "..ttt..", ".tLLLt.", ".tLlLt.", ".tLLLt.", "..ttt..", "...p...", "...p...", "...p...",
        "...p...", "...p...", "...p...", "...p...", "..ppp..", ".ppppp."]


def lamp(p):
    lx, ly = LAMP_X, TOP - 3 - len(LAMP) + 1
    trim = p["house"]["trim"]
    on = p["lamp_on"]
    px = Px()
    px.sprite(lx, ly, LAMP, {"t": trim, "p": trim, "L": "#ffd27a" if on else "#d6d2c4", "l": "#fff6d0" if on else "#eeeae0"})
    out = px.svg()
    if on:
        out += g(glow(lx + 3.5, ly + 3.5, p["glow"], ((4, .35), (7, .18), (11, .09), (16, .045))), cls="flicker")
        pool = Px()
        for x, y in ellipse(lx + 3.5, TOP - 3, 12, 3):
            if x % 2 == 0 and y % 2 == 0:
                pool.set(x, y, p["glow"])
        out += g(pool.svg(), opacity=.14, cls="flicker")
    return out, (lx + 3.5, TOP - 2, 4, 1)


def path_stones(p):
    px = Px()
    stone = p["house"]["stone"]
    for x, y in ((HOUSE_X + 11, TOP - 4), (HOUSE_X + 7, TOP - 2), (HOUSE_X + 2, TOP - 1), (HOUSE_X - 4, TOP)):
        for cx, cy in ellipse(x, y, 2.2, 1.1):
            px.set(cx, cy, stone[1])
        px.set(x - 1, y, stone[0])
    return px.svg()


def flowers(p):
    px = Px()
    r = rng("flowers")
    for i in range(16):
        x = r.choice((r.randint(FL + 6, TREE_X - 20), r.randint(TREE_X + 28, LAMP_X - 4), r.randint(HOUSE_X + 30, FR - 36)))
        y = r.randint(TOP - DEPTH + 4, TOP - 1)
        px.set(x, y, p["flowers"][i % len(p["flowers"])])
        px.set(x, y + 1, p["grass"][1])
    return px.svg()


def islet(p, cx, top, w, seed):
    r = rng("islet", seed)
    gr = p["grass"]
    polys = [chunk(cx + r.uniform(-1, 1), top + 10, w * .14, 4, r, r.uniform(3, 6)),
             chunk(cx - w * .18, top + 5, w * .2, 3.5, r), chunk(cx + w * .2, top + 5, w * .2, 3.5, r),
             chunk(cx, top + 3, w * .45, 2.5, r)]
    px, _ = shade_rocks(polys, p["rock"], p["light"], bias=-.1, rim=p["rim"], bounce=p["bounce"])
    for x in range(int(cx - w / 2 + 1), int(cx + w / 2)):
        px.set(x, top - 1, gr[4])
        px.set(x, top, gr[3])
        px.set(x, top + 1, gr[1])
        if r.random() < .3:
            px.set(x, top + 2, gr[0])
    b, _ = bush(p, cx - w * .15, top - 1, w * .35, seed)
    return px.svg() + b


# ---------------------------------------------------------------- drifting life

def petals(p):
    if not p["petals"]:
        return ""
    r = rng("petals")
    out, css = [], []
    direction = 1 if p["light"][0] < 0 else -1
    for i in range(8):
        x, y = TREE_X + r.randint(-24, 24), r.randint(TOP - 52, TOP - 24)
        dur = r.uniform(10, 16)
        drift = r.uniform(20, 46) * direction
        fall_ = r.uniform(50, 90)
        css.append(f"@keyframes pt{i}{{0%{{transform:translate(0,0);opacity:0}}8%{{opacity:1}}"
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
        out.append(g(flutter, style=f"animation:pt{i} {dur:.1f}s steps(48) infinite;animation-delay:-{r.uniform(0, dur):.1f}s;opacity:0"))
    return f"<style>{''.join(css)}</style>" + "".join(out)


def wanderers(p, kind):
    """Fireflies at night, butterflies at noon: small things drifting around the plateau."""
    r = rng(kind)
    out, css = [], []
    count = 11 if kind == "ff" else 3
    for i in range(count):
        x = r.choice((r.randint(TREE_X - 30, TREE_X + 30), r.randint(TREE_X + 34, HOUSE_X - 4)))
        y = r.randint(TOP - 34, TOP - 6) if kind == "ff" else r.randint(TOP - 22, TOP - 8)
        span = 8 if kind == "ff" else 14
        pts = [(0, 0)] + [(r.randint(-span, span), r.randint(-5, 5)) for _ in range(3)] + [(0, 0)]
        frames = "".join(f"{k * 25}%{{transform:translate({dx}px,{dy}px)}}" for k, (dx, dy) in enumerate(pts))
        css.append(f"@keyframes {kind}{i}{{{frames}}}")
        if kind == "ff":
            body = (f'<g opacity=".35"><rect x="{x - 1}" y="{y}" width="3" height="1" fill="#e9ff9c"/>'
                    f'<rect x="{x}" y="{y - 1}" width="1" height="3" fill="#e9ff9c"/></g>'
                    f'<rect x="{x}" y="{y}" width="1" height="1" fill="#f6ffd0"/>')
            inner = g(body, cls="tw", style=f"animation-duration:{r.uniform(1.5, 3):.1f}s;animation-delay:-{r.uniform(0, 3):.1f}s")
        else:
            color = ["#ffffff", "#fff07a", "#ffb3d0"][i % 3]
            a, b = Px(), Px()
            a.sprite(x - 1, y, ["#.#", ".#."], {"#": color})
            b.sprite(x - 1, y, [".#.", ".#."], {"#": color})
            inner = g(a.svg(), cls="fa", style="animation-duration:.4s") + g(b.svg(), cls="fb", style="animation-duration:.4s;animation-delay:-.2s")
        dur = r.uniform(9, 16)
        out.append(g(inner, style=f"animation:{kind}{i} {dur:.1f}s steps(36) infinite;animation-delay:-{r.uniform(0, dur):.1f}s"))
    return f"<style>{''.join(css)}</style>" + "".join(out)


def birds(p):
    if not p["birds"]:
        return ""
    up, down = Px(), Px()
    for bx, by in ((0, 0), (10, 5), (19, 1)):
        up.sprite(bx, by, ["#...#", ".#.#.", "..#.."], {"#": p["birds"]})
        down.sprite(bx, by + 1, ["##.##", "..#.."], {"#": p["birds"]})
    flap = g(up.svg(), cls="fa", style="animation-duration:.7s") + g(down.svg(), cls="fb", style="animation-duration:.7s;animation-delay:-.35s")
    return g(g(flap, transform="translate(0,26)"), cls="fly")


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
    defs = (sky_defs + frame_clip()
            + '<pattern id="raydots" width="2" height="2" patternUnits="userSpaceOnUse"><rect width="1" height="1" fill="#fff4dc"/></pattern>')

    tree_svg, tree_shadow = tree(p)
    house_svg, house_shadow = house(p)
    lamp_svg, lamp_shadow = lamp(p)
    bushes = [bush(p, FL + 14, TOP - 1, 16, "a"), bush(p, FR - 22, TOP - 10, 12, "b"),
              bush(p, FR - 44, TOP - 1, 11, "c"), bush(p, TREE_X - 30, TOP - 9, 10, "d")]
    shadows = [tree_shadow, house_shadow, lamp_shadow] + [s for _, s in bushes]
    block_px, cells = blocks(p, levels)

    island = (
        island_body(p).svg() + block_px.svg() + grid_fx(p, cells) + vines(p)
        + plateau(p, shadows).svg() + path_stones(p) + flowers(p) + stream_and_fall(p)
        + bushes[1][0] + bushes[3][0] + tree_svg + house_svg + lamp_svg + bushes[0][0] + bushes[2][0]
    )
    islets = (g(islet(p, 30, 122, 24, "l"), cls="bob", style="animation-duration:2.8s;animation-delay:-1s")
              + g(islet(p, 394, 74, 18, "r"), cls="bob", style="animation-duration:3.8s"))
    body = (
        sky_rows + stars(p) + orb(p) + sky_clouds(p)
        + g(horizon_bank(p), cls="right") + birds(p)
        + g(island, cls="bob") + islets
        + g(cloud_sea(p), cls="left") + splash(p)
        + petals(p) + (wanderers(p, "ff") if p["fireflies"] else "") + (wanderers(p, "bf") if p["butterflies"] else "")
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W * SCALE}" height="{H * SCALE}" '
        f'shape-rendering="crispEdges"><style>{CSS}</style>'
        f'<defs>{defs}</defs><g clip-path="url(#frame)">{body}</g></svg>\n'
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
