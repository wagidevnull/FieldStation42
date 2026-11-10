"""Generates the Halloween guide theme artwork: scene.svg, slime_frame.svg,
guide_logo.svg, footer.svg and stars.svg. Writes next to this script unless
another folder is given:  python make_halloween.py [out_dir]
The art is seeded, so a run with no changes gives back the same files.
(The orange provider logos in logos/ are not made here.)"""
import math
import os
import random
import sys

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
rnd = random.Random(1031)

SLIME_LIGHT = "#b6ff4a"
SLIME_MID = "#6fd61f"
SLIME_DARK = "#2a6e0c"
SILHOUETTE = "#140c30"


def bat(x, y, s, color=SILHOUETTE):
    # wings out, little ears - drawn around (x, y), s = scale
    return (
        f'<path transform="translate({x} {y}) scale({s})" fill="{color}" d="'
        "M0 0 c-4 -6 -10 -8 -16 -6 c3 2 4 5 3 8 c-4 -3 -9 -3 -13 0 c3 1 5 4 5 7 "
        "c-3 -2 -7 -2 -10 0 c6 -1 12 1 16 5 c3 -4 7 -6 12 -6 c2 -1 3 -2 3 -4 "
        "l1 -3 l1 2 l2 0 l1 -2 l1 3 c0 2 1 3 3 4 c5 0 9 2 12 6 c4 -4 10 -6 16 -5 "
        "c-3 -2 -7 -2 -10 0 c0 -3 2 -6 5 -7 c-4 -3 -9 -3 -13 0 c-1 -3 0 -6 3 -8 "
        'c-6 -2 -12 0 -16 6 z"/>'
    )


def scene():
    # band across the top of the info panel, between the provider logo and the clock:
    # dusk sky, moon, haunted house on a hill, bats, and "guide" in slime
    # tall enough that the hill and sky fade out level with the show name
    w, h = 1200, 280
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">',
        "<defs>",
        '<linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="#2a0f5c"/><stop offset="0.4" stop-color="#3b2a96" stop-opacity="0.8"/>'
        '<stop offset="1" stop-color="#3b2a96" stop-opacity="0"/></linearGradient>',
        '<radialGradient id="glow"><stop offset="0" stop-color="#ffb347" stop-opacity="0.75"/>'
        '<stop offset="1" stop-color="#ff7a00" stop-opacity="0"/></radialGradient>',
        '<radialGradient id="moon" cx="0.4" cy="0.4"><stop offset="0" stop-color="#fff4c2"/>'
        '<stop offset="1" stop-color="#ffc85a"/></radialGradient>',
        '<linearGradient id="hillfade" x1="0" y1="0" x2="0" y2="1"><stop offset="0.3" stop-color="#140c30"/>'
        '<stop offset="1" stop-color="#140c30" stop-opacity="0"/></linearGradient>',
        f'<linearGradient id="slime" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{SLIME_LIGHT}"/>'
        f'<stop offset="1" stop-color="{SLIME_MID}"/></linearGradient>',
        "</defs>",
        f'<rect width="{w}" height="{h}" fill="url(#sky)"/>',
    ]
    for _ in range(40):
        parts.append(
            f'<circle cx="{rnd.uniform(240, 870):.0f}" cy="{rnd.uniform(5, 90):.0f}" '
            f'r="{rnd.uniform(0.6, 1.6):.1f}" fill="#fff" opacity="{rnd.uniform(0.35, 0.9):.2f}"/>'
        )
    # the moon, house and hill sit right of the provider logo - wide ones like Comcast too
    parts.append('<g transform="translate(200 0)">')
    # moon with an orange glow, a cloud wisp across it
    parts += [
        '<circle cx="345" cy="62" r="95" fill="url(#glow)"/>',
        '<circle cx="345" cy="62" r="44" fill="url(#moon)"/>',
        '<circle cx="331" cy="52" r="7" fill="#e9b04a" opacity="0.35"/>',
        '<circle cx="360" cy="76" r="5" fill="#e9b04a" opacity="0.3"/>',
        '<path d="M262 84 q32 -11 72 -3 q24 -8 56 0 q24 -5 48 3 q-40 8 -88 5 q-48 5 -88 -5z" '
        'fill="#5a3fb0" opacity="0.55"/>',
    ]
    # hill, fading out at the bottom so it never sits on the text below
    parts.append('<path d="M190 280 Q330 108 470 116 Q610 108 750 280 Z" fill="url(#hillfade)"/>')
    # dead tree on the left of the hill
    parts.append(
        f'<path d="M335 156 q5 -32 -3 -62 m3 21 q-15 -10 -24 -27 m24 18 q13 -13 18 -32 '
        f'm-21 5 q-8 -8 -8 -19 m11 37 q16 -2 26 -13" stroke="{SILHOUETTE}" stroke-width="6" '
        'fill="none" stroke-linecap="round"/>'
    )
    # haunted house: main hall, a tall tower with a spire, a side wing, a chimney
    house = [
        "M440 128 L440 82 L464 60 L488 82 L488 128 Z",
        "M488 128 L488 92 L512 75 L536 92 L536 128 Z",
        "M414 128 L414 66 L426 66 L426 40 L431 22 L436 40 L436 66 L448 66 L448 128 Z",
        "M472 70 L472 56 L479 56 L479 76 Z",
    ]
    for d in house:
        parts.append(f'<path d="{d}" fill="{SILHOUETTE}"/>')
    for x, y, ww, hh in [(420, 78, 7, 10), (432, 78, 7, 10), (426, 100, 7, 10), (450, 94, 9, 12),
                         (468, 94, 9, 12), (458, 112, 9, 10), (500, 102, 8, 10), (518, 102, 8, 10)]:
        parts.append(f'<rect x="{x}" y="{y}" width="{ww}" height="{hh}" fill="#ffb22e"/>')
        parts.append(f'<rect x="{x - 3}" y="{y - 3}" width="{ww + 6}" height="{hh + 6}" fill="#ffb22e" opacity="0.25"/>')
    for x, y in [(556, 124), (578, 130), (360, 128)]:
        parts.append(f'<path d="M{x} {y + 15} v-10 a7 7 0 0 1 14 0 v10 z" fill="#2c2550"/>')
    for x, y, s in [(250, 32, 0.8), (300, 14, 0.55), (520, 22, 0.7), (560, 48, 0.45), (395, 110, 0.4), (600, 12, 0.5)]:
        parts.append(bat(x, y, s))
    parts.append("</g>")
    parts.append("</svg>")
    return "\n".join(parts)


