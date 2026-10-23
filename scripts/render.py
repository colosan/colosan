"""Render the floating-island scene for each time of day.

Each scene is painted as continuous watercolour (soft washes, pigment pooling at the
edges, paper grain), then reduced to a per-scene palette with ordered dithering so it
reads as pixel art. The island's cliff face is the real contribution graph laid as
crisp bevelled blocks in GitHub's own greens. A bloom pass is applied as an SVG
filter; small animated details are overlaid as pixels.

usage:
  python scripts/render.py now <out.svg>             # scene for the current hour in Seoul
  python scripts/render.py all <out_dir> [names...]  # all (or some) scenes
"""
import base64
import io
import json
import math
import os
import random
import re
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from PIL import Image

W, H, SCALE = 420, 200, 3
TOP = 100                                 # front lip of the island's grass plateau
DEPTH = 13                                # how far back the plateau reaches
CELL, PITCH = 4, 5                        # contribution block size / spacing
GRID_W, GRID_H = 53 * PITCH - 1, 7 * PITCH - 1
GX, GY = (W - GRID_W) // 2, TOP + 6
FL, FR = GX - 15, GX + GRID_W + 14        # island face left/right
LEDGE = GY + GRID_H + 1
SEA_TOP, SEA_Y = 148, 172                 # cloud-sea layer origin / typical crest line
TREE_X, HOUSE_X, LAMP_X = FL + 50, FL + 166, FL + 150
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


# ---------------------------------------------------------------- watercolour toolkit

def col(c):
    return np.array([int(c[i:i + 2], 16) for i in (1, 3, 5)], dtype=np.float32) / 255


def hexs(rgb):
    return "#" + "".join(f"{int(min(255, max(0, v))):02x}" for v in rgb)


def smooth(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)


def ramp(stops, t):
    """Interpolate a list of hex colours along t in [0, 1] (any shape) -> (..., 3)."""
    cs = np.stack([col(c) for c in stops])
    pos = np.linspace(0, 1, len(stops))
    t = np.clip(t, 0, 1)
    return np.stack([np.interp(t, pos, cs[:, k]) for k in range(3)], axis=-1).astype(np.float32)


def vnoise(h, w, cy, cx, seed, wrap=False):
    """Smooth value noise with cells of cy x cx pixels; optionally periodic in x."""
    g_ = np.random.default_rng(seed)
    gw = max(1, int(round(w / cx))) if wrap else int(math.ceil(w / cx)) + 2
    gh = int(math.ceil(h / cy)) + 2
    grid = g_.random((gh, gw)).astype(np.float32)
    ys, xs = (np.arange(h) + .5) / cy, (np.arange(w) + .5) / cx
    y0, x0 = np.floor(ys).astype(int), np.floor(xs).astype(int)
    fy, fx = ys - y0, xs - x0
    sy, sx = fy * fy * (3 - 2 * fy), fx * fx * (3 - 2 * fx)
    xa, xb = (x0 % gw, (x0 + 1) % gw) if wrap else (x0, x0 + 1)
    a, b = grid[np.ix_(y0, xa)], grid[np.ix_(y0, xb)]
    c, d = grid[np.ix_(y0 + 1, xa)], grid[np.ix_(y0 + 1, xb)]
    top, bot = a + (b - a) * sx, c + (d - c) * sx
    return (top + (bot - top) * sy[:, None]).astype(np.float32)


def fbm(h, w, cells, seed, wrap=False, stretch=1.0):
    out, amp, tot = np.zeros((h, w), np.float32), 1.0, 0.0
    for i, c in enumerate(cells):
        out += amp * vnoise(h, w, c, c * stretch, seed * 31 + i, wrap)
        tot += amp
        amp *= .55
    return out / tot


def blur(a, r):
    """Separable box blur, applied twice (close to a gaussian)."""
    for _ in range(2):
        for axis in (0, 1):
            pad = [(0, 0), (0, 0)]
            pad[axis] = (r + 1, r)
            c = np.cumsum(np.pad(a, pad, mode="edge"), axis=axis, dtype=np.float64)
            n = a.shape[axis]
            hi = np.take(c, np.arange(2 * r + 1, 2 * r + 1 + n), axis=axis)
            lo = np.take(c, np.arange(0, n), axis=axis)
            a = ((hi - lo) / (2 * r + 1)).astype(np.float32)
    return a


class Layer:
    """Float RGBA canvas painted with transparent washes."""

    def __init__(self, w=W, h=H):
        self.w, self.h = w, h
        self.rgb = np.zeros((h, w, 3), np.float32)
        self.a = np.zeros((h, w), np.float32)
        self.Y, self.X = (np.mgrid[0:h, 0:w].astype(np.float32) + .5)

    def paint(self, cover, color):
        cover = np.clip(np.asarray(cover, np.float32), 0, 1)[..., None]
        self.rgb = self.rgb * (1 - cover) + np.asarray(color, np.float32) * cover
        self.a = cover[..., 0] + self.a * (1 - cover[..., 0])

    def glaze(self, cover, color, strength=1.0):
        """Multiply a transparent pigment over what is already there (watercolour glazing)."""
        cover = (np.clip(cover, 0, 1) * strength)[..., None]
        self.rgb = self.rgb * (1 - cover + cover * np.asarray(color, np.float32))

    def light(self, cover, color):
        cover = np.clip(cover, 0, 1)[..., None]
        self.rgb = 1 - (1 - self.rgb) * (1 - cover * np.asarray(color, np.float32))


def wash(layer, field, colors, soft=.55, rim=.18, rim_w=2.5, grain=.06, seed=0, alpha=1.0):
    """Paint a region (field > 0, roughly in pixels) with pooled-pigment edges and granulation."""
    cover = smooth(-soft, soft, field) * alpha
    edge = np.clip(1 - field / rim_w, 0, 1) * (field > -soft)
    gran = vnoise(layer.h, layer.w, 1.3, 1.3, seed + 7)
    shade = 1 - rim * edge - grain * (gran - .5)
    layer.paint(cover, colors * shade[..., None])
    return cover


def bands(t, n, wobble, amt=.12):
    """Posterise a tone into n flat steps, roughening the step edges with noise."""
    t = np.clip(t + (wobble - .5) * amt, 0, 1)
    return np.round(t * (n - 1)) / (n - 1)


def segments_dist(X, Y, pts):
    """Distance from each pixel to a polyline, plus the parameter along it (0..1)."""
    best = np.full(X.shape, 1e9, np.float32)
    tpar = np.zeros(X.shape, np.float32)
    total = sum(math.dist(a, b) for a, b in zip(pts, pts[1:])) or 1
    acc = 0.0
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        dx, dy = x1 - x0, y1 - y0
        ln2 = dx * dx + dy * dy or 1
        t = np.clip(((X - x0) * dx + (Y - y0) * dy) / ln2, 0, 1)
        d = np.hypot(X - (x0 + t * dx), Y - (y0 + t * dy))
        closer = d < best
        best = np.where(closer, d, best)
        tpar = np.where(closer, (acc + t * math.sqrt(ln2)) / total, tpar)
        acc += math.sqrt(ln2)
    return best, tpar


def poly_mask(X, Y, pts):
    inside = np.zeros(X.shape, bool)
    n = len(pts)
    for i in range(n):
        (x0, y0), (x1, y1) = pts[i], pts[(i + 1) % n]
        cond = (y0 > Y) != (y1 > Y)
        xi = x0 + (Y - y0) * (x1 - x0) / ((y1 - y0) or 1e-6)
        inside ^= cond & (X < xi)
    return inside.astype(np.float32)


# ---------------------------------------------------------------- palettes

