"""Hangs icicles off a logo for the Winter look, and gives it a slight icy sheen:
finds the undersides of its shapes (the bottoms of letters, rims and swooshes)
and hangs icicles of varying length from the flat stretches, on a canvas
extended downward to fit them. The extra
height is EXTEND times the logo's own, which winter.css allows for when sizing
the image. Icicles are placed from a fixed seed, so a rerun draws the same ones.

Usage: make_icicles.py <logo .svg or .png> <out .png> [seed]
(an SVG is drawn with Qt first, so run it with FieldStation42's env/bin/python)"""
import random
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

EXTEND = 0.45
RENDER_H = 480   # an SVG is drawn this tall before the icicles go on
SCALE = 3        # icicles are drawn this much bigger, then scaled down, for smooth edges


def load(path):
    if not path.endswith(".svg"):
        return Image.open(path).convert("RGBA")
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QGuiApplication, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer
    app = QGuiApplication.instance() or QGuiApplication([])
    r = QSvgRenderer(path)
    s = r.defaultSize()
    w = round(RENDER_H * s.width() / s.height())
    img = QImage(w, RENDER_H, QImage.Format_RGBA8888)
    img.fill(0)
    p = QPainter(img)
    r.render(p, QRectF(0, 0, w, RENDER_H))
    p.end()
    buf = img.constBits().tobytes()
    return Image.frombytes("RGBA", (w, RENDER_H), buf, "raw", "RGBA", img.bytesPerLine())


def anchors(alpha, rnd):
    """Points on the undersides of the logo's shapes that an icicle can hang from."""
    h, w = alpha.shape
    solid = alpha > 128
    # the lowest solid pixel in each column, or -1
    bottom = np.where(solid.any(axis=0), h - 1 - np.argmax(solid[::-1], axis=0), -1)
    pts = []
    x = rnd.randint(2, 10)
    while x < w - 3:
        y = bottom[x]
        flat = (y >= 0 and bottom[x - 3] >= 0 and bottom[x + 3] >= 0
                and abs(int(bottom[x - 3]) - y) <= 3 and abs(int(bottom[x + 3]) - y) <= 3)
        if flat:
            pts.append((x, int(y)))
            x += rnd.randint(int(h * 0.05), int(h * 0.11))
        else:
            x += 2
    return pts


def room_below(solid, x, y, half):
    """How far an icicle hanging at (x, y) can drop before it would run into
    another part of the logo (the canvas below the logo is all free)."""
    h, w = solid.shape
    cols = solid[y + 3:, max(0, x - half):min(w, x + half + 1)]
    hit = np.where(cols.any(axis=1))[0]
    return hit[0] + 3 if len(hit) else None