def drip_path(x, y, width, length):
    # a slime drip hanging from (x, y): narrow neck, round drop at the end
    r = width / 2
    return (
        f"M{x - r} {y} C{x - r} {y + length * 0.6} {x - r * 0.6} {y + length * 0.8} "
        f"{x - r * 1.1} {y + length} A{r * 1.15} {r * 1.15} 0 1 0 {x + r * 1.1} {y + length} "
        f"C{x + r * 0.6} {y + length * 0.8} {x + r} {y + length * 0.6} {x + r} {y} Z"
    )


def drip_layers(drips, fill, outline, outline_width):
    """Drips as two layers: draw the outline one under the slime body and the fill one
    over it. The fill starts inside the body, covering the body's own edge where each
    drip leaves it, so only the drip's outer edge is outlined."""
    d = " ".join(drip_path(*dr) for dr in drips)
    under = f'<path d="{d}" fill="{outline}" stroke="{outline}" stroke-width="{outline_width}"/>'
    over = f'<path d="{d}" fill="{fill}"/>'
    return under, over


def wavy_edge(points_from, points_to, steps, amp):
    # points along a straight line with a gentle random wobble, as smooth curves
    (x0, y0), (x1, y1) = points_from, points_to
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy)
    nx, ny = -dy / length, dx / length
    out = []
    for i in range(1, steps + 1):
        t = i / steps
        off = rnd.uniform(-amp, amp) if i < steps else 0
        cx = x0 + dx * (t - 0.5 / steps) + nx * rnd.uniform(-amp, amp) * 1.6
        cy = y0 + dy * (t - 0.5 / steps) + ny * rnd.uniform(-amp, amp) * 1.6
        out.append(f"Q{cx:.1f} {cy:.1f} {x0 + dx * t + nx * off:.1f} {y0 + dy * t + ny * off:.1f}")
    return " ".join(out)