PAL = {
    "dawn": dict(
        sky=["#05061a", "#0a0c26", "#121534", "#1c1f48", "#2a2a5a", "#40375f", "#6e4a6c"], bloom="#2a3070", bloom_k=.35,
        horizon="#b0708a", bank_alpha=.4, light=(.5, -.6, .6), orb=("moon", 364, 36, 9), orb_core="#f8f1d8", orb_glow="#7f8cff",
        stars=True, milky=True, shooting=True, rays=False, streaks=False,
        cloud=("#5f68ae", "#232758", "#171a42"), cloud_alpha=.8,
        sea=("#8a8ccc", "#464a8e", "#2a2c64", "#1a1c46"), haze="#3a3468",
        rock=("#6a70b0", "#3c3866", "#241f44", "#100d24"), rim="#8f9ae0", cool=None, bounce="#3a4282",
        block=["#1e1a3a", "#29244a", "#38325e"], mortar="#151229", levels=GH_DARK,
        grass=("#4f8f86", "#2d6660", "#1d4a48", "#112e30"),
        leaves=("#7aa8c0", "#2e6468", "#173c44", "#0a1e2a"), trunk=("#4a4470", "#16122a"),
        house=dict(wall="#2a2648", wall_lit="#565a96", roof="#232046", roof_lit="#4a4a88", trim="#0f0d1f",
                   glass="#ffc66a", door="#1e1a34", stone="#2a2640", base="#120f22", flower="#a99ae0"),
        windows_lit=True, lamp_on=True, glow="#ffb347", water=("#b4bcf0", "#5a64b0", "#2e3478"),
        smoke=None, flowers=["#a99ae0", "#8fc4ff"], leaves_fall=None, birds=None, butterflies=False,
        fireflies=True, grid_fx="glow", sheen=None, bloom_amt=.7,
    ),
    "morning": dict(
        sky=["#6f8fd8", "#8ea6e2", "#b4b8e6", "#d8c4e2", "#f2cfd3", "#ffe2cc"], bloom="#f4c8d4", bloom_k=.2,
        horizon=None, bank_alpha=.85, light=(-.8, -.35, .5), orb=("sun", 28, 158, 9), orb_core="#fffbf0", orb_glow="#ffd2ac",
        stars=False, milky=False, shooting=False, rays=True, streaks=False,
        cloud=("#fff6ef", "#cdb2d4", "#a98fc0"), cloud_alpha=.92,
        sea=("#fff8f2", "#eed4e2", "#cdb0d2", "#ad93c4"), haze="#f2d6de",
        rock=("#e2b39c", "#a87a86", "#6a4c6c", "#3a2a48"), rim="#ffd2b0", cool=None, bounce="#dcc4dc",
        block=["#8c6c80", "#9a7a8e", "#ac8ea0"], mortar="#76586c", levels=GH_LIGHT,
        grass=("#e2efa4", "#a9d488", "#6fae74", "#3f7a5c"),
        leaves=("#d6eaa4", "#86bc7c", "#4a8066", "#24484a"), trunk=("#b48474", "#5a3e4e"),
        house=dict(wall="#b49cae", wall_lit="#fff3ea", roof="#b85a4e", roof_lit="#e08268", trim="#5e4660",
                   glass="#9fb8e8", door="#7a5068", stone="#a890a4", base="#6a5068", flower="#ff8fb0"),
        windows_lit=False, lamp_on=False, glow="#ffcf70", water=("#ffffff", "#cfe0f8", "#8fa6de"),
        smoke="#ffffff", flowers=["#ffb4c8", "#fff2b0", "#ffffff"], leaves_fall=("#ffc4d4", "#fff0f4"),
        birds="#6f6f9e", butterflies=False, fireflies=False, grid_fx="sheen", sheen="#fff4ea", bloom_amt=.35,
    ),
    "noon": dict(
        sky=["#4a78cc", "#5f8ed8", "#78a6e2", "#96bcea", "#bcd4ef", "#e2edf7"], bloom="#94c2f2", bloom_k=.3,
        horizon=None, bank_alpha=.85, light=(.55, -.75, .45), orb=("sun", 354, 32, 9), orb_core="#ffffff", orb_glow="#fff2c8",
        stars=False, milky=False, shooting=False, rays=False, streaks=False,
        cloud=("#ffffff", "#c2d0ea", "#9fb2d8"), cloud_alpha=.95,
        sea=("#ffffff", "#e6eefa", "#c2d2ec", "#a2b6dc"), haze="#d8e8f8",
        rock=("#d2b494", "#9a7c64", "#634c42", "#382a2c"), rim=None, cool=None, bounce="#c4d2ea",
        block=["#86705e", "#957d68", "#a88f78"], mortar="#735a48", levels=GH_LIGHT,
        grass=("#d2e2a4", "#9cc27a", "#679a5c", "#3a6a44"),
        leaves=("#c6dd96", "#7aa863", "#3f6e4c", "#22413a"), trunk=("#a07452", "#4a3226"),
        house=dict(wall="#bba88e", wall_lit="#fbf3e4", roof="#b4523a", roof_lit="#dc7a52", trim="#4e3c32",
                   glass="#9ccaee", door="#74503a", stone="#a49c94", base="#6a5a4e", flower="#ff7aa0"),
        windows_lit=False, lamp_on=False, glow="#ffcf70", water=("#ffffff", "#bfe2ff", "#6aaae6"),
        smoke=None, flowers=["#ffa6c0", "#fff07a", "#ffffff", "#c2b4ff"], leaves_fall=None,
        birds="#3d4f7c", butterflies=True, fireflies=False, grid_fx="sheen", sheen="#ffffff", bloom_amt=.25,
    ),
    "evening": dict(
        sky=["#272259", "#4a3380", "#81488f", "#c25d8f", "#ef8384", "#ffb27a"], bloom="#d0688e", bloom_k=.35,
        horizon=None, bank_alpha=.85, light=(.85, -.2, .5), orb=("sun", 396, 158, 14), orb_core="#fff2c8", orb_glow="#ff9468",
        stars=True, milky=False, shooting=False, rays=False, streaks=True,
        cloud=("#ffc69e", "#87508a", "#5e3a74"), cloud_alpha=.9,
        sea=("#ffd4a8", "#ea96a2", "#a95f95", "#734685"), haze="#e88c98",
        rock=("#f2a084", "#8c5378", "#4a2f5a", "#22163a"), rim="#ffb08a", cool="#6a5aa8", bounce="#c07094",
        block=["#4a3460", "#56406e", "#66507e"], mortar="#2e2044", levels=GH_DARK,
        grass=("#f2c87c", "#9aa064", "#4e7a62", "#2c4a48"),
        leaves=("#ffb27a", "#6f8a6a", "#2f5a5a", "#1c2f40"), trunk=("#c07a6a", "#3a2440"),
        house=dict(wall="#5e4a78", wall_lit="#ffb894", roof="#4a3266", roof_lit="#e0866e", trim="#2a1d38",
                   glass="#ffd27a", door="#3e2a50", stone="#5a4668", base="#2a1d38", flower="#ffa8bc"),
        windows_lit=True, lamp_on=True, glow="#ffa860", water=("#ffd2b8", "#c9a8d8", "#8c74b4"),
        smoke="#d8aac4", flowers=["#ffd27a", "#ffa8bc"], leaves_fall=("#ffb36e", "#ffd9a0"),
        birds=None, butterflies=False, fireflies=False, grid_fx="sheen", sheen="#ffd9b0", bloom_amt=.5,
    ),
}


# ---------------------------------------------------------------- background

def background(p):
    L = Layer()
    Y, X = L.Y, L.X
    t = Y / H + .05 * (fbm(H, W, [60, 30], 3) - .5)
    L.rgb[:] = ramp(p["sky"], t)
    L.a[:] = 1
    bloom = fbm(H, W, [90, 45, 22], 5)                       # wet-in-wet blooms
    L.glaze(smooth(.5, .75, bloom), col(p["bloom"]), p["bloom_k"])
    L.light(smooth(.55, .8, fbm(H, W, [70, 35], 9)) * .25, col(p["bloom"]))
    streak = fbm(H, W, [6, 3], 11, stretch=9)               # long horizontal brush strokes
    L.rgb *= (1 + .05 * (streak - .5))[..., None]

    if p["milky"]:
        band = Y - (6 + .2 * X)
        dust = fbm(H, W, [14, 7, 3], 21)
        L.light(np.exp(-(band / 12) ** 2) * smooth(.4, .8, dust) * .22, col("#9aa4ff"))
    cr = rng("clouds", p["orb"][1], p["orb"][2])            # each scene gets its own sky
    for cx_, cy_, w, h, seed in ((120, 120, 90, 14, 41), (290, 108, 70, 11, 42), (20, 96, 60, 10, 43)):
        cloud(L, p, cx_ + cr.uniform(-25, 25), cy_, w * cr.uniform(.8, 1.2), h, seed + cr.randint(0, 50), .55)
    for cx_, cy_, w, h, seed in ((70, 46, 70, 24, 51), (212, 26, 46, 15, 52), (300, 66, 58, 19, 53)):
        cloud(L, p, cx_ + cr.uniform(-20, 20), cy_ + cr.uniform(-6, 6), w * cr.uniform(.8, 1.2), h, seed + cr.randint(0, 50), .1)
    bank = 30 * (fbm(1, W, [40, 20, 9], 29)[0] - .5)        # distant cloud bank dissolving into haze
    field = Y - (SEA_TOP - 4 + bank[None, :])
    wash(L, field * .7, ramp([p["haze"], p["sea"][2]], smooth(SEA_TOP - 20, H, Y)), soft=3, rim=.05, seed=31, alpha=p["bank_alpha"])
    if p["horizon"]:                                         # first light before sunrise: teal above, dusty rose below
        m = smooth(98, 138, Y) * smooth(190, 160, Y) * smooth(330, 10, X)
        L.paint(m * .5, ramp(["#2f5a6a", p["horizon"]], smooth(112, 166, Y)))

    kind, cx, cy, r = p["orb"]
    d = np.hypot(X - cx, Y - cy)
    if kind == "moon":                                       # halo hugs the lit limb, so it reads as a crescent
        out = np.maximum(d - r, 0)
        facing = np.clip(((X - cx) * -.8 + (Y - cy) * .6) / (d + 1e-3), 0, 1) ** 1.5
        L.light((np.exp(-(out / (r * .9)) ** 2) * .4 + np.exp(-(out / (r * 3.5)) ** 2) * .12) * facing * (d > r - .5), col(p["orb_glow"]))
    else:
        L.light(np.exp(-(d / (r * 3.2)) ** 2) * .7 + np.exp(-(d / (r * 8)) ** 2) * .22, col(p["orb_glow"]))
    disc = smooth(r + .8, r - .8, d)
    if kind == "moon":
        disc = disc * (1 - smooth(r - .4, r - 1.6, np.hypot(X - cx - 5, Y - cy + 3.5)))
    L.paint(disc, col(p["orb_core"]) * (1 - .06 * (vnoise(H, W, 2, 2, 13) - .5))[..., None])
    if kind == "moon":
        L.glaze(disc * smooth(.55, .7, vnoise(H, W, 3, 3, 17)), col("#c8bfa0"), .6)
    if p["rays"]:
        ang = np.arctan2(Y - cy, X - cx)
        rays = sum(np.exp(-((ang - math.radians(a)) / .028) ** 2) for a in (-58, -44, -31, -20, -11))
        L.light(rays * smooth(0, 60, d) * np.exp(-d / 320) * .22, col("#fff2dc"))
    if p["streaks"]:
        for y0, x0, s_ in ((160, 250, .3), (166, 290, .25), (153, 210, .16)):
            L.light(np.exp(-((Y - y0) / .9) ** 2) * smooth(x0, x0 + 40, X) * s_, col(p["orb_glow"]))
    return L


