"""Makes the Winter look's Christmas lights round the guide's preview, as two
layers: lights_frame.svg (a dark frosted band, the wire and every bulb unlit,
which never changes) and lights_on.svg over it (just the lit bulbs and their
glow, which chase - so a step only redraws that layer). The picture goes in
the black opening, 60 in from every edge of a 1000 x 615 frame - keep the
--video-inset-* settings in winter.css in step with it. The bulbs and their
glow spill MARGIN past the frame, so both layers are drawn that much bigger
than the panel (winter.css's #video-panel::before and ::after).

The bulbs chase like marquee lights: along the string, every CHASE-th bulb is
dark and the rest lit, and each step the dark ones move on one bulb, so the gaps
run round the frame. The steps are discrete, so the page only redraws once a
step rather than every frame. Bulbs are placed from a fixed seed, so a rerun draws the same
frame. Writes next to this script."""
import math
import os
import random

W, H = 1000, 615
INSET = 60
MARGIN = 30
OPEN = (INSET, INSET, W - 2 * INSET, H - 2 * INSET)

# the wire runs round the middle of the band, clipped up every CLIP units and
# drooping a little between clips; a bulb hangs at each clip and halfway between
WIRE_OFFSET = INSET / 2
CLIP = 64
DROOP = 7

BULBS = {
    "red": "#ff3a2e",
    "green": "#2fd35a",
    "blue": "#3a86ff",
    "amber": "#ffc83a",
    "orange": "#ff8a1e",
}
ORDER = ["red", "green", "blue", "amber", "orange"]

# the chase: one bulb in every CHASE is dark, moving on one bulb every STEP seconds
CHASE = 3
STEP = 0.4


def shade(hex_colour, f):
    r, g, b = (int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(c * f))) for c in (r, g, b))


def ring():
    """Corners of the wire's path, clockwise from the top left."""
    o = WIRE_OFFSET
    return [(o, o), (W - o, o), (W - o, H - o), (o, H - o)]


def wire_and_bulbs(rnd):
    """The wire's path and where each bulb hangs: (x, y, angle it points)."""
    corners = ring()
    d = []
    bulbs = []
    for i, (x1, y1) in enumerate(corners):
        x2, y2 = corners[(i + 1) % 4]
        length = math.hypot(x2 - x1, y2 - y1)
        ux, uy = (x2 - x1) / length, (y2 - y1) / length
        nx, ny = uy, -ux  # outward, for a clockwise ring
        steps = max(1, round(length / CLIP))
        step = length / steps
        if i == 0:
            d.append(f"M{x1:.1f} {y1:.1f}")
        for k in range(steps):
            ax, ay = x1 + ux * step * k, y1 + uy * step * k
            bx, by = ax + ux * step, ay + uy * step
            mx, my = (ax + bx) / 2 + nx * DROOP, (ay + by) / 2 + ny * DROOP
            # quadratic sag: the control point sits twice the droop out
            d.append(f"Q{mx + nx * DROOP:.1f} {my + ny * DROOP:.1f} {bx:.1f} {by:.1f}")
            out = math.degrees(math.atan2(ny, nx)) + 90  # the bulb shape points up
            # one at the clip, pointing out; one at the bottom of the sag, pointing in
            bulbs.append((ax, ay, out + rnd.uniform(-18, 18)))
            bulbs.append((mx, my, out + 180 + rnd.uniform(-22, 22)))
    d.append("Z")
    return " ".join(d), bulbs


# an old-fashioned C9 bulb, pointing up from its socket at (0, 0)
BULB = "M0 -6 C-8 -8 -10 -20 -6 -28 C-4 -33 -1 -36 0 -37 C1 -36 4 -33 6 -28 C10 -20 8 -8 0 -6 Z"


