# Draws the Pay-Per-View channel logo: a gold admission ticket with "PPV" on it.
# The lettering is turned into outlines (Anton, SIL Open Font License) so the SVG
# looks the same everywhere - the guide's browser and the banner's Qt renderer.
import sys
from fontTools.ttLib import TTFont
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.boundsPen import BoundsPen

font_path, out = sys.argv[1], sys.argv[2]
font = TTFont(font_path)
glyphs = font.getGlyphSet()
cmap = font.getBestCmap()
upm = font["head"].unitsPerEm


def text_path(text, x, baseline, size, tracking=0.0):
    """SVG path data for text, left edge at x, with its width."""
    scale = size / upm
    pen = SVGPathPen(glyphs)
    cursor = 0
    for ch in text:
        name = cmap[ord(ch)]
        tp = TransformPen(pen, (scale, 0, 0, -scale, x + cursor, baseline))
        glyphs[name].draw(tp)
        cursor += glyphs[name].width * scale + tracking * size
    return pen.getCommands(), cursor - tracking * size


def text_bounds(text, size, tracking=0.0):
    scale = size / upm
    bp = BoundsPen(glyphs)
    cursor = 0
    for ch in text:
        name = cmap[ord(ch)]
        tp = TransformPen(bp, (scale, 0, 0, -scale, cursor, 0))
        glyphs[name].draw(tp)
        cursor += glyphs[name].width * scale + tracking * size
    return bp.bounds  # xmin, ymin(top, negative), xmax, ymax


W, H = 300, 136
NOTCH = 17
R = 14
# ticket outline: rounded corners, half-circle notches cut from the middle of each end
ticket = (
    f"M{R},0 H{W - R} A{R},{R} 0 0 1 {W},{R} "
    f"V{H / 2 - NOTCH} A{NOTCH},{NOTCH} 0 0 0 {W},{H / 2 + NOTCH} "
    f"V{H - R} A{R},{R} 0 0 1 {W - R},{H} H{R} A{R},{R} 0 0 1 0,{H - R} "
    f"V{H / 2 + NOTCH} A{NOTCH},{NOTCH} 0 0 0 0,{H / 2 - NOTCH} V{R} A{R},{R} 0 0 1 {R},0 Z"
)

size = 118
track = 0.02
xmin, top, xmax, bottom = text_bounds("PPV", size, track)
tw, th = xmax - xmin, bottom - top
x = (W - tw) / 2 - xmin
baseline = (H - th) / 2 - top
ppv, _ = text_path("PPV", x, baseline, size, track)

PAD = 9
svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W + 8}" height="{H + 8}" viewBox="-4 -4 {W + 8} {H + 8}">
  <defs>
    <linearGradient id="gold" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#ffe17a"/>
      <stop offset="0.55" stop-color="#f7b928"/>
      <stop offset="1" stop-color="#e08a12"/>
    </linearGradient>
    <linearGradient id="red" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#d2232c"/>
      <stop offset="1" stop-color="#8e0f16"/>
    </linearGradient>
  </defs>
  <path d="{ticket}" fill="url(#gold)" stroke="#5c1208" stroke-width="5" stroke-linejoin="round"/>
  <rect x="{PAD + NOTCH}" y="{PAD}" width="{W - 2 * (PAD + NOTCH)}" height="{H - 2 * PAD}" rx="6"
        fill="none" stroke="#8e0f16" stroke-width="3" stroke-dasharray="7 6"/>
  <path d="{ppv}" fill="#5c1208" transform="translate(3 4)"/>
  <path d="{ppv}" fill="url(#red)" stroke="#fff4cf" stroke-width="2.5" paint-order="stroke"/>
</svg>
'''
open(out, "w").write(svg)
print(f"wrote {out}")
