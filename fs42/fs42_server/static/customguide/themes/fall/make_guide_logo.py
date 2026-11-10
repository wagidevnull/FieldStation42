# Burnt-orange version of the TV Guide logo for the Fall look: a plain matte
# button, orange at the top darkening to brown at the bottom, no gloss.
# Usage: make_guide_logo.py ../../logos/tvguide.png guide_logo.png
import sys
import numpy as np
from PIL import Image, ImageFilter

src, out = sys.argv[1], sys.argv[2]
im = Image.open(src).convert("RGBA")
# work at 2x for smoother edges
im = im.resize((im.width * 2, im.height * 2), Image.LANCZOS)
a = np.asarray(im).astype(np.float32) / 255.0
rgb, A = a[..., :3], a[..., 3]
h, w = A.shape

# letters: the white parts inside the shape
white = np.clip((rgb.min(axis=2) - 0.55) / 0.35, 0, 1) * A

ys = np.linspace(0, 1, h)[:, None] * np.ones((1, w))
rows = np.where(A.max(axis=1) > 0.5)[0]
top, bot = rows[0] / h, rows[-1] / h
t = np.clip((ys - top) / (bot - top), 0, 1)


def lerp(c1, c2, f):
    return np.array(c1)[None, None, :] * (1 - f[..., None]) + np.array(c2)[None, None, :] * f[..., None]


# body: muted orange at the top, deepening to brown over the bottom half
c_top, c_mid, c_bot = (0.84, 0.52, 0.24), (0.66, 0.36, 0.15), (0.36, 0.18, 0.07)
body = np.where(t[..., None] < 0.5, lerp(c_top, c_mid, t / 0.5), lerp(c_mid, c_bot, (t - 0.5) / 0.5))

# letters: cream, with a faint brown shadow below them
shadow = np.roll(white, 6, axis=0)
shadow = np.asarray(Image.fromarray((shadow * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(5))) / 255.0
body = body * (1 - 0.4 * shadow[..., None]) + np.array([0.20, 0.08, 0.02]) * 0.4 * shadow[..., None]
col = body * (1 - white[..., None]) + np.array([0.98, 0.94, 0.86]) * white[..., None]


def erode(mask, px):
    # shrink by a round brush, so the edge is the same width everywhere - corners included
    out = mask.copy()
    pad = np.pad(mask, px)
    for dy in range(-px, px + 1):
        for dx in range(-px, px + 1):
            if dx * dx + dy * dy <= px * px:
                out = np.minimum(out, pad[px + dy:px + dy + h, px + dx:px + dx + w])
    return out


# a plain dark brown edge
rim = np.clip(A - erode(A, 6), 0, 1)
col = col * (1 - 0.7 * rim[..., None]) + np.array([0.22, 0.10, 0.03]) * 0.7 * rim[..., None]

res = Image.fromarray((np.dstack([np.clip(col, 0, 1), A]) * 255).astype(np.uint8))
res = res.resize((res.width // 2, res.height // 2), Image.LANCZOS)
res.save(out)
