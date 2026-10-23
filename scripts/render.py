"""Render four time-of-day landscapes (dawn, morning, noon, evening) into assets/.

The same quiet seascape is drawn under four lights; a workflow publishes the one
matching the current hour in Seoul.
"""
import math
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
W, H = 1200, 400
HORIZON = 286

SCENES = {
    "dawn": {
        "sky": [(0, "#060818"), (0.45, "#141640"), (0.8, "#2a2a66"), (1, "#3d3a7c")],
        "orb": (880, 92, 26), "orb_color": "#f4efdc", "orb_glow": "#8f97ff", "glow_size": 260, "crescent": True,
        "cloud_lit": "#4b4f96", "cloud_shade": "#1d1f4a", "cloud_op": 0.55,
        "far": "#22245a", "near": "#14163a", "haze": "#5a5aa8",
        "sea": [(0, "#1d1f52"), (1, "#07081c")], "shimmer": "#cfd3ff",
        "stars": 130, "sparkles": True, "birds": False,
    },
    "morning": {
        "sky": [(0, "#8db0e6"), (0.45, "#d8c3e6"), (0.78, "#f8cdd2"), (1, "#ffe2c6")],
        "orb": (330, 214, 30), "orb_color": "#fff6e6", "orb_glow": "#ffc6a6", "glow_size": 340, "crescent": False,
        "cloud_lit": "#fff4f0", "cloud_shade": "#e9b3c6", "cloud_op": 0.85,
        "far": "#c2b2db", "near": "#9b92c8", "haze": "#ffe6dc",
        "sea": [(0, "#f1cbd6"), (1, "#8e98d0")], "shimmer": "#fff3e4",
        "stars": 0, "sparkles": False, "birds": True,
    },
    "noon": {
        "sky": [(0, "#2f6fd6"), (0.5, "#6ea6ee"), (0.85, "#b9d8f8"), (1, "#e2f0fc")],
        "orb": (850, 70, 30), "orb_color": "#ffffff", "orb_glow": "#fff6d8", "glow_size": 300, "crescent": False,
        "cloud_lit": "#ffffff", "cloud_shade": "#c6d9f1", "cloud_op": 0.95,
        "far": "#a3c2e8", "near": "#6f9ad2", "haze": "#ffffff",
        "sea": [(0, "#77aeea"), (1, "#245fb6")], "shimmer": "#ffffff",
        "stars": 0, "sparkles": False, "birds": True,
    },
    "evening": {
        "sky": [(0, "#221f5c"), (0.42, "#6a4a9a"), (0.75, "#d0739a"), (1, "#ffb48a")],
        "orb": (880, 226, 34), "orb_color": "#ffe2b8", "orb_glow": "#ff8f74", "glow_size": 380, "crescent": False,
        "cloud_lit": "#ffc4a4", "cloud_shade": "#5b3f86", "cloud_op": 0.9,
        "far": "#6e4f93", "near": "#3c2e69", "haze": "#ff9f8a",
        "sea": [(0, "#8a5f9e"), (1, "#231f50")], "shimmer": "#ffd0a0",
        "stars": 40, "sparkles": False, "birds": False,
    },
}


def f(x):
    return f"{x:.1f}"


def defs(s):
    sky = "".join(f'<stop offset="{o}" stop-color="{c}"/>' for o, c in s["sky"])
    sea = "".join(f'<stop offset="{o}" stop-color="{c}"/>' for o, c in s["sea"])
    return f"""<defs>
<clipPath id="card"><rect width="{W}" height="{H}" rx="20"/></clipPath>
<linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">{sky}</linearGradient>
<linearGradient id="sea" x1="0" y1="0" x2="0" y2="1">{sea}</linearGradient>
<radialGradient id="glow"><stop offset="0" stop-color="{s["orb_glow"]}" stop-opacity=".9"/><stop offset=".3" stop-color="{s["orb_glow"]}" stop-opacity=".35"/><stop offset="1" stop-color="{s["orb_glow"]}" stop-opacity="0"/></radialGradient>
<linearGradient id="cloud" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{s["cloud_lit"]}"/><stop offset="1" stop-color="{s["cloud_shade"]}"/></linearGradient>
<linearGradient id="haze" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{s["haze"]}" stop-opacity="0"/><stop offset="1" stop-color="{s["haze"]}" stop-opacity=".55"/></linearGradient>
<linearGradient id="path" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{s["shimmer"]}" stop-opacity=".55"/><stop offset="1" stop-color="{s["shimmer"]}" stop-opacity="0"/></linearGradient>
<radialGradient id="vig" cx=".5" cy=".45" r=".8"><stop offset=".6" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".28"/></radialGradient>
<filter id="cloudy" x="-20%" y="-60%" width="140%" height="220%">
  <feTurbulence type="fractalNoise" baseFrequency=".006 .03" numOctaves="4" seed="4" result="n"/>
  <feDisplacementMap in="SourceGraphic" in2="n" scale="46" xChannelSelector="R" yChannelSelector="G" result="d"/>
  <feGaussianBlur in="d" stdDeviation="2.4"/>
</filter>
<filter id="soft" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="14"/></filter>
<filter id="blur2" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="1.4"/></filter>
<filter id="grain" x="0" y="0" width="100%" height="100%">
  <feTurbulence type="fractalNoise" baseFrequency=".85" numOctaves="2" seed="9" stitchTiles="stitch"/>
  <feColorMatrix values="0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 .7 0"/>
</filter>
</defs>"""