def icicle_layer(size, pts, logo_h, rnd, solid):
    """The icicles, drawn big: rounded ice, bluer at the edges and bright through
    the middle, clearing toward the tip, with now and then a drop forming there."""
    W, H = size[0] * SCALE, size[1] * SCALE
    body, core, edge, shine = (Image.new("L", (W, H), 0) for _ in range(4))
    db, dc, de, ds = (ImageDraw.Draw(m) for m in (body, core, edge, shine))
    gap = logo_h * 0.03
    for x, y in pts:
        # mostly short, now and then a long one
        length = logo_h * (rnd.uniform(0.08, 0.2) if rnd.random() < 0.7 else rnd.uniform(0.25, EXTEND * 0.92))
        width = logo_h * rnd.uniform(0.022, 0.045) * (1.25 if length > logo_h * 0.25 else 1.0)
        lean = rnd.uniform(-0.15, 0.15)
        # which ones get a drop is picked apart from the shared random sequence, so
        # adding drops didn't change the icicles themselves
        drop = random.Random(x * 7919 + y).random() < 0.3
        room = room_below(solid, x, y, int(width))
        if room is not None:
            # more of the logo below here - stop a little short of it, so the ice
            # stays clear of the lettering
            if room - gap < logo_h * 0.04:
                continue
            length = min(length, room - gap)
            drop = False
        tip = (x + lean * width) * SCALE, (y + length) * SCALE
        top = (y - 1) * SCALE
        half_w = width / 2 * SCALE

        def outline(f):
            """The icicle's two sides, `f` of its full width - sides that bulge a
            little near the top, then taper to the tip."""
            lpts, rpts = [], []
            for i in range(13):
                t = i / 12
                cy = top + (tip[1] - top) * t
                cx = (x * SCALE) * (1 - t) + tip[0] * t
                half = half_w * f * (1 - t) ** 1.35 * (1 + 0.15 * np.sin(t * np.pi))
                lpts.append((cx - half, cy))
                rpts.append((cx + half, cy))
            return lpts, rpts

        lpts, rpts = outline(1.0)
        db.polygon(lpts + rpts[::-1], fill=255)
        de.line(lpts + [tip] + rpts[::-1], fill=255, width=max(2, SCALE))
        # the bright core runs a little left of centre, as if lit from the left
        cl, cr = outline(0.42)
        dc.polygon([(px - half_w * 0.15, py) for px, py in cl + cr[::-1]], fill=255)
        ds.line([(px + half_w * 0.36, py) for px, py in lpts[1:-3]], fill=255, width=max(2, SCALE))
        # a little knob of ice where it meets the logo
        r = half_w * 1.4
        db.ellipse([x * SCALE - r, top - r * 0.6, x * SCALE + r, top + r * 0.6], fill=255)
        if drop and length > logo_h * 0.15:
            # a drop of meltwater just below the tip
            dr = half_w * 0.5
            cx, cy = tip[0], tip[1] + dr * 2.2
            db.ellipse([cx - dr, cy - dr * 1.2, cx + dr, cy + dr], fill=255)
            de.ellipse([cx - dr, cy - dr * 1.2, cx + dr, cy + dr], outline=255, width=max(2, SCALE))
            dc.ellipse([cx - dr * 0.7, cy - dr * 0.9, cx + dr * 0.2, cy], fill=255)

    b = np.asarray(body).astype(np.float32) / 255
    c = np.asarray(core.filter(ImageFilter.GaussianBlur(SCALE * 1.5))).astype(np.float32) / 255
    e = np.asarray(edge).astype(np.float32) / 255
    s = np.asarray(shine.filter(ImageFilter.GaussianBlur(SCALE))).astype(np.float32) / 255
    # how far down the icicles each row is: 0 at the logo's bottom, 1 at the canvas's
    ys = np.clip((np.arange(H)[:, None] / SCALE - logo_h * 0.75) / (H / SCALE - logo_h * 0.75), 0, 1)
    ys = ys * np.ones((1, W))
    # ice blue at the edges, deepening further down; near white through the core
    edge_c = np.dstack([150 - 40 * ys, 196 - 30 * ys, 236 - 10 * ys])
    core_c = np.array([250, 253, 255], dtype=np.float32)
    rgb = edge_c * (1 - c[..., None]) + core_c * c[..., None]
    # a faint darker outline so they read on light backgrounds, and a bright streak
    rgb = rgb * (1 - 0.5 * e[..., None]) + np.array([78, 122, 172]) * 0.5 * e[..., None]
    rgb = rgb * (1 - 0.75 * s[..., None]) + 255 * 0.75 * s[..., None]
    # solid near the top, clearer toward the tips
    a = np.clip(np.maximum(b * (0.95 - 0.3 * ys), e * 0.7), 0, 1)
    img = Image.fromarray(np.dstack([np.clip(rgb, 0, 255), a * 255]).astype(np.uint8))
    return img.resize(size, Image.LANCZOS)


def gloss(logo):
    """A slight icy sheen: a soft diagonal band of light across the upper part of
    the logo, and a fainter thin one below it."""
    a = np.asarray(logo).astype(np.float32)
    h, w = a.shape[:2]
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    # distance from a line running gently downhill left to right
    d = (ys / h) - (0.26 + 0.22 * (xs / w))
    band = np.clip(1 - np.abs(d) / 0.12, 0, 1) ** 1.5 * 0.36
    band += np.clip(1 - np.abs(d - 0.24) / 0.035, 0, 1) * 0.18
    band *= a[..., 3] / 255
    a[..., :3] = a[..., :3] * (1 - band[..., None]) + 255 * band[..., None]
    return Image.fromarray(a.astype(np.uint8))


def main():
    src, out = sys.argv[1], sys.argv[2]
    rnd = random.Random(int(sys.argv[3]) if len(sys.argv) > 3 else 7)
    logo = load(src)
    w, h = logo.size
    canvas = Image.new("RGBA", (w, round(h * (1 + EXTEND))), (0, 0, 0, 0))
    alpha = np.asarray(logo)[..., 3]
    pts = anchors(alpha, rnd)
    canvas.alpha_composite(icicle_layer(canvas.size, pts, h, rnd, alpha > 128))
    # the logo goes over them, so the icicles look like they grow from under it
    canvas.alpha_composite(gloss(logo), (0, 0))
    canvas.save(out)
    print(f"{out}: {len(pts)} icicles")


if __name__ == "__main__":
    main()