def slime_frame():
    # stretched over the preview panel; the opening is where the player puts the video
    w, h = 1000, 600
    ix, iy, iw, ih = 30, 30, 940, 500  # opening - matches --video-inset-* in halloween.css
    outer = (
        f"M6 10 {wavy_edge((6, 10), (994, 8), 14, 5)} "
        f"{wavy_edge((994, 8), (996, 566), 9, 5)} "
        f"{wavy_edge((996, 566), (4, 568), 14, 6)} "
        f"{wavy_edge((4, 568), (6, 10), 9, 5)} Z"
    )
    hole = f"M{ix} {iy} H{ix + iw} V{iy + ih} H{ix} Z"
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" preserveAspectRatio="none">',
        "<defs>",
        f'<linearGradient id="g" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="180" y2="600"><stop offset="0" stop-color="{SLIME_LIGHT}"/>'
        f'<stop offset="0.5" stop-color="{SLIME_MID}"/><stop offset="1" stop-color="#4aa514"/></linearGradient>',
        "</defs>",
        f'<rect x="{ix}" y="{iy}" width="{iw}" height="{ih}" fill="#000"/>',
    ]
    # drips off the bottom edge - they start inside the slime so they hang from it
    drips = []
    x = 40
    while x < 960:
        length = rnd.choice([16, 20, 26, 32, 38, 44])
        drips.append((x, 548, rnd.uniform(12, 22), min(length, 588 - 548)))
        x += rnd.uniform(45, 110)
    under, over = drip_layers(drips, "url(#g)", SLIME_DARK, 5)
    parts += [
        under,
        f'<path fill-rule="evenodd" d="{outer} {hole}" fill="url(#g)" stroke="{SLIME_DARK}" stroke-width="4"/>',
        over,
        # the opening gets its own dark rim so the video looks set into the slime
        f'<rect x="{ix}" y="{iy}" width="{iw}" height="{ih}" fill="none" stroke="{SLIME_DARK}" stroke-width="5"/>',
    ]
    # glossy highlights along the top edge
    for _ in range(14):
        parts.append(
            f'<ellipse cx="{rnd.uniform(40, 960):.0f}" cy="{rnd.uniform(12, 22):.0f}" rx="{rnd.uniform(6, 22):.0f}" '
            f'ry="{rnd.uniform(2, 4):.1f}" fill="#fff" opacity="{rnd.uniform(0.3, 0.6):.2f}"/>'
        )
    for _ in range(5):
        parts.append(
            f'<ellipse cx="{rnd.uniform(10, 22):.0f}" cy="{rnd.uniform(60, 500):.0f}" rx="2.5" '
            f'ry="{rnd.uniform(8, 20):.0f}" fill="#fff" opacity="0.4"/>'
        )
    parts.append("</svg>")
    return "\n".join(parts)


def pumpkin(x, ground, size):
    # jack-o-lantern sitting on the ground line, lit from inside
    rx, ry = size, size * 0.78
    cy = ground - ry
    face = (
        f'<path d="M{x - rx * 0.5} {cy - ry * 0.2} l{rx * 0.18} -{ry * 0.3} l{rx * 0.18} {ry * 0.3} z"/>'
        f'<path d="M{x + rx * 0.14} {cy - ry * 0.2} l{rx * 0.18} -{ry * 0.3} l{rx * 0.18} {ry * 0.3} z"/>'
        f'<path d="M{x - rx * 0.55} {cy + ry * 0.15} q{rx * 0.55} {ry * 0.55} {rx * 1.1} 0 '
        f'l-{rx * 0.14} {ry * 0.08} l-{rx * 0.12} -{ry * 0.1} l-{rx * 0.14} {ry * 0.12} l-{rx * 0.14} -{ry * 0.12} '
        f'l-{rx * 0.14} {ry * 0.12} l-{rx * 0.12} -{ry * 0.1} z"/>'
    )
    return "\n".join([
        # warm light spilling onto the grass around it
        f'<ellipse cx="{x}" cy="{cy}" rx="{rx * 2.6}" ry="{ry * 2.1}" fill="url(#pglow)"/>',
        f'<ellipse cx="{x - rx * 0.45}" cy="{cy}" rx="{rx * 0.6}" ry="{ry}" fill="#e86a00"/>',
        f'<ellipse cx="{x + rx * 0.45}" cy="{cy}" rx="{rx * 0.6}" ry="{ry}" fill="#e86a00"/>',
        f'<ellipse cx="{x}" cy="{cy}" rx="{rx * 0.62}" ry="{ry}" fill="#ff8c1a"/>',
        f'<path d="M{x - 3} {cy - ry + 2} q2 -{size * 0.35} {size * 0.3} -{size * 0.42}" stroke="#2c4f10" '
        f'stroke-width="{max(3, size * 0.16):.1f}" fill="none" stroke-linecap="round"/>',
        # the face twice: a soft blurred glow, then the sharp cut-out on top
        f'<g fill="#ffb000" filter="url(#fglow)">{face}</g>',
        f'<g fill="#ffe86a">{face}</g>',
    ])