def cloud(L, p, cx, cy, w, h, seed, depth):
    """A cumulus with a flat base, wind-torn top and pigment pooled along its edge."""
    r = rng("cloud", seed)
    Y, X = L.Y, L.X
    F = np.zeros_like(Y)
    lobes = [(cx, cy, w * .5, h * .3, 1.0)]
    for i in range(r.randint(3, 5)):
        t = (i + .5) / 4
        lobes.append((cx - w * .4 + t * w * .8 + r.uniform(-4, 4), cy - h * r.uniform(.35, .65),
                      w * r.uniform(.16, .26), h * r.uniform(.32, .45), r.uniform(.85, 1.05)))
    for x0, y0, rx, ry, s in lobes:
        F = np.maximum(F, s * np.exp(-(((X - x0) / rx) ** 2 + ((Y - y0) / ry) ** 2)))
    F = F + .28 * (fbm(L.h, L.w, [9, 4, 2], seed) - .5)
    F = F * (smooth(cy + h * .28, cy + h * .02, Y) * .6 + .4)  # flatter base
    field = (F - .42) * 22
    lit, shade, deep = (col(c) for c in p["cloud"])
    vert = smooth(cy - h * .9, cy + h * .25, Y)
    side = (X - cx) / w * -p["light"][0]
    tone = np.clip(vert * .85 + side * .35 + .25 * (fbm(L.h, L.w, [5, 3], seed + 1) - .5), 0, 1)
    color = lit * (1 - tone[..., None]) + shade * tone[..., None]
    color = color * (1 - depth) + L.rgb * depth
    wash(L, field, color, soft=.9, rim=.16, rim_w=3, seed=seed, alpha=p["cloud_alpha"])


# ---------------------------------------------------------------- cloud sea

def cloud_sea(p):
    """Big billows behind, small ones cresting in front, cauliflower tops; lit in flat clusters. Periodic in x."""
    h = H - SEA_TOP
    L = Layer(W, h)
    Y, X = L.Y, L.X
    r = rng("sea")
    noise = fbm(h, W, [10, 5, 2.5], 61, wrap=True)
    fine = fbm(h, W, [3, 1.5], 62, wrap=True)
    height = np.full((h, W), -1.0, np.float32)
    base = SEA_Y - SEA_TOP

    def dome(cx, cy, rx, ry, lift):
        dx = ((X - cx + W / 2) % W) - W / 2
        q = (dx / rx) ** 2 + ((Y - cy) / ry) ** 2
        return np.where(q <= 1, ry * np.sqrt(np.clip(1 - q, 0, 1)) + lift, -1)

    for n, rxr, ryr, y0, jitter, lift, bumps in ((4, (42, 60), (10, 14), base + 2, 4, 0.0, True),
                                                 (6, (18, 28), (7, 10), base + 12, 3, 1.0, True),
                                                 (9, (9, 14), (5, 7), base + 21, 2, 2.0, False)):
        for i in range(n):
            cx, cy = (i + r.uniform(-.3, .3)) * W / n, y0 + r.uniform(-jitter, jitter)
            rx, ry = r.uniform(*rxr), r.uniform(*ryr)
            height = np.maximum(height, dome(cx, cy, rx, ry, lift))
            if bumps:                                        # cauliflower knobs along the upper rim
                for _ in range(r.randint(2, 3)):
                    a = r.uniform(math.radians(-160), math.radians(-20))
                    br = r.uniform(2.5, 4.5)
                    height = np.maximum(height, dome(cx + rx * .82 * math.cos(a), cy + ry * .82 * math.sin(a), br * 1.25, br, lift + ry * .4))
    lobe_mask = np.zeros((h, W), bool)
    for cx in (r.uniform(20, 60), r.uniform(150, 200), r.uniform(270, 320)):   # a few big crests rising out of the bank
        rx, ry = r.uniform(16, 28), r.uniform(10, 14)
        cy = base + 2 - r.uniform(2, 5)
        lobe = dome(cx, cy, rx, ry, 3.0)
        lobe_mask |= lobe > 0
        height = np.maximum(height, lobe)
        for _ in range(2):
            a = r.uniform(math.radians(-150), math.radians(-30))
            br = r.uniform(4, 6)
            knob = dome(cx + rx * .75 * math.cos(a), cy + ry * .75 * math.sin(a), br * 1.3, br, 3 + ry * .45)
            lobe_mask |= knob > 0
            height = np.maximum(height, knob)
    overhang = np.roll(lobe_mask, 2, axis=0) & ~lobe_mask      # just below each crest
    inside = np.maximum.accumulate(height > 0, axis=0).astype(np.float32)
    hs = np.where(height > 0, height, 0) + .8 * (noise - .5)
    wrap3 = np.concatenate([hs, hs, hs], 1)
    hb = blur(wrap3, 2)[:, W:2 * W]
    gy, gx = np.gradient(hb)
    nrm = np.stack([-gx, -gy, np.full_like(gx, .8)], -1)
    nrm /= np.linalg.norm(nrm, axis=-1, keepdims=True)
    lv = np.array([p["light"][0] * .5, -.85, .5], np.float32)
    lv /= np.linalg.norm(lv)
    lam = (nrm @ lv + .4) / 1.4
    crevice = np.clip((blur(wrap3, 4)[:, W:2 * W] - hs) / 3, 0, 1)
    tone = .95 - lam * .95 + crevice * .3 + .2 * (Y / h)
    tone -= .22 * smooth(.35, .7, nrm[..., 1])                      # bounce light on the undersides
    top_y = np.argmax(height > 0, axis=0).astype(np.float32)          # first covered row in each column
    below_top = Y - top_y[None, :]
    tone = bands(tone, 6, fine, .06)
    mist = np.where(below_top > 18, .72, .5)                           # bodies settle into two flat values
    tone = np.where(below_top > 7, mist, tone)
    tone = np.where(overhang & (below_top > 1), np.minimum(tone + .2, 1), tone)  # shade under each crest
    tone = np.where(below_top < 1, np.minimum(tone, .08), tone)        # a pale rim along the crest
    L.rgb = ramp(list(p["sea"]), tone * .92)
    L.a = inside
    return L


# ---------------------------------------------------------------- island

def plateau_back(x):
    """Back edge of the grass plateau: rounded ends, a couple of soft mounds."""
    end = 24
    d = np.minimum(x - FL, FR - x)
    k = np.where(d >= end, 1.0, np.sqrt(np.clip(1 - ((end - d) / end) ** 2, 0, 1)))
    mounds = 4.5 * np.exp(-((x - (FL + 62)) / 30) ** 2) + 3 * np.exp(-((x - (FL + 222)) / 24) ** 2)
    return TOP - (DEPTH * k + (.8 * np.sin(x / 7.0) + mounds) * k)


def fall_left(y):
    """Left edge of the waterfall: it leaves the lip and curves outward as it drops."""
    return FR + 1 + 3.5 * (1 - np.exp(-np.maximum(y - (TOP - 2), 0) / 5))


