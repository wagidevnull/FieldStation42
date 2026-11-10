"""Makes leaf_frame.svg for the Fall look: brown and orange fall leaves heaped
around the guide's preview. The picture goes in the black opening, which is 60 in
from every edge of a 1000 x 615 frame - keep the --video-inset-* settings in
fall.css in step with it. The leaves spill MARGIN past the frame on every side,
so the image is drawn that much bigger than the panel (fall.css's
#video-panel::before) and no leaf is sliced off at its edge. Leaves are placed from a fixed seed, so a rerun draws
the same frame. Writes next to this script."""
import math
import os
import random

W, H = 1000, 615
INSET = 60
OPEN = (INSET, INSET, W - 2 * INSET, H - 2 * INSET)
MARGIN = 30

# leaf outlines, about 100 units long, pointing up from a stem at (0, 0), with the
# side veins drawn on each - leaf() centres them on the point it is given
MAPLE = {
    "outline": "M0 0 L-4 -14 L-30 -10 L-24 -22 L-46 -40 L-34 -42 L-40 -62 L-22 -52 L-20 -66 "
               "L-10 -60 L0 -96 L10 -60 L20 -66 L22 -52 L40 -62 L34 -42 L46 -40 L24 -22 "
               "L30 -10 L4 -14 Z",
    "veins": "M0 -14 L-38 -38 M0 -14 L38 -38 M0 -18 L-26 -58 M0 -18 L26 -58 "
             "M-17 -25 L-24 -18 M17 -25 L24 -18",
}
OAK = {
    "outline": "M0 0 C-10 -6 -26 -10 -20 -22 C-34 -26 -36 -40 -22 -44 C-34 -54 -30 -68 -16 -66 "
               "C-20 -82 -8 -96 0 -98 C8 -96 20 -82 16 -66 C30 -68 34 -54 22 -44 C36 -40 34 -26 "
               "20 -22 C26 -10 10 -6 0 0 Z",
    "veins": "M0 -16 L-22 -26 M0 -16 L22 -26 M0 -34 L-26 -44 M0 -34 L26 -44 "
             "M0 -54 L-18 -64 M0 -54 L18 -64 M0 -72 L-8 -82 M0 -72 L8 -82",
}
ELM = {
    "outline": "M0 0 C-22 -16 -30 -50 -18 -76 C-10 -90 -4 -96 0 -100 C4 -96 10 -90 18 -76 "
               "C30 -50 22 -16 0 0 Z",
    "veins": "M0 -14 L-16 -22 M0 -14 L16 -22 M0 -30 L-20 -40 M0 -30 L20 -40 "
             "M0 -46 L-19 -58 M0 -46 L19 -58 M0 -62 L-14 -74 M0 -62 L14 -74 M0 -78 L-7 -88 M0 -78 L7 -88",
}
SHAPES = [MAPLE, MAPLE, OAK, ELM]

# muted fall colours: deep browns at the back, rust and soft orange in front
BACK = ["#4a2a14", "#5a3219", "#3f2412", "#62381c"]
FRONT = ["#7a4422", "#8c4f26", "#9a5a2b", "#a8632e", "#b5713a", "#8a3f24", "#9c7a3c", "#c0803f"]
COLOURS = BACK + FRONT


def shade(hex_colour, f):
    """Lighter (f > 1) or darker (f < 1) version of a colour."""
    r, g, b = (int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(c * f))) for c in (r, g, b))


def gradients():
    """One gradient per colour: lit along one side, darker toward the other edge."""
    out = []
    for i, c in enumerate(COLOURS):
        out.append(
            f'<linearGradient id="g{i}" x1="0" y1="0" x2="1" y2="1">'
            f'<stop offset="0" stop-color="{shade(c, 1.28)}"/>'
            f'<stop offset="0.45" stop-color="{c}"/>'
            f'<stop offset="1" stop-color="{shade(c, 0.62)}"/>'
            f'</linearGradient>')
    return out


def leaf(rnd, x, y, size, colour):
    s = size / 100
    shape = rnd.choice(SHAPES)
    fill = f"url(#g{COLOURS.index(colour)})"
    edge = shade(colour, 0.45)
    vein = shade(colour, 0.55)
    parts = [
        f'<g transform="translate({x:.1f} {y:.1f}) rotate({rnd.uniform(0, 360):.0f}) '
        f'scale({s:.3f}) translate(0 50)">',
        f'<path d="{shape["outline"]}" fill="{fill}" stroke="{edge}" stroke-width="2.5" stroke-linejoin="round"/>',
        # a darker band down one half, as if the leaf were folded slightly along its midrib
        f'<path d="{shape["outline"]}" fill="#1a0c04" fill-opacity="0.18" clip-path="url(#half)"/>',
        f'<path d="{shape["veins"]}" stroke="{vein}" stroke-width="1.6" stroke-linecap="round" fill="none" opacity="0.85"/>',
        f'<path d="M0 8 L0 -84" stroke="{vein}" stroke-width="3" stroke-linecap="round" fill="none"/>',
    ]
    # now and then a few dark spots of decay
    if rnd.random() < 0.3:
        for _ in range(rnd.randint(1, 3)):
            parts.append(f'<circle cx="{rnd.uniform(-14, 14):.0f}" cy="{rnd.uniform(-70, -24):.0f}" '
                         f'r="{rnd.uniform(2.5, 5):.1f}" fill="{shade(colour, 0.4)}" opacity="0.7"/>')
    parts.append('</g>')
    return "".join(parts)