def frame():
    rnd = random.Random(1225)
    ox, oy, ow, oh = OPEN
    wire, bulbs = wire_and_bulbs(rnd)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{-MARGIN} {-MARGIN} {W + 2 * MARGIN} {H + 2 * MARGIN}" '
        'preserveAspectRatio="none">',
        '<defs>',
        '<linearGradient id="band" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="#2a3644"/><stop offset="1" stop-color="#18212c"/></linearGradient>',
        '<filter id="soft"><feGaussianBlur stdDeviation="3"/></filter>',
        f'<mask id="outside" maskUnits="userSpaceOnUse" x="{-MARGIN}" y="{-MARGIN}" '
        f'width="{W + 2 * MARGIN}" height="{H + 2 * MARGIN}">'
        f'<rect x="{-MARGIN}" y="{-MARGIN}" width="{W + 2 * MARGIN}" height="{H + 2 * MARGIN}" fill="#fff"/>'
        f'<rect x="{ox}" y="{oy}" width="{ow}" height="{oh}" fill="#000"/></mask>',
    ]
    for name, c in BULBS.items():
        parts.append(f'<radialGradient id="glow-{name}">'
                     f'<stop offset="0" stop-color="{c}" stop-opacity="0.75"/>'
                     f'<stop offset="0.4" stop-color="{c}" stop-opacity="0.3"/>'
                     f'<stop offset="1" stop-color="{c}" stop-opacity="0"/></radialGradient>')
        parts.append(f'<linearGradient id="lit-{name}" x1="0" y1="0" x2="1" y2="0">'
                     f'<stop offset="0" stop-color="{shade(c, 1.0)}"/>'
                     f'<stop offset="0.35" stop-color="#fffbe8"/>'
                     f'<stop offset="1" stop-color="{shade(c, 0.85)}"/></linearGradient>')
    parts.append('</defs>')

    # the band: dark frosted slate with a soft drift of snow along its top, and a
    # thin icy line on each edge
    parts += [
        f'<rect x="4" y="4" width="{W - 8}" height="{H - 8}" rx="14" fill="url(#band)" fill-opacity="0.94"/>',
        f'<rect x="5" y="5" width="{W - 10}" height="{H - 10}" rx="13" fill="none" stroke="#dfeaf5" stroke-opacity="0.45" stroke-width="2"/>',
    ]
    drift = ["M8 22"]
    x = 8
    while x < W - 8:
        nx = min(W - 8, x + rnd.uniform(28, 60))
        drift.append(f"Q{(x + nx) / 2:.0f} {rnd.uniform(2, 10):.0f} {nx:.0f} {rnd.uniform(14, 24):.0f}")
        x = nx
    drift.append(f"L{W - 8} 8 L8 8 Z")
    parts.append(f'<path d="{" ".join(drift)}" fill="#f4f8fc" fill-opacity="0.9" filter="url(#soft)"/>')
    parts.append(f'<rect x="{ox}" y="{oy}" width="{ow}" height="{oh}" fill="#000"/>')
    parts.append(f'<rect x="{ox - 2}" y="{oy - 2}" width="{ow + 4}" height="{oh + 4}" fill="none" '
                 f'stroke="#dfeaf5" stroke-opacity="0.55" stroke-width="2"/>')

    glows = [[] for _ in range(CHASE)]
    lit = [[] for _ in range(CHASE)]
    dim = []
    for n, (x, y, angle) in enumerate(bulbs):
        name = ORDER[n % len(ORDER)]
        c = BULBS[name]
        # bulbs run clockwise round the string, so neighbours land in neighbouring groups
        g = n % CHASE
        t = f'translate({x:.1f} {y:.1f}) rotate({angle:.0f})'
        glows[g].append(f'<circle transform="{t}" cx="0" cy="-22" r="30" fill="url(#glow-{name})"/>')
        dim.append(f'<g transform="{t}">'
                   f'<rect x="-4.5" y="-8" width="9" height="11" rx="2" fill="#1d3b22" stroke="#0f2213" stroke-width="1"/>'
                   f'<path d="{BULB}" fill="{shade(c, 0.42)}" stroke="{shade(c, 0.3)}" stroke-width="1"/></g>')
        lit[g].append(f'<g transform="{t}"><path d="{BULB}" fill="url(#lit-{name})"/>'
                      f'<path d="M-3 -14 C-5 -20 -4 -27 -1 -31" stroke="#fff" stroke-opacity="0.8" '
                      f'stroke-width="2" stroke-linecap="round" fill="none"/></g>')

    def chase(i):
        # group i is dark on step i and lit on the others; the dark group moves on
        # one each step, so the gaps travel clockwise. All groups share one clock
        values = ";".join("0" if step == i else "1" for step in range(CHASE))
        return (f'<animate attributeName="opacity" values="{values}" dur="{STEP * CHASE:.2f}s" '
                f'begin="0s" calcMode="discrete" repeatCount="indefinite"/>')

    # the still layer: the band, the wire and every bulb unlit - drawn once.
    # Bulbs and wire stop at the picture's edge
    base = parts + ['<g mask="url(#outside)">',
                    f'<path d="{wire}" fill="none" stroke="#163019" stroke-width="3.2" stroke-linejoin="round"/>',
                    f'<path d="{wire}" fill="none" stroke="#3a6b3f" stroke-opacity="0.6" stroke-width="1.2"/>',
                    *dim, '</g>', '</svg>']
    # the chasing layer laid over it: only the glows and lit bulbs, so a step
    # redraws just these. It shares the still layer's header and definitions
    header = parts[:parts.index('</defs>') + 1]
    lights = header + ['<g mask="url(#outside)">']
    for i, group in enumerate(glows):
        lights.append(f'<g>{chase(i)}{"".join(group)}</g>')
    for i, group in enumerate(lit):
        lights.append(f'<g>{chase(i)}{"".join(group)}</g>')
    lights += ['</g>', '</svg>']
    return "\n".join(base), "\n".join(lights)


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    base, lights = frame()
    with open(os.path.join(here, "lights_frame.svg"), "w") as f:
        f.write(base)
    with open(os.path.join(here, "lights_on.svg"), "w") as f:
        f.write(lights)