def fall_width(y):
    return 5 + np.clip((y - TOP) / 15, 0, 5)


def island(p):
    L = Layer()
    Y, X = L.Y, L.X
    lx = p["light"][0]
    r = rng("island")
    xs = np.arange(W, dtype=np.float32) + .5
    inside_x = (xs >= FL) & (xs <= FR)
    mid = (FL + FR) / 2

    # --- underside: an uneven inverted cone with two tips and hanging spurs
    u = np.clip(np.abs(xs - mid) / ((FR - FL) / 2), 0, 1)
    prof = 16 * (1 - u ** 1.3) ** .9 + 24 * np.exp(-((xs - (mid - 28)) / 40) ** 2) + 15 * np.exp(-((xs - (mid + 64)) / 24) ** 2)
    bottom = LEDGE + prof + 5 * (fbm(1, W, [24, 9, 4], 71)[0] - .5)
    for _ in range(12):
        sx = r.uniform(FL + 20, FR - 20)
        bottom = bottom + r.uniform(3, 8) * (1 - u[int(sx)]) ** .5 * np.exp(-((xs - sx) / r.uniform(1.4, 2.6)) ** 2)
    bottom = bottom + 4                                       # a band of rock below the blocks
    corner = np.clip(5 - (Y - TOP), 0, 5)                    # chamfered top corners
    wob_l, wob_r = (1.3 * (fbm(H, 1, [8, 4], s_)[:, :1] - .5) for s_ in (78, 79))
    left_edge, right_edge = FL + corner + wob_l, FR - corner - wob_r
    field = np.minimum.reduce([bottom[None, :] - Y, Y - (TOP + 1), X - left_edge + 1, right_edge - X + 1])
    hi, lit, dark, deep = p["rock"]
    depth_t = np.clip((Y - TOP) / (bottom[None, :] - TOP + 1e-3), 0, 1)
    wobble = fbm(H, W, [9, 4], 73)
    tone = depth_t * .95 - .15 * lx * (X - mid) / ((FR - FL) / 2)
    tone = bands(tone, 4, wobble, .18)
    seam = ((depth_t * 3 + (wobble - .5) * .5) % 1) < .07     # strata lines following the cone
    tone = np.where(seam, np.minimum(tone + .34, 1), tone)
    rock = ramp([hi, lit, dark, deep], tone * .95 + .02)
    for i in range(6):                                       # a few chunky cracks
        cx0 = r.uniform(FL + 30, FR - 30)
        pts, y_ = [(cx0, LEDGE + 1)], LEDGE + 1
        for _ in range(4):
            y_ += r.uniform(3, 6)
            pts.append((pts[-1][0] + r.uniform(-3, 3), y_))
        cd, _ = segments_dist(X, Y, pts)
        rock = np.where((cd < .7)[..., None] & (Y < bottom[None, :] - 3)[..., None], col(deep), rock)
    near_bottom = (field < 2.6) & (field > 0) & (Y > LEDGE + 2)
    rock = np.where(near_bottom[..., None], rock * .35 + col(p["bounce"]) * .65, rock)
    if p["rim"]:                                             # the lit side of the island catches the light
        lit_d = (right_edge - X) if lx > 0 else (X - left_edge)
        k = np.exp(-np.maximum(lit_d, 0) / 1.8)[..., None] * .7
        rock = rock * (1 - k) + col(p["rim"]) * k
    wash(L, field, rock, soft=.45, rim=.12, rim_w=2, grain=.05, seed=77)
    if p["cool"]:                                            # and the far side cools off
        L.glaze(smooth(mid, FL, X) * (field > 0), col(p["cool"]), .35)

    # --- grass plateau seen from slightly above, spilling over the lip
    back = plateau_back(xs)
    gfield = np.minimum(Y - back[None, :], TOP + 2.5 - Y)
    front_round = np.clip(5 - (TOP - Y), 0, 5) * .8          # rounded front corners of the plateau
    gfield = np.where(inside_x[None, :], np.minimum.reduce([gfield, X - FL - front_round, FR - front_round - X]), -5)
    drape = 2 + 6 * fbm(H, 1, [5, 2], 80)[:, :1]             # grass spilling down the sides
    side_grass = ((np.abs(X - left_edge) < 1.6) | (np.abs(X - right_edge) < 1.6)) & (Y > TOP - 1) & (Y < TOP + drape)
    drips = (fbm(1, W, [3, 1.5], 81)[0] - .5) * 8
    lip = inside_x[None, :] & (Y > TOP) & (Y < TOP + 2.5 + np.maximum(drips, 0)[None, :])
    gfield = np.maximum(gfield, np.where(lip | side_grass, .6, -5))
    gl, gm, gd, gx = p["grass"]
    gtone = np.clip((Y - back[None, :]) / (TOP - back[None, :] + 1e-3), 0, 1)
    patches = fbm(H, W, [10, 5], 83)
    blades = fbm(H, W, [1.2, .8], 85, stretch=.35)
    tone = .12 + gtone * .45 + .3 * (patches - .5) + .25 * (blades - .5) + .45 * smooth(TOP - .5, TOP + 2.5, Y)
    wash(L, gfield, ramp([gl, gm, gd, gx], np.clip(tone, 0, 1)), soft=.45, rim=.1, rim_w=1.5, seed=87)
    reach = 6 + 10 * abs(lx)                                 # low sun, long shadows
    for sx, sy, srx, sry in ((TREE_X - lx * reach, TOP - 7, 16 + reach, 3.2), (HOUSE_X + 14 - lx * reach, TOP - 3.5, 16 + reach * .6, 3),
                             (LAMP_X - lx * reach * .5, TOP - 2.5, 3 + reach * .4, 1)):
        L.glaze(np.exp(-(((X - sx) / srx) ** 2 + ((Y - sy) / sry) ** 2) * 2) * (gfield > 0), col(gx), .6)
    fr = rng("flowers")
    for i in range(22):
        fx_ = fr.choice((fr.uniform(FL + 6, TREE_X - 22), fr.uniform(TREE_X + 26, LAMP_X - 6), fr.uniform(HOUSE_X + 40, FR - 52)))
        fy = fr.uniform(TOP - DEPTH + 4, TOP - 1)
        L.paint(np.exp(-(((X - fx_) / .7) ** 2 + ((Y - fy) / .6) ** 2) * 2), col(p["flowers"][i % len(p["flowers"])]))

    # --- a stream with dark banks that widens toward the edge
    wl, wm, wd = (col(c) for c in p["water"])
    sd, st = segments_dist(X, Y, [(FR - 52, TOP - 11), (FR - 41, TOP - 8.5), (FR - 30, TOP - 9), (FR - 19, TOP - 6),
                                  (FR - 9, TOP - 3.5), (FR + 1, TOP - 1.5)])
    width = .9 + 1.5 * st
    L.paint(smooth(width + 1.3, width + .7, sd), col(gx))
    L.paint(smooth(width + .4, width - .2, sd), ramp([p["water"][2], p["water"][1]], .3 + .5 * vnoise(H, W, 2, 4, 92)))
    L.paint(smooth(width + .4, width - .2, sd) * (vnoise(H, W, 1, 2.5, 93) > .72), wl)

    for cx_, base, w, h in ((FL + 15, TOP - 1, 15, 6), (TREE_X - 34, TOP - 9, 11, 5), (FR - 26, TOP - 11, 12, 5), (FR - 60, TOP - 1, 12, 5)):
        foliage(L, p, [(cx_ - w * .25, base - h * .5, w * .32, h * .55, .95), (cx_ + w * .2, base - h * .45, w * .3, h * .5, .95),
                        (cx_, base - h * .8, w * .28, h * .5, .9)], base, seed=int(cx_))
    tree(L, p)
    house(L, p)
    lamp(L, p)

    # --- waterfall: curls off the lip, widens, three values of falling water, mist at the bottom
    xl = fall_left(Y)
    fw_ = fall_width(Y)
    fall = np.minimum.reduce([X - xl, xl + fw_ - X, Y - (TOP - 2), SEA_Y + 26 - Y])
    streak = vnoise(H, W, 10, 1.2, 91)
    across = np.clip(np.minimum(X - xl, xl + fw_ - X) / (fw_ / 2), 0, 1)
    L.paint(smooth(-.4, .4, fall), ramp([p["water"][2], p["water"][1], p["water"][0]], .08 + .4 * streak + .3 * across))
    # --- roots: a few clusters, mostly hanging straight; two curl, two leafy vines, one trails into the clouds
    hang = []
    for cluster_x in (mid - 70, mid - 20, mid + 40, mid + 95):
        for _ in range(r.randint(2, 4)):
            hang.append((cluster_x + r.uniform(-8, 8), r.uniform(4, 16), 0))
    hang += [(mid - 45, r.uniform(18, 24), 1), (mid + 70, r.uniform(16, 22), -1)]
    for sx, length, curl in hang:
        top_y = bottom[int(sx)] - 1
        bend = r.uniform(-2.5, 2.5)
        pts = [(sx, top_y)] + [(sx + bend * k / 4 + r.uniform(-.8, .8), top_y + length * k / 4) for k in (1, 2, 3, 4)]
        if curl:
            pts += [(pts[-1][0] + curl * 2, pts[-1][1] + 1.5), (pts[-1][0] + curl * 3, pts[-1][1] - .5)]
        dd, t = segments_dist(X, Y, pts)
        width = .95 - .5 * t
        L.paint(smooth(width + .25, width - .25, dd), col(p["trunk"][1]))
    for sx, length in ((mid - 30, 44), (mid + 18, 22)):
        top_y = bottom[int(sx)] - 1
        pts = [(sx, top_y)] + [(sx + 2.2 * math.sin(k * .9), top_y + k * length / 6) for k in range(1, 7)]
        dd, _ = segments_dist(X, Y, pts)
        L.paint(smooth(.85, .3, dd), col(p["grass"][3]))
        for k in range(2, int(length), 4):
            vx, vy = sx + 2.2 * math.sin(k / (length / 6) * .9), top_y + k
            L.paint(smooth(1.2, .6, np.hypot(X - vx - (1.2 if k % 8 else -1.2), Y - vy)), col(p["grass"][2]))
    return L