def bare_tree(x, ground, height, color="#040208"):
    # a leafless tree: trunk, then branches that keep forking and thinning out
    segments = []

    def branch(x0, y0, angle, length, width, depth):
        x1 = x0 + math.cos(angle) * length
        y1 = y0 - math.sin(angle) * length
        bend = rnd.uniform(-0.25, 0.25) * length
        segments.append((width, f"M{x0:.1f} {y0:.1f} Q{(x0 + x1) / 2 + bend:.1f} {(y0 + y1) / 2:.1f} {x1:.1f} {y1:.1f}"))
        if depth == 0 or width < 0.8:
            return
        for _ in range(rnd.choice([2, 2, 3])):
            branch(x1, y1, angle + rnd.uniform(-0.75, 0.75), length * rnd.uniform(0.62, 0.8), width * 0.64, depth - 1)

    branch(x, ground, math.pi / 2 + rnd.uniform(-0.12, 0.12), height * 0.3, max(4, height * 0.075), 6)
    return "\n".join(
        f'<path d="{d}" stroke="{color}" stroke-width="{w:.1f}" fill="none" stroke-linecap="round"/>'
        for w, d in segments
    )


def footer():
    # strip along the bottom of the screen: grass, vines, tombstones, jack-o-lanterns.
    # It is drawn behind the guide, so the tall trees run up behind the grid.
    w, h = 1920, 280
    ground = 262
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" preserveAspectRatio="xMidYMax slice">',
        '<defs><linearGradient id="fade" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="#0b0a2a" stop-opacity="0"/><stop offset="0.45" stop-color="#0b0a2a" stop-opacity="0.85"/>'
        '<stop offset="1" stop-color="#05040f"/></linearGradient>'
        '<radialGradient id="pglow"><stop offset="0" stop-color="#ff9a1f" stop-opacity="0.55"/>'
        '<stop offset="0.5" stop-color="#ff7a00" stop-opacity="0.22"/><stop offset="1" stop-color="#ff7a00" stop-opacity="0"/></radialGradient>'
        '<filter id="fglow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="2.5"/></filter></defs>',
        f'<rect y="{h - 130}" width="{w}" height="130" fill="url(#fade)"/>',
    ]
    # a woods of bare trees in silhouette, furthest back - a back row of shorter ones,
    # then a front row of tall ones that reach up behind the guide
    for x in range(20, w, 95):
        parts.append(bare_tree(x + rnd.uniform(-35, 35), ground + 4, rnd.uniform(120, 175), "#0a0614"))
    for x in range(60, w, 150):
        parts.append(bare_tree(x + rnd.uniform(-45, 45), ground + 4, rnd.uniform(190, 270)))
    # tombstones behind the grass
    for x in [180, 560, 1010, 1420, 1760]:
        tw = rnd.uniform(34, 48)
        th = rnd.uniform(44, 64)
        parts.append(
            f'<path d="M{x} {ground} v-{th - tw / 2:.0f} a{tw / 2:.0f} {tw / 2:.0f} 0 0 1 {tw:.0f} 0 v{th - tw / 2:.0f} z" '
            f'fill="#3a3560" stroke="#22203f" stroke-width="3"/>'
        )
        parts.append(f'<text x="{x + tw / 2:.0f}" y="{ground - th * 0.45:.0f}" font-family="DejaVu Sans" '
                     f'font-size="12" font-weight="bold" text-anchor="middle" fill="#22203f">RIP</text>')
    # vines: wandering curly stems
    for start in range(0, w, 320):
        d = f"M{start} {ground - 10}"
        x = start
        for _ in range(6):
            x += 55
            d += f" q-28 -{rnd.uniform(20, 46):.0f} {55} -{rnd.uniform(-8, 14):.0f}"
        parts.append(f'<path d="{d}" stroke="#1d4a0e" stroke-width="5" fill="none" stroke-linecap="round"/>')
        for _ in range(5):
            lx, ly = start + rnd.uniform(20, 320), ground - rnd.uniform(18, 50)
            parts.append(f'<ellipse cx="{lx:.0f}" cy="{ly:.0f}" rx="11" ry="5" transform="rotate({rnd.uniform(-50, 50):.0f} {lx:.0f} {ly:.0f})" fill="#245c12"/>')
    # jack-o-lanterns
    for x in [90, 420, 760, 1180, 1520]:
        parts.append(pumpkin(x, ground + 6, rnd.uniform(26, 36)))
    # the big one, bottom right
    parts.append(pumpkin(1835, ground + 10, 58))
    # grass blades in front of everything
    blades = []
    x = 0
    while x < w:
        bh = rnd.uniform(18, 52)
        lean = rnd.uniform(-12, 12)
        bw = rnd.uniform(5, 10)
        blades.append(f"M{x:.0f} {h} L{x + lean + bw / 2:.0f} {h - bh - (h - ground):.0f} L{x + bw:.0f} {h} Z")
        x += rnd.uniform(3, 8)
    parts.append(f'<path d="{" ".join(blades)}" fill="#0c2d07"/>')
    blades = []
    x = 2
    while x < w:
        bh = rnd.uniform(10, 34)
        lean = rnd.uniform(-10, 10)
        bw = rnd.uniform(4, 8)
        blades.append(f"M{x:.0f} {h} L{x + lean + bw / 2:.0f} {h - bh - (h - ground):.0f} L{x + bw:.0f} {h} Z")
        x += rnd.uniform(4, 10)
    parts.append(f'<path d="{" ".join(blades)}" fill="#164510"/>')
    # a few bats over the strip
    for bx, by, s in [(300, 150, 0.7), (980, 140, 0.55), (1640, 155, 0.65)]:
        parts.append(bat(bx, by, s, "#1d1446"))
    parts.append("</svg>")
    return "\n".join(parts)