def ridge(base, waves, seed):
    """Smooth closed mountain silhouette down to the horizon."""
    r = random.Random(seed)
    phases = [r.uniform(0, math.tau) for _ in waves]
    pts = []
    for x in range(-20, W + 41, 20):
        y = base - sum(a * (0.5 + 0.5 * math.sin(x / l * math.tau + p)) for (l, a), p in zip(waves, phases))
        pts.append((x, y))
    d = f"M{pts[0][0]},{HORIZON + 2} L{pts[0][0]},{f(pts[0][1])}"
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        d += f" Q{x0},{f(y0)} {f((x0 + x1) / 2)},{f((y0 + y1) / 2)}"
    d += f" L{pts[-1][0]},{HORIZON + 2} Z"
    return d


def mountains(s):
    far = ridge(HORIZON - 8, [(520, 46), (230, 18), (90, 6)], "far")
    near = ridge(HORIZON + 2, [(380, 30), (150, 12), (60, 4)], "near")
    return (
        f'<path d="{far}" fill="{s["far"]}"/>'
        f'<rect x="0" y="{HORIZON - 70}" width="{W}" height="72" fill="url(#haze)" opacity=".7"/>'
        f'<path d="{near}" fill="{s["near"]}" transform="translate(0,6) scale(1,.92)" transform-origin="0 {HORIZON}"/>'
        f'<rect x="0" y="{HORIZON - 30}" width="{W}" height="32" fill="url(#haze)" opacity=".5"/>'
    )


def orb(s):
    x, y, r = s["orb"]
    g = s["glow_size"]
    body = f'<circle cx="{x}" cy="{y}" r="{r}" fill="{s["orb_color"]}"/>'
    if s["crescent"]:
        body = (f'<mask id="cres"><rect width="{W}" height="{H}" fill="#fff"/><circle cx="{x + 11}" cy="{y - 7}" r="{r - 2}" fill="#000"/></mask>'
                f'<circle cx="{x}" cy="{y}" r="{r}" fill="{s["orb_color"]}" mask="url(#cres)"/>')
    return (
        f'<circle cx="{x}" cy="{y}" r="{g}" fill="url(#glow)">'
        f'<animate attributeName="opacity" values=".8;1;.8" dur="8s" repeatCount="indefinite"/></circle>'
        f'<circle cx="{x}" cy="{y}" r="{r * 1.8}" fill="{s["orb_color"]}" opacity=".25" filter="url(#soft)"/>'
        + body
    )


def clouds(s, name):
    r = random.Random("clouds" + name)
    bands = []
    for i in range(6):
        cx = r.uniform(80, W - 80)
        cy = r.uniform(70, HORIZON - 70)
        rx = r.uniform(140, 300)
        ry = r.uniform(10, 22)
        parts = "".join(
            f'<ellipse cx="{f(cx + r.uniform(-rx * .5, rx * .5))}" cy="{f(cy + r.uniform(-6, 6))}" '
            f'rx="{f(rx * r.uniform(.4, .8))}" ry="{f(ry * r.uniform(.7, 1.3))}"/>'
            for _ in range(4)
        )
        dur = r.uniform(70, 120)
        drift = r.uniform(30, 70)
        bands.append(
            f'<g><animateTransform attributeName="transform" type="translate" values="0 0;{f(drift)} 0;0 0" dur="{f(dur)}s" repeatCount="indefinite"/>'
            f'<g fill="url(#cloud)" opacity="{r.uniform(.55, 1) * s["cloud_op"]:.2f}">{parts}</g></g>'
        )
    return f'<g filter="url(#cloudy)">{"".join(bands)}</g>'