def foliage(L, p, lobes, base, seed, detail=.24):
    """Leaf clumps (back to front) with ragged leafy rims, shaded in flat clusters: lit tops, dark undersides."""
    Y, X = L.Y, L.X
    hi_n = fbm(L.h, L.w, [3, 1.6], seed)
    tiny = fbm(L.h, L.w, [1.7, 1.0], seed + 2)
    owner = np.full(Y.shape, -1, int)
    for i, (x0, y0, rx, ry, s) in enumerate(lobes):
        f = s * np.exp(-(((X - x0) / rx) ** 2 + ((Y - y0) / ry) ** 2)) + detail * (hi_n - .5) + .16 * (tiny - .5)
        owner = np.where(f > .38, i, owner)
    owner = np.where(Y <= base + .5, owner, -1)
    valid = owner >= 0
    P = np.array(lobes, np.float32)
    o = np.clip(owner, 0, None)
    nx, ny = (X - P[o, 0]) / P[o, 2], (Y - P[o, 1]) / P[o, 3]
    nz = np.sqrt(np.clip(1 - nx * nx - ny * ny, 0, 1))
    lv = np.array(p["light"], np.float32)
    lv /= np.linalg.norm(lv)
    lam = nx * lv[0] + ny * lv[1] + nz * lv[2]
    back = 1 - o / max(1, len(lobes) - 1)
    tone = .85 - lam * .8 + .26 * back + .3 * np.clip(ny, 0, 1)
    tone += .2 * (tiny > .64) - .16 * (tiny < .34)            # leaf clusters inside each clump
    padded = np.pad(owner, 1, constant_values=-1)
    below, above = padded[2:, 1:-1], padded[:-2, 1:-1]
    away = padded[1:-1, :-2] if lv[0] > 0 else padded[1:-1, 2:]
    tone += .24 * ((below > owner) | (away > owner))          # crease where a nearer clump overlaps
    tone = np.where((below < 0) | (away < 0), tone + .2, tone)  # selective outline on the shadow side
    tone = np.where(above < 0, tone - .1, tone)                # lit top edge
    color = ramp(list(p["leaves"]), bands(tone, 4, hi_n, .1))
    L.paint(valid, color)


def tree(L, p):
    Y, X = L.Y, L.X
    tx, base = TREE_X, TOP - 7
    lx = p["light"][0]
    tl, td = (col(c) for c in p["trunk"])
    limbs = [([(tx, base + 1), (tx + 1, base - 9), (tx + 3, base - 20), (tx + 2, base - 32)], 3.4, 1.4),
             ([(tx + 1, base - 12), (tx - 8, base - 20), (tx - 16, base - 26)], 1.4, .7),
             ([(tx + 2, base - 17), (tx + 12, base - 24), (tx + 20, base - 28)], 1.3, .7),
             ([(tx + 3, base - 22), (tx - 2, base - 36)], 1.1, .6)]
    for pts, w0, w1 in limbs:
        d, t = segments_dist(X, Y, pts)
        width = w0 + (w1 - w0) * t
        if pts[0][1] > base:
            width = width + 2.2 * smooth(base - 3, base + 1, Y)
        side = np.clip((X - pts[0][0]) * (1 if lx > 0 else -1) / 3, -1, 1)
        L.paint(smooth(width + .4, width - .4, d), td + (tl - td) * (.5 + .5 * side)[..., None])
    lobes = [(tx + 14, base - 42, 12, 8, 1.0), (tx - 12, base - 40, 15, 10, 1.0), (tx + 2, base - 51, 9, 6, .95),
             (tx - 25, base - 25, 10, 8, 1.0), (tx + 25, base - 28, 16, 10, 1.0), (tx - 3, base - 31, 19, 12, 1.0),
             (tx + 9, base - 17, 11, 7, 1.0), (tx - 17, base - 15, 8, 6, .95)]
    foliage(L, p, lobes, base - 10, seed=101, detail=.3)


def house(L, p):
    """A low stone-footed cottage in three-quarter view: gable to the front, long side receding."""
    Y, X = L.Y, L.X
    hp = p["house"]
    hx, hb = HOUSE_X, TOP - 5
    fw, fh, rh, o = 15, 10, 8, 2
    ox, oy = 20, -5
    slope = oy / ox
    lit_front = p["light"][0] < 0
    front_c = col(hp["wall_lit"] if lit_front else hp["wall"])
    side_c = col(hp["wall"] if lit_front else hp["wall_lit"])
    tex = 1 + .05 * (vnoise(H, W, 1, 3, 111) - .5)
    rect = lambda x0, y0, x1, y1: poly_mask(X, Y, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)])

    A, B = (hx + fw, hb - fh), (hx + fw, hb + 1)
    side = poly_mask(X, Y, [A, B, (B[0] + ox, B[1] + oy), (A[0] + ox, A[1] + oy)])
    planks = 1 - .07 * (((Y - (X - A[0]) * slope) % 3) < 1)
    L.paint(side, side_c * (tex * planks)[..., None])
    L.paint(side * ((Y - (X - A[0]) * slope) > hb - .2), col(hp["base"]))
    windows = []
    glass = col(hp["glass"]) * (1 if p["windows_lit"] else .9)
    for i0 in (5, 12):
        y0 = A[1] + 2.5 + i0 * slope
        quad = lambda a, b, c, d: poly_mask(X, Y, [(A[0] + i0 + a, y0 + b + a * slope), (A[0] + i0 + c, y0 + b + c * slope),
                                                   (A[0] + i0 + c, y0 + d + c * slope), (A[0] + i0 + a, y0 + d + a * slope)])
        L.paint(quad(-.5, -.5, 3.5, 4.5), col(hp["trim"]))
        L.paint(quad(.5, .5, 2.5, 3.5), glass)
        windows.append((A[0] + i0 + 1.5, y0 + 2 + 1.5 * slope))

    P = (hx + fw / 2, hb - fh - rh)
    E = (hx + fw + o, hb - fh + 1)
    roof = poly_mask(X, Y, [P, E, (E[0] + ox, E[1] + oy), (P[0] + ox, P[1] + oy)])
    ax, ay = E[0] - P[0], E[1] - P[1]
    s = ((X - P[0]) * oy - (Y - P[1]) * ox) / (ax * oy - ay * ox)
    courses = 1 - .14 * ((s * 7) % 1 < .3)
    L.paint(roof, col(hp["roof_lit"] if not lit_front else hp["roof"]) * (courses * tex)[..., None])
    L.paint(roof * (s < .12), col(hp["roof_lit"]))
    L.paint(roof * (s > .9), col(hp["roof"]) * .75)          # eave in shadow

    front = poly_mask(X, Y, [(hx, hb + 1), (hx, hb - fh), P, (hx + fw, hb - fh), (hx + fw, hb + 1)])
    L.paint(front, front_c * tex[..., None])
    bd, _ = segments_dist(X, Y, [(hx - o, hb - fh + 1), P, (hx + fw + o, hb - fh + 1)])
    L.paint(smooth(1.1, .6, bd) * (Y < hb - fh + 1.5), col(hp["roof"]) * .8)
    L.paint(rect(hx - .5, hb, hx + fw + .5, hb + 1), col(hp["base"]))
    L.paint(rect(hx + 8.5, hb - 6.5, hx + 12.5, hb + .5), col(hp["trim"]))     # door and frame
    L.paint(rect(hx + 9.5, hb - 5.5, hx + 11.5, hb), col(hp["door"]))
    L.paint(rect(hx + 1.5, hb - 7.5, hx + 6.5, hb - 2.5), col(hp["trim"]))     # window and frame
    L.paint(rect(hx + 2.5, hb - 6.5, hx + 5.5, hb - 3.5), glass)
    L.paint(rect(hx + 1, hb - 2.5, hx + 7, hb - 1.5), col(hp["trim"]))         # flower box
    for fxp in (hx + 2, hx + 4, hx + 6):
        L.paint(rect(fxp - .5, hb - 3.5, fxp + .5, hb - 2.5), col(hp["flower"]))
    cx_, cy_ = P[0] + .7 * ox + .35 * ax, P[1] + .7 * oy + .35 * ay
    L.paint(rect(cx_ - 1.5, cy_ - 6, cx_ + 1.5, cy_ + 1), col(hp["stone"]))
    L.paint(rect(cx_ - 2, cy_ - 7, cx_ + 2, cy_ - 6), col(hp["trim"]))
    house.chimney = (cx_, cy_ - 9)
    house.windows = [(hx + 4, hb - 5)] + windows