def guide_logo():
    # "guide" in slime - stands in for the TV Guide logo in this theme
    w, h = 260, 130
    gx, base = 130, 80
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">',
        f'<defs><linearGradient id="slime" gradientUnits="userSpaceOnUse" x1="0" y1="20" x2="0" y2="125">'
        f'<stop offset="0" stop-color="{SLIME_LIGHT}"/><stop offset="1" stop-color="{SLIME_MID}"/></linearGradient></defs>',
    ]
    # drips hang from the bottoms of u, i, d and e
    drips = [(gx + dx, base - 8, wd, ln) for dx, wd, ln in
             [(-42, 7, 30), (-24, 6, 20), (2, 7, 40), (30, 6, 24), (52, 7, 34), (70, 5, 18)]]
    under, over = drip_layers(drips, "url(#slime)", SLIME_DARK, 6)
    text = ('font-family="URW Bookman, DejaVu Sans, sans-serif" font-weight="bold" font-size="76" '
            f'font-style="italic" text-anchor="middle" x="{gx}" y="{base}"')
    parts += [
        under,
        f'<text {text} fill="{SLIME_DARK}" stroke="{SLIME_DARK}" stroke-width="14" stroke-linejoin="round">guide</text>',
        f'<text {text} fill="url(#slime)" stroke="{SLIME_MID}" stroke-width="4" stroke-linejoin="round">guide</text>',
        over,
        f'<ellipse cx="{gx - 60}" cy="44" rx="10" ry="4" fill="#fff" opacity="0.45"/>',
        f'<ellipse cx="{gx + 8}" cy="40" rx="8" ry="3" fill="#fff" opacity="0.4"/>',
        "</svg>",
    ]
    return "\n".join(parts)


def stars():
    # a tile of tiny stars, repeated behind the guide grid - its own random source,
    # so adding it didn't reshuffle the rest of the artwork
    rnd = random.Random(42)
    w, h = 480, 360
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">']
    for _ in range(34):
        parts.append(
            f'<circle cx="{rnd.uniform(0, w):.1f}" cy="{rnd.uniform(0, h):.1f}" r="{rnd.uniform(0.5, 1.3):.2f}" '
            f'fill="#ffffff" opacity="{rnd.uniform(0.25, 0.8):.2f}"/>'
        )
    # a couple of slightly brighter ones with a soft halo
    for _ in range(3):
        x, y = rnd.uniform(20, w - 20), rnd.uniform(20, h - 20)
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" fill="#cfd8ff" opacity="0.18"/>')
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="1.4" fill="#ffffff" opacity="0.9"/>')
    parts.append("</svg>")
    return "\n".join(parts)