def stars(s, name):
    if not s["stars"]:
        return ""
    r = random.Random("stars" + name)
    out = []
    limit = HORIZON - 40 if name == "dawn" else 120
    for _ in range(s["stars"]):
        x, y = r.uniform(0, W), r.uniform(0, limit)
        rad = r.choice((.5, .6, .8, 1, 1.3))
        dur = r.uniform(2.5, 6)
        out.append(f'<circle cx="{f(x)}" cy="{f(y)}" r="{rad}" fill="#ffffff" opacity=".8">'
                   f'<animate attributeName="opacity" values=".9;.2;.9" dur="{f(dur)}s" begin="-{f(r.uniform(0, dur))}s" repeatCount="indefinite"/></circle>')
    if s["sparkles"]:
        for x, y, sz in ((180, 70, 7), (1040, 180, 6), (560, 40, 5)):
            arm = (f"M0,{-sz * 1.7} C{sz * .1},{-sz * .2} {sz * .2},{-sz * .1} {sz},0 C{sz * .2},{sz * .1} {sz * .1},{sz * .2} 0,{sz * 1.7} "
                   f"C{-sz * .1},{sz * .2} {-sz * .2},{sz * .1} {-sz},0 C{-sz * .2},{-sz * .1} {-sz * .1},{-sz * .2} 0,{-sz * 1.7} Z")
            dur = r.uniform(4, 7)
            out.append(f'<g transform="translate({x},{y})"><g><animateTransform attributeName="transform" type="scale" values="1;.5;1" dur="{f(dur)}s" begin="-{f(r.uniform(0, dur))}s" repeatCount="indefinite"/>'
                       f'<circle r="{sz * 2.4}" fill="url(#glow)" opacity=".5"/><path d="{arm}" fill="#ffffff"/></g></g>')
    return "".join(out)


def sea(s):
    x, y, _ = s["orb"]
    r = random.Random("sea")
    glints = []
    for i in range(46):
        depth = r.random()
        gy = HORIZON + 4 + depth ** 1.4 * (H - HORIZON - 8)
        spread = 20 + depth * 120
        gx = x + r.gauss(0, spread * .45)
        w = 6 + depth * 30 * r.random()
        dur = r.uniform(2, 5)
        glints.append(f'<rect x="{f(gx - w / 2)}" y="{f(gy)}" width="{f(w)}" height="{f(1 + depth * 1.4)}" rx="1" fill="{s["shimmer"]}">'
                      f'<animate attributeName="opacity" values="0;.9;0" dur="{f(dur)}s" begin="-{f(r.uniform(0, dur))}s" repeatCount="indefinite"/></rect>')
    lines = "".join(f'<rect x="0" y="{HORIZON + 8 + i * i * 1.6:.0f}" width="{W}" height="1" fill="{s["shimmer"]}" opacity=".06"/>' for i in range(1, 9))
    column = (f'<polygon points="{x - 30},{HORIZON} {x + 30},{HORIZON} {x + 150},{H} {x - 150},{H}" fill="url(#path)" filter="url(#soft)">'
              f'<animate attributeName="opacity" values=".7;1;.7" dur="6s" repeatCount="indefinite"/></polygon>')
    return (f'<rect x="0" y="{HORIZON}" width="{W}" height="{H - HORIZON}" fill="url(#sea)"/>'
            + lines + column + f'<g filter="url(#blur2)">{"".join(glints)}</g>'
            + f'<rect x="0" y="{HORIZON}" width="{W}" height="1.5" fill="{s["shimmer"]}" opacity=".35"/>')


def birds(s):
    if not s["birds"]:
        return ""
    out = []
    flock = [(0, 0, 1), (26, 10, .8), (48, 2, .7)]
    for dx, dy, sc in flock:
        out.append(
            f'<g transform="translate({dx},{dy}) scale({sc})"><path fill="none" stroke="#3b3f6e" stroke-opacity=".55" stroke-width="1.6" stroke-linecap="round">'
            f'<animate attributeName="d" values="M-8,0 Q-4,-5 0,0 Q4,-5 8,0;M-8,-2 Q-4,2 0,0 Q4,2 8,-2;M-8,0 Q-4,-5 0,0 Q4,-5 8,0" dur="{1.1 + dx / 100:.2f}s" repeatCount="indefinite"/></path></g>'
        )
    return (f'<g><animateTransform attributeName="transform" type="translate" values="-120 150;1320 90" dur="60s" repeatCount="indefinite"/>'
            f'{"".join(out)}</g>')


def scene(name):
    s = SCENES[name]
    body = (
        f'<rect width="{W}" height="{H}" fill="url(#sky)"/>'
        + stars(s, name) + orb(s) + clouds(s, name) + birds(s) + mountains(s) + sea(s)
        + f'<rect width="{W}" height="{H}" fill="url(#vig)"/>'
        + f'<rect width="{W}" height="{H}" filter="url(#grain)" opacity=".05"/>'
    )
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">'
            f'{defs(s)}<g clip-path="url(#card)">{body}</g></svg>\n')


def main():
    out = ROOT / "assets"
    out.mkdir(exist_ok=True)
    for old in out.glob("*.svg"):
        old.unlink()
    for name in SCENES:
        (out / f"{name}.svg").write_text(scene(name), encoding="utf-8")


if __name__ == "__main__":
    main()