def lamp(L, p):
    Y, X = L.Y, L.X
    lx, base = LAMP_X, TOP - 3
    trim = col(p["house"]["trim"])
    rect = lambda x0, y0, x1, y1: poly_mask(X, Y, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)])
    L.paint(rect(lx - .5, base - 12, lx + .5, base + 1), trim)
    L.paint(rect(lx - 1.5, base, lx + 1.5, base + 1), trim)
    L.paint(rect(lx - 2, base - 17, lx + 2, base - 12), trim)
    L.paint(rect(lx - 1, base - 16, lx + 1, base - 13), col("#fff1c4") if p["lamp_on"] else col("#e6e0d0"))
    L.paint(rect(lx - 2.5, base - 18, lx + 2.5, base - 17), trim)
    L.paint(rect(lx - .5, base - 19, lx + .5, base - 18), trim)
    lamp.head = (lx, base - 14.5)


def islet(p, w, seed, haze=0.0):
    h = 30
    L = Layer(w + 8, h)
    Y, X = L.Y, L.X
    c = (w + 8) / 2
    u = np.clip(np.abs(X[0] - c) / (w / 2), 0, 1)
    bottom = (7 + (h - 16) * (1 - u ** 1.2) + 7 * np.exp(-((X[0] - c + w * .12) / (w * .14)) ** 2)
              + 4 * np.exp(-((X[0] - c - w * .22) / (w * .09)) ** 2) + 3 * (fbm(1, w + 8, [5, 2], seed)[0] - .5))
    field = np.minimum.reduce([bottom[None, :] - Y, Y - 5, w / 2 - np.abs(X - c)])
    rock = ramp(list(p["rock"]), np.clip((Y - 5) / h * 1.5 + .2 * (fbm(h, w + 8, [3, 1.5], seed + 1) - .5), 0, 1))
    wash(L, field, rock, soft=.45, rim=.2, rim_w=1.5, seed=seed)
    grass = np.minimum.reduce([Y - 4, 6.5 - Y, w / 2 - np.abs(X - c)])
    wash(L, grass * 2, ramp(list(p["grass"]), (Y - 4) / 4), soft=.45, seed=seed + 2)
    foliage(L, p, [(c - w * .22, 2.5, w * .16, 3, 1.0), (c - w * .05, 1.5, w * .14, 3, 1.0), (c + w * .08, 3, w * .1, 2.2, .95)], 4.5, seed + 4)
    if haze:
        L.rgb = L.rgb * (1 - haze) + col(p["haze"]) * haze
    return L


# ---------------------------------------------------------------- pixelation

BAYER4 = (np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]], np.float32) + .5) / 16 - .5