def spider(x, y, drop, color):
    """A little spider hanging on a silk line from (x, y). It's dark like the
    silhouettes, with a pale rim so it still shows against the night sky."""
    bx, by = x, y + drop
    dark = "#0b0820"
    legs = []
    for side in (-1, 1):
        # four legs a side: out and up to a knee, then down to a foot
        for knee_dx, knee_dy, foot_dx, foot_dy in ((10, -12, 16, -4), (13, -6, 21, 4), (13, 2, 21, 13), (10, 7, 15, 19)):
            legs.append(
                f"M{bx + side * 4:.1f} {by + 2:.1f} L{bx + side * knee_dx:.1f} {by + knee_dy:.1f} "
                f"L{bx + side * foot_dx:.1f} {by + foot_dy:.1f}"
            )
    legs = " ".join(legs)
    return "\n".join([
        f'<path d="M{x:.1f} {y:.1f} L{bx:.1f} {by - 12:.1f}" stroke="{color}" stroke-width="1.6" stroke-opacity="0.6"/>',
        f'<path d="{legs}" stroke="{color}" stroke-width="4.2" stroke-opacity="0.45" fill="none" '
        f'stroke-linecap="round" stroke-linejoin="round"/>',
        f'<path d="{legs}" stroke="{dark}" stroke-width="2.4" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
        f'<circle cx="{bx:.1f}" cy="{by - 7:.1f}" r="5.5" fill="{dark}" stroke="{color}" stroke-width="1.2" stroke-opacity="0.6"/>',
        f'<ellipse cx="{bx:.1f}" cy="{by + 6:.1f}" rx="8.5" ry="10.5" fill="{dark}" stroke="{color}" stroke-width="1.2" stroke-opacity="0.6"/>',
    ])


def spider_web():
    # a corner web for the top left, behind the provider logo. Threads fan out from
    # the corner and the rings sag a little toward it between threads. Uses no random
    # numbers, so it doesn't shift the rest of the art.
    size = 360
    height = 400  # a little taller than the web, for the spider hanging off it
    # the first and last threads run along the top and left edges of the screen,
    # so the rings are anchored to the walls
    angles = [0, 15, 29, 44, 59, 74, 90]
    reach = [360, 330, 345, 352, 338, 346, 360]
    rings = [44, 86, 128, 168, 210, 252, 292]
    color = "#dfe6ff"
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {height}">']

    def point(angle, r):
        a = math.radians(angle)
        return r * math.cos(a), r * math.sin(a)

    threads = []
    for angle, r in zip(angles, reach):
        x, y = point(angle, r)
        threads.append(f"M0 0 L{x:.1f} {y:.1f}")
    parts.append(
        f'<path d="{" ".join(threads)}" stroke="{color}" stroke-width="5" '
        f'stroke-opacity="0.6" fill="none" stroke-linecap="round"/>'
    )

    spiral = []
    for k, ring in enumerate(rings):
        # each ring is a touch uneven, like a real web
        radii = [ring * (1 + 0.04 * math.sin(k * 1.7 + i * 2.3)) for i in range(len(angles))]
        x, y = point(angles[0], radii[0])
        d = f"M{x:.1f} {y:.1f}"
        for i in range(1, len(angles)):
            mid = (angles[i - 1] + angles[i]) / 2
            cx, cy = point(mid, (radii[i - 1] + radii[i]) / 2 * 0.86)
            x, y = point(angles[i], radii[i])
            d += f" Q{cx:.1f} {cy:.1f} {x:.1f} {y:.1f}"
        spiral.append(d)
    parts.append(
        f'<path d="{" ".join(spiral)}" stroke="{color}" stroke-width="3.8" '
        f'stroke-opacity="0.5" fill="none" stroke-linecap="round"/>'
    )
    parts.append(spider(*point(angles[0], 338), drop=128, color=color))
    parts.append("</svg>")
    return "\n".join(parts)


for name, fn in [("guide_logo.svg", guide_logo), ("scene.svg", scene), ("slime_frame.svg", slime_frame), ("footer.svg", footer), ("stars.svg", stars), ("spider_web.svg", spider_web)]:
    with open(f"{OUT}/{name}", "w") as f:
        f.write(fn())
    print("wrote", name)
