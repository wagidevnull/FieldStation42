# Slate blue-grey version of the TV Guide logo for the Winter look: a plain matte
# button, frosty blue-grey at the top darkening to slate at the bottom, no gloss.
# The icicles and sheen go on after, with make_icicles.py:
#   make_guide_logo.py ../../logos/tvguide.png button.png
#   make_icicles.py button.png guide_logo.png 3
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


# body: frosty blue-grey at the top, deepening to slate over the bottom half
c_top, c_mid, c_bot = (0.66, 0.74, 0.83), (0.45, 0.54, 0.65), (0.22, 0.28, 0.37)
body = np.where(t[..., None] < 0.5, lerp(c_top, c_mid, t / 0.5), lerp(c_mid, c_bot, (t - 0.5) / 0.5))

# letters: snow white, with a faint slate shadow below them
shadow = np.roll(white, 6, axis=0)
shadow = np.asarray(Image.fromarray((shadow * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(5))) / 255.0
body = body * (1 - 0.4 * shadow[..., None]) + np.array([0.08, 0.11, 0.17]) * 0.4 * shadow[..., None]
col = body * (1 - white[..., None]) + np.array([0.98, 0.99, 1.0]) * white[..., None]


def erode(mask, px):
    # shrink by a round brush, so the edge is the same width everywhere - corners included
    out = mask.copy()
    pad = np.pad(mask, px)
    for dy in range(-px, px + 1):
        for dx in range(-px, px + 1):
            if dx * dx + dy * dy <= px * px:
                out = np.minimum(out, pad[px + dy:px + dy + h, px + dx:px + dx + w])
    return out


# a plain dark slate edge
rim = np.clip(A - erode(A, 6), 0, 1)
col = col * (1 - 0.7 * rim[..., None]) + np.array([0.12, 0.16, 0.23]) * 0.7 * rim[..., None]

res = Image.fromarray((np.dstack([np.clip(col, 0, 1), A]) * 255).astype(np.uint8))
res = res.resize((res.width // 2, res.height // 2), Image.LANCZOS)
res.save(out)