def pixelate(L, colors=40, spread=.09, keep=()):
    """Reduce a painted layer to a small palette with ordered dithering; alpha is dithered too."""
    rgb = np.clip(L.rgb, 0, 1)
    opaque = L.a > .02
    img = Image.fromarray((rgb[opaque][None, :, :] * 255).astype(np.uint8))
    pal = np.array(img.quantize(colors=colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).getpalette()[:colors * 3],
                   np.float32).reshape(-1, 3) / 255
    if keep:                                                 # small but important colours must survive
        pal = np.concatenate([pal, np.stack([col(c) for c in keep])])
    b = np.tile(BAYER4, (L.h // 4 + 1, L.w // 4 + 1))[:L.h, :L.w]
    q = rgb + b[..., None] * spread
    wts = np.array([.9, 1.2, .7], np.float32)
    idx = np.zeros((L.h, L.w), int)
    for y0 in range(0, L.h, 50):                            # chunked to keep memory small
        d = (((q[y0:y0 + 50, :, None, :] - pal[None, None]) * wts) ** 2).sum(-1)
        idx[y0:y0 + 50] = d.argmin(-1)
    out = np.zeros((L.h, L.w, 4), np.uint8)
    out[..., :3] = (pal[idx] * 255 + .5).astype(np.uint8)
    out[..., 3] = np.where(L.a > .5, 255, 0)
    return out


def png_uri(rgba):
    flat = rgba.reshape(-1, 4).copy()
    flat[flat[:, 3] == 0] = 0
    uniq, inv = np.unique(flat, axis=0, return_inverse=True)
    buf = io.BytesIO()
    if len(uniq) <= 256:
        img = Image.frombytes("P", (rgba.shape[1], rgba.shape[0]), inv.reshape(-1).astype(np.uint8).tobytes())
        img.putpalette(uniq[:, :3].flatten().tolist())
        img.save(buf, "PNG", optimize=True, transparency=bytes(uniq[:, 3].tolist()))
    else:
        Image.fromarray(rgba).save(buf, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def image(uri, x, y, w, h):
    return (f'<image href="{uri}" x="{x}" y="{y}" width="{w}" height="{h}" image-rendering="optimizeSpeed" '
            f'style="image-rendering:crisp-edges;image-rendering:pixelated"/>')


# ---------------------------------------------------------------- crisp blocks (the contribution graph)

def mix(a, b, t):
    pa, pb = col(a), col(b)
    return hexs((pa + (pb - pa) * t) * 255 + .5)


def draw_blocks(rgba, p, levels):
    """Bevelled blocks set straight into the rock: stones for empty days, moss for busy ones."""
    lit_left = p["light"][0] < 0
    cells = []
    r = rng("blocks")
    u8 = lambda c: (col(c) * 255 + .5).astype(np.uint8)
    rgba[GY:GY + GRID_H, GX:GX + GRID_W, :3] = u8(p["mortar"])
    rgba[GY:GY + GRID_H, GX:GX + GRID_W, 3] = 255
    for wi, week in enumerate(levels):
        toward = (wi / 52 - .5) * (-1 if lit_left else 1)      # columns nearer the light are a touch brighter
        for di, level in enumerate(week):
            if level is None:
                continue
            x, y = GX + wi * PITCH, GY + di * PITCH
            if level == 0:
                lo, base, hi = p["block"]
                j = r.random()
                base = mix(base, lo, .4) if j < .3 else mix(base, hi, .35) if j > .75 else base
                base = mix(base, hi, .3 * toward) if toward > 0 else mix(base, lo, -.3 * toward)
                hi, lo = mix(base, hi, .5), mix(base, lo, .5)
            else:
                base = p["levels"][level - 1]
                base = mix(base, "#ffffff", .08 * toward) if toward > 0 else mix(base, "#000000", -.06 * toward)
                hi, lo = mix(base, "#ffffff", .32), mix(base, p["mortar"], .35)
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
                    rgba[y + dy, x + dx, :3] = u8(c)
            if level == 0 and r.random() < .1:
                rgba[y + 2, x + 1 + r.randint(0, 1), :3] = u8(lo)
            if level >= 3 and r.random() < .6:
                rgba[y - 1, x + r.randint(0, CELL - 1), :3] = u8(mix(base, "#ffffff", .45))
            if di == 0 and r.random() < .3:                       # moss creeping over the top row
                start = r.randint(0, CELL - 1)
                for k in range(r.randint(1, 3)):
                    if start + k < CELL:
                        rgba[y, x + start + k, :3] = u8(p["grass"][2])
                if r.random() < .4:
                    rgba[y + 1, x + start, :3] = u8(p["grass"][3])
            cells.append((x, y, level))
    for _ in range(4):                                           # vines hanging across the blocks
        x = GX + r.randint(2, 50) * PITCH + r.choice((-1, 0, 2))
        length = r.randint(9, 16)
        for k in range(length):
            xx = x + (1 if (k // 4) % 2 else 0)
            rgba[GY - 2 + k, xx, :3] = u8(p["grass"][3])
            if k % 3 == 1:
                rgba[GY - 2 + k, xx + (1 if k % 2 else -1), :3] = u8(p["grass"][2])
    return cells


# ---------------------------------------------------------------- animated overlays (crisp pixels)

class Px:
    def __init__(self):
        self.p = {}

    def set(self, x, y, c):
        self.p[(int(x), int(y))] = c

    def svg(self):
        by = {}
        for (x, y), c in self.p.items():
            by.setdefault(c, []).append(f"M{x} {y}h1v1h-1z")
        return "".join(f'<path fill="{c}" d="{"".join(d)}"/>' for c, d in by.items())


def g(content, cls=None, style=None, **attrs):
    a = "".join(f' {k.replace("_", "-")}="{v}"' for k, v in attrs.items())
    if cls:
        a += f' class="{cls}"'
    if style:
        a += f' style="{style}"'
    return f"<g{a}>{content}</g>"


def dot(x, y, c, w=1, h=1):
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{c}"/>'


def halo(cx, cy, c, rings):
    out = []
    for rad, op in rings:
        px = Px()
        for y in range(int(cy - rad) - 1, int(cy + rad) + 2):
            for x in range(int(cx - rad) - 1, int(cx + rad) + 2):
                if (x + .5 - cx) ** 2 + (y + .5 - cy) ** 2 <= rad * rad:
                    px.set(x, y, c)
        out.append(g(px.svg(), opacity=op))
    return "".join(out)


CSS = """
.tw{animation:tw 3s steps(1,end) infinite}
@keyframes tw{0%,100%{opacity:1}50%{opacity:.2}}
.pulse{animation:pulse 5s ease-in-out infinite}
@keyframes pulse{0%,100%{opacity:.45}50%{opacity:1}}
.bob{animation:bob 3.4s steps(1,end) infinite}
@keyframes bob{0%,100%{transform:translateY(0)}50%{transform:translateY(-1px)}}
.left{animation:left 300s steps(420) infinite}
@keyframes left{to{transform:translateX(-420px)}}
.fa{animation:fa 1.2s steps(1,end) infinite}
.fb{animation:fa 1.2s steps(1,end) infinite;animation-delay:-.6s}
@keyframes fa{0%,49.9%{opacity:1}50%,100%{opacity:0}}
.flow{animation:flow 2.4s steps(24) infinite}
@keyframes flow{to{transform:translateY(24px)}}
.smoke{animation:smoke 6s steps(16) infinite;opacity:0}
@keyframes smoke{0%{transform:translate(0,0);opacity:0}12%{opacity:.7}100%{transform:translate(7px,-17px);opacity:0}}
.flicker{animation:flicker 2.6s steps(1,end) infinite}
@keyframes flicker{0%,100%{opacity:1}30%{opacity:.8}55%{opacity:.95}80%{opacity:.72}}
.shoot{animation:shoot 14s linear infinite;opacity:0}
@keyframes shoot{0%{transform:translate(0,0);opacity:0}1%{opacity:1}6%{transform:translate(-72px,36px);opacity:0}100%{opacity:0}}
.fly{animation:fly 80s steps(500) infinite}
@keyframes fly{from{transform:translateX(-40px)}to{transform:translateX(460px)}}
.sheen{animation:sheen 9s steps(70) infinite}
@keyframes sheen{0%{transform:translateX(0)}45%,100%{transform:translateX(330px)}}
"""


def overlays_sky(p):
    out = []
    if p["stars"]:
        r = rng("stars", p["orb"][2])
        top = 150 if p["milky"] else 50
        for _ in range(70 if p["milky"] else 22):
            x, y = r.randrange(2, W - 2), r.randrange(2, top)
            c = r.choice(["#ffffff", "#d6dcff", "#fff0d0"])
            if r.random() < .85:
                out.append(g(dot(x, y, c), cls="tw", style=f"animation-duration:{r.uniform(2, 5):.1f}s;animation-delay:-{r.uniform(0, 5):.1f}s"))
            else:
                out.append(g(dot(x, y, "#ffffff") + dot(x - 1, y, "#aab4ff") + dot(x + 1, y, "#aab4ff")
                             + dot(x, y - 1, "#aab4ff") + dot(x, y + 1, "#aab4ff"), cls="tw",
                             style=f"animation-duration:{r.uniform(3, 6):.1f}s;animation-delay:-{r.uniform(0, 6):.1f}s"))
    if p["shooting"]:
        for x, y, delay in ((300, 12, 2), (190, 8, 9)):
            s = Px()
            for k in range(9):
                c = "#ffffff" if k == 0 else "#c9d1ff" if k < 3 else "#6a70b0"
                s.set(x + k * 2, y - k, c)
                s.set(x + k * 2 + 1, y - k, c)
            out.append(g(s.svg(), cls="shoot", style=f"animation-delay:{delay}s"))
    if p["birds"]:
        up, down = Px(), Px()
        for bx, by in ((0, 0), (10, 5), (19, 1)):
            for dx, dy in ((0, 0), (4, 0), (1, 1), (3, 1), (2, 2)):
                up.set(bx + dx, by + dy, p["birds"])
            for dx in (0, 1, 3, 4):
                down.set(bx + dx, by + 1, p["birds"])
            down.set(bx + 2, by + 2, p["birds"])
        flap = g(up.svg(), cls="fa", style="animation-duration:.7s") + g(down.svg(), cls="fb", style="animation-duration:.7s;animation-delay:-.35s")
        out.append(g(g(flap, transform="translate(0,22)"), cls="fly"))
    return "".join(out)


def overlays_island(p, cells):
    out = []
    r = rng("fx")
    fx = p["grid_fx"]
    if fx == "glow":
        for x, y, level in cells:
            if level >= 2:
                out.append(g(dot(x - 1, y - 1, "#7ee787", CELL + 2, CELL + 2), cls="pulse", opacity=round(.12 + .07 * level, 2),
                             style=f"animation-duration:{r.uniform(3, 6):.1f}s;animation-delay:-{r.uniform(0, 6):.1f}s"))
    elif fx == "dew":
        for x, y, level in r.sample(cells, min(22, len(cells))):
            out.append(g(dot(x + 1, y + 1, "#ffffff"), cls="tw", style=f"animation-duration:{r.uniform(2, 4.5):.1f}s;animation-delay:-{r.uniform(0, 4):.1f}s"))
    elif fx == "sheen":
        clip = "".join(dot(x, y, "#000", CELL, CELL) for x, y, _ in cells)
        band = (f'<polygon class="sheen" points="{GX - 40},{GY - 2} {GX - 30},{GY - 2} {GX - 44},{GY + GRID_H + 2} '
                f'{GX - 54},{GY + GRID_H + 2}" fill="{p["sheen"]}" opacity=".4"/>')
        out.append(f'<clipPath id="cells">{clip}</clipPath><g clip-path="url(#cells)">{band}</g>')

    streaks = Px()
    sr = rng("streaks")
    lanes = {}
    for i in range(10):                                       # each lane gets its own irregular dashes, looping every 24px
        cycle, y_ = [], sr.randint(0, 6)
        while y_ < 24:
            length = sr.randint(3, 10)
            cycle.append((y_, length, sr.random() < .6))
            y_ += length + sr.randint(3, 9)
        lanes[i] = cycle
    for y in range(TOP - 26, SEA_Y + 30):
        xl, fw_ = float(fall_left(np.float32(y))), float(fall_width(np.float32(y)))
        for i in range(1, int(fw_) - 1):
            for y0, length, bright in lanes[i]:
                if 0 <= (y - y0) % 24 < length:
                    streaks.set(round(xl) + i, y, p["water"][0] if bright else p["water"][1])
    edge = [(float(fall_left(np.float32(y))), y) for y in range(TOP - 2, SEA_Y + 27, 3)]
    poly = " ".join(f"{x:.1f},{y}" for x, y in edge) + " " + " ".join(f"{x + float(fall_width(np.float32(y))):.1f},{y}" for x, y in reversed(edge))
    out.append(f'<clipPath id="fall"><polygon points="{poly}"/></clipPath>'
               + g(g(streaks.svg(), cls="flow", opacity=.75), clip_path="url(#fall)"))
    foam_a, foam_b = Px(), Px()                                 # foam where the stream tips over the lip
    for dx, dy in ((0, -1), (2, -2), (4, -1), (5, 0), (1, 0), (3, 1)):
        foam_a.set(FR + 1 + dx, TOP - 1 + dy, "#ffffff")
    for dx, dy in ((1, -1), (3, -2), (5, -1), (0, 0), (4, 0), (2, 1)):
        foam_b.set(FR + 1 + dx, TOP - 1 + dy, p["water"][0])
    out.append(g(foam_a.svg(), cls="fa", style="animation-duration:.7s") + g(foam_b.svg(), cls="fb", style="animation-duration:.7s;animation-delay:-.35s"))
    mx = float(fall_left(np.float32(SEA_Y))) + float(fall_width(np.float32(SEA_Y))) / 2
    out.append(g(halo(mx, SEA_Y + 2, "#ffffff", ((3, .35),)) + halo(mx, SEA_Y + 3, p["sea"][0], ((6, .45), (10, .28), (14, .14), (19, .06))),
                 cls="pulse", style="animation-duration:3.5s"))
    if p["windows_lit"]:
        out.append(g("".join(halo(x, y, p["glow"], ((2, .3), (4, .14), (7, .06))) for x, y in house.windows), cls="flicker"))
    if p["lamp_on"]:
        hx, hy = lamp.head
        out.append(g(halo(hx, hy, p["glow"], ((2.5, .4), (5, .2), (9, .09), (14, .04))), cls="flicker"))
    if p["smoke"]:
        cx_, cy_ = house.chimney
        for i in range(3):
            out.append(g(dot(round(cx_) - 1, round(cy_), p["smoke"], 2, 2) + dot(round(cx_) + 1, round(cy_) + 1, p["smoke"]),
                         cls="smoke", style=f"animation-delay:-{i * 2:.1f}s"))
    return "".join(out)


def overlays_life(p):
    out, css = [], []
    r = rng("life")
    if p["leaves_fall"]:
        direction = 1 if p["light"][0] < 0 else -1
        a_, b_ = p["leaves_fall"]
        for i in range(8):
            x, y = TREE_X + r.randint(-24, 26), r.randint(TOP - 50, TOP - 26)
            dur = r.uniform(10, 16)
            drift, fall_ = r.uniform(12, 30) * direction, (TOP - 3) - y
            css.append(f"@keyframes lf{i}{{0%{{transform:translate(0,0);opacity:0}}8%{{opacity:1}}"
                       f"35%{{transform:translate({drift * .25:.0f}px,{fall_ * .35:.0f}px)}}"
                       f"65%{{transform:translate({drift * .6:.0f}px,{fall_ * .6:.0f}px)}}"
                       f"85%{{transform:translate({drift * .8:.0f}px,{fall_ * .85:.0f}px);opacity:1}}"
                       f"100%{{transform:translate({drift:.0f}px,{fall_:.0f}px);opacity:0}}}}")
            flutter = (g(dot(x, y, a_) + dot(x + 1, y, b_), cls="fa", style="animation-duration:.9s")
                       + g(dot(x, y, b_) + dot(x, y + 1, a_), cls="fb", style="animation-duration:.9s;animation-delay:-.45s"))
            out.append(g(flutter, style=f"animation:lf{i} {dur:.1f}s steps(48) infinite;animation-delay:-{r.uniform(0, dur):.1f}s;opacity:0"))
    for kind, on, count in (("ff", p["fireflies"], 11), ("bf", p["butterflies"], 3)):
        if not on:
            continue
        for i in range(count):
            x = r.choice((r.randint(TREE_X - 30, TREE_X + 30), r.randint(TREE_X + 34, HOUSE_X - 4)))
            y = r.randint(TOP - 34, TOP - 6) if kind == "ff" else r.randint(TOP - 22, TOP - 8)
            span = 8 if kind == "ff" else 14
            pts = [(0, 0)] + [(r.randint(-span, span), r.randint(-5, 5)) for _ in range(3)] + [(0, 0)]
            css.append(f"@keyframes {kind}{i}{{" + "".join(f"{k * 25}%{{transform:translate({dx}px,{dy}px)}}" for k, (dx, dy) in enumerate(pts)) + "}")
            if kind == "ff":
                body = g(dot(x - 1, y, "#e9ff9c", 3, 1) + dot(x, y - 1, "#e9ff9c", 1, 3), opacity=.35) + dot(x, y, "#f6ffd0")
                inner = g(body, cls="tw", style=f"animation-duration:{r.uniform(1.5, 3):.1f}s;animation-delay:-{r.uniform(0, 3):.1f}s")
            else:
                c = ["#ffffff", "#fff07a", "#ffb3d0"][i % 3]
                inner = (g(dot(x - 1, y, c) + dot(x + 1, y, c) + dot(x, y + 1, c), cls="fa", style="animation-duration:.4s")
                         + g(dot(x, y, c) + dot(x, y + 1, c), cls="fb", style="animation-duration:.4s;animation-delay:-.2s"))
            dur = r.uniform(9, 16)
            out.append(g(inner, style=f"animation:{kind}{i} {dur:.1f}s steps(36) infinite;animation-delay:-{r.uniform(0, dur):.1f}s"))
    return (f"<style>{''.join(css)}</style>" if css else "") + "".join(out)


# ---------------------------------------------------------------- compose

def frame_clip():
    pts = [(0, 3), (1, 3), (1, 1), (3, 1), (3, 0)]
    path = []
    for corner in range(4):
        for x, y in pts:
            path.append([(x, y), (W - y, x), (W - x, H - y), (y, H - x)][corner])
    return '<clipPath id="frame"><polygon points="' + " ".join(f"{x},{y}" for x, y in path) + '"/></clipPath>'


def filters(p):
    amt = p["bloom_amt"]
    return f"""
<filter id="bloom" x="0" y="0" width="100%" height="100%" color-interpolation-filters="sRGB">
  <feComponentTransfer in="SourceGraphic" result="bright">
    <feFuncR type="linear" slope="3" intercept="-2.1"/><feFuncG type="linear" slope="3" intercept="-2.1"/>
    <feFuncB type="linear" slope="3" intercept="-2.1"/></feComponentTransfer>
  <feGaussianBlur in="bright" stdDeviation="3.5" result="soft"/>
  <feColorMatrix in="soft" type="matrix" values="{amt} 0 0 0 0  0 {amt} 0 0 0  0 0 {amt} 0 0  0 0 0 1 0" result="glow"/>
  <feBlend in="SourceGraphic" in2="glow" mode="screen"/>
</filter>
"""


def sea_light(p):
    """Warm light raking across the billow tops near a low sun (or the first glow before dawn)."""
    kind, cx, cy, _ = p["orb"]
    if kind == "sun" and cy > 120:
        x, c, op = cx, p["orb_glow"], .45
    elif p["horizon"]:
        x, c, op = 50, "#c8b4f0", .3
    else:
        return ""
    return (f'<radialGradient id="seaglow"><stop offset="0" stop-color="{c}" stop-opacity="1"/>'
            f'<stop offset="1" stop-color="{c}" stop-opacity="0"/></radialGradient>'
            f'<ellipse cx="{x}" cy="{SEA_Y}" rx="170" ry="26" fill="url(#seaglow)" opacity="{op}"/>')


def scene(name, levels):
    p = PAL[name]
    bg = pixelate(background(p), colors=26, spread=.03, keep=(p["orb_core"],))
    sea_uri = png_uri(pixelate(cloud_sea(p), colors=12, spread=.035))
    isl = pixelate(island(p), colors=34, spread=.06, keep=(p["house"]["glass"], p["house"]["roof_lit"], p["water"][0]))
    cells = draw_blocks(isl, p, levels)
    islets = []
    for cx, top, w, seed, haze, dur in ((36, 114, 32, 7, 0, 3.0), (392, 64, 15, 8, .45, 4.2)):
        lay = islet(p, w, seed, haze)
        islets.append(g(image(png_uri(pixelate(lay, colors=14, spread=.05)), round(cx - lay.w / 2), top - 6, lay.w, lay.h),
                        cls="bob", style=f"animation-duration:{dur}s"))
    body = (
        image(png_uri(bg), 0, 0, W, H)
        + overlays_sky(p)
        + "".join(islets)
        + g(image(png_uri(isl), 0, 0, W, H) + overlays_island(p, cells), cls="bob")
        + g(image(sea_uri, 0, SEA_TOP, W, H - SEA_TOP) + image(sea_uri, W, SEA_TOP, W, H - SEA_TOP), cls="left")
        + sea_light(p)
        + overlays_life(p)
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W * SCALE}" height="{H * SCALE}" '
        f'shape-rendering="crispEdges"><style>{CSS}</style><defs>{frame_clip()}{filters(p)}</defs>'
        f'<g clip-path="url(#frame)"><g filter="url(#bloom)">{body}</g></g></svg>\n'
    )


def current_scene(now=None):
    h = (now or datetime.now(timezone.utc) + timedelta(hours=9)).hour
    return "dawn" if h < 6 else "morning" if h < 12 else "noon" if h < 18 else "evening"


def main():
    mode, target = sys.argv[1], Path(sys.argv[2])
    levels = load_levels()
    names = [current_scene()] if mode == "now" else (sys.argv[3:] or list(PAL))
    for name in names:
        out = target if mode == "now" else target / f"{name}.svg"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(scene(name, levels), encoding="utf-8")


if __name__ == "__main__":
    main()
