# Glossy green "glass button" version of the TV Guide logo, for the Frutiger Aero look.
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

# body: bright lime at the top to deep green at the bottom
c_top, c_mid, c_bot = (0.62, 0.92, 0.36), (0.20, 0.72, 0.18), (0.06, 0.42, 0.10)
body = np.where(t[..., None] < 0.5, lerp(c_top, c_mid, t / 0.5), lerp(c_mid, c_bot, (t - 0.5) / 0.5))

# a soft light glow coming up from the bottom edge, like light through the glass
glow = np.clip(1 - (1 - t) / 0.28, 0, 1) ** 2 * 0.45
body = body * (1 - glow[..., None]) + np.array([0.70, 1.0, 0.55]) * glow[..., None]

# letters: white, with a faint green shadow below them for depth
shadow = np.roll(white, 6, axis=0)
shadow = np.asarray(Image.fromarray((shadow * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(5))) / 255.0
body = body * (1 - 0.45 * shadow[..., None]) + np.array([0.02, 0.25, 0.05]) * 0.45 * shadow[..., None]
col = body * (1 - white[..., None]) + np.array([1.0, 1.0, 1.0]) * white[..., None]

# rim: a dark outer edge and a thin bright line just inside it
def erode(mask, px):
    # shrink by a round brush, so the rim is the same width everywhere - corners included
    out = mask.copy()
    pad = np.pad(mask, px)
    for dy in range(-px, px + 1):
        for dx in range(-px, px + 1):
            if dx * dx + dy * dy <= px * px:
                out = np.minimum(out, pad[px + dy:px + dy + h, px + dx:px + dx + w])
    return out

e1, e2, e3 = erode(A, 6), erode(A, 10), erode(A, 14)
dark_rim = np.clip(A - e1, 0, 1)
light_rim = np.clip(e2 - e3, 0, 1)
col = col * (1 - 0.6 * dark_rim[..., None]) + np.array([0.02, 0.22, 0.05]) * 0.6 * dark_rim[..., None]
col = col * (1 - 0.35 * light_rim[..., None]) + 0.35 * light_rim[..., None]

# the gloss: a bright sheen over the top half with a crisp lower edge
gloss_edge = top + (bot - top) * 0.47
xs = np.linspace(-1, 1, w)[None, :] * np.ones((h, 1))
curve = gloss_edge + 0.04 * (xs ** 2)          # edge dips a little toward the sides
gl = np.where(ys < curve, 0.62 - 0.45 * np.clip((ys - top) / (curve - top), 0, 1), 0.0)
gl = gl * e1                                    # keep it inside the rim
col = col * (1 - gl[..., None]) + gl[..., None]

outa = np.dstack([np.clip(col, 0, 1), A])
res = Image.fromarray((outa * 255).astype(np.uint8))
res = res.resize((res.width // 2, res.height // 2), Image.LANCZOS)
res.save(out)