def ring_points(offset, spacing, rnd, wobble):
    """Points running round the frame, `offset` in from its outer edge."""
    corners = [(offset, offset), (W - offset, offset), (W - offset, H - offset),
               (offset, H - offset), (offset, offset)]
    pts = []
    for (x1, y1), (x2, y2) in zip(corners, corners[1:]):
        steps = max(1, int(math.hypot(x2 - x1, y2 - y1) / spacing))
        for i in range(steps):
            t = i / steps
            pts.append((x1 + (x2 - x1) * t + rnd.uniform(-wobble, wobble),
                        y1 + (y2 - y1) * t + rnd.uniform(-wobble, wobble)))
    return pts


def frame():
    rnd = random.Random(1031)
    ox, oy, ow, oh = OPEN
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{-MARGIN} {-MARGIN} {W + 2 * MARGIN} {H + 2 * MARGIN}" '
        'preserveAspectRatio="none">',
        '<defs>',
        '<filter id="shadow" x="-20%" y="-20%" width="140%" height="140%">',
        '<feDropShadow dx="0" dy="3" stdDeviation="3" flood-color="#1a0c04" flood-opacity="0.55"/>',
        '</filter>',
        '<filter id="soft"><feGaussianBlur stdDeviation="6"/></filter>',
        '<clipPath id="half"><rect x="0" y="-110" width="60" height="130"/></clipPath>',
        # leaves stop at the picture's edge
        f'<mask id="outside" maskUnits="userSpaceOnUse" x="{-MARGIN}" y="{-MARGIN}" '
        f'width="{W + 2 * MARGIN}" height="{H + 2 * MARGIN}">'
        f'<rect x="{-MARGIN}" y="{-MARGIN}" width="{W + 2 * MARGIN}" height="{H + 2 * MARGIN}" fill="#fff"/>'
        f'<rect x="{ox}" y="{oy}" width="{ow}" height="{oh}" fill="#000"/></mask>',
        *gradients(),
        '</defs>',
        # a dark earthy band under the leaves, so no gaps show through to the wallpaper
        f'<path fill-rule="evenodd" fill="#2e1a0c" fill-opacity="0.92" filter="url(#soft)" '
        f'd="M6 6 H{W - 6} V{H - 6} H6 Z M{ox} {oy} V{oy + oh} H{ox + ow} V{oy} Z"/>',
        f'<rect x="{ox}" y="{oy}" width="{ow}" height="{oh}" fill="#000"/>',
        '<g mask="url(#outside)"><g filter="url(#shadow)">',
    ]
    # back layer: bigger, darker leaves packed along the middle of the band
    for x, y in ring_points(INSET / 2, 34, rnd, 6):
        parts.append(leaf(rnd, x, y, rnd.uniform(58, 72), rnd.choice(BACK)))
    # front layer: smaller, brighter leaves scattered over them
    for x, y in ring_points(INSET / 2, 26, rnd, 12):
        parts.append(leaf(rnd, x, y, rnd.uniform(42, 58), rnd.choice(FRONT)))
    # an inner ring hugging the picture, so the leaves run right up to its edge
    for x, y in ring_points(INSET - 12, 20, rnd, 4):
        parts.append(leaf(rnd, x, y, rnd.uniform(34, 46), rnd.choice(FRONT + BACK[:2])))
    # an extra cluster at each corner, where the frame turns
    for cx, cy in [(INSET / 2, INSET / 2), (W - INSET / 2, INSET / 2),
                   (W - INSET / 2, H - INSET / 2), (INSET / 2, H - INSET / 2)]:
        for _ in range(5):
            parts.append(leaf(rnd, cx + rnd.uniform(-16, 16), cy + rnd.uniform(-16, 16),
                              rnd.uniform(48, 64), rnd.choice(FRONT)))
    parts.append('</g></g>')
    # a thin dark edge round the picture
    parts.append(f'<rect x="{ox - 1}" y="{oy - 1}" width="{ow + 2}" height="{oh + 2}" fill="none" '
                 f'stroke="#1e1007" stroke-width="2"/>')
    parts.append('</svg>')
    return "\n".join(parts)


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "leaf_frame.svg"), "w") as f:
        f.write(frame())
