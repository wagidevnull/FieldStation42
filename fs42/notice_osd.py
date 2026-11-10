import logging
import threading

from fs42.channel_banner import CANVAS_H
from fs42.volume_osd import OUTLINE

# A short notice low on the screen - a red X and "ACTION NOT VALID" when a button
# does nothing here (play, pause, fast forward or rewind on live TV), the way a
# cable box answered a button it couldn't act on. Drawn with mpv's OSD in the same
# pixel font as the volume read-out; a web channel draws the same thing in its page
# (fs42/webrender/web_render.py), since mpv's OSD is hidden under it.

SHOW_SECONDS = 2.5
OVERLAY_ID = 49  # 48 is the volume read-out
BOTTOM = CANVAS_H - 150  # bottom edge of the box, just above the bottom of the screen
BOX_H = 104
PAD_X = 36
ICON = 56  # the X's size
GAP = 26
FONT = "\\fnVT323\\fs80\\bord0\\shad0"

# ASS colours are &HBBGGRR&
RED = "&H2020F0&"
WHITE = "&HFFFFFF&"
BOX = "&H140A0A&"

_l = logging.getLogger("NoticeOSD")


class NoticeOSD:
    def __init__(self, mpv):
        self.mpv = mpv
        self._timer = None
        self._lock = threading.Lock()
        self._text_w = {}

    def invalid(self):
        self.show("ACTION NOT VALID")

    def show(self, text):
        try:
            dims = self.mpv.command("get_property", "osd-dimensions")
            canvas_w = round(CANVAS_H * dims["aspect"])
            events = self._events(canvas_w, text, self._width(text, canvas_w))
            with self._lock:
                if self._timer:
                    self._timer.cancel()
                self.mpv.command("osd-overlay", OVERLAY_ID, "ass-events", "\n".join(events),
                                 canvas_w, CANVAS_H, 0, False)
                self._timer = threading.Timer(SHOW_SECONDS, self.hide)
                self._timer.daemon = True
                self._timer.start()
        except Exception as e:
            _l.warning(f"Could not show notice: {e}")

    def hide(self):
        with self._lock:
            if self._timer:
                self._timer.cancel()
                self._timer = None
            try:
                self.mpv.command("osd-overlay", OVERLAY_ID, "none", "")
            except Exception as e:
                _l.debug(f"Could not hide notice: {e}")

    def _width(self, text, canvas_w):
        # how wide the words render, measured once in a hidden overlay
        if text not in self._text_w:
            width = 0
            try:
                res = self.mpv.command("osd-overlay", OVERLAY_ID + 50, "ass-events",
                                       f"{{\\an7\\pos(0,0){FONT}}}{text}", canvas_w, CANVAS_H, 0, True, True)
                self.mpv.command("osd-overlay", OVERLAY_ID + 50, "none", "")
                if res and "x0" in res:
                    width = res["x1"] - res["x0"]
            except Exception as e:
                _l.debug(f"Could not measure notice: {e}")
            self._text_w[text] = width or len(text) * 34
        return self._text_w[text]

    @staticmethod
    def _events(canvas_w, text, text_w):
        box_w = PAD_X * 2 + ICON + GAP + text_w
        x0 = (canvas_w - box_w) // 2
        top = BOTTOM - BOX_H
        mid_y = top + BOX_H // 2
        ix, iy = x0 + PAD_X, mid_y - ICON // 2
        t = 11  # the X's stroke thickness
        # the X as two thick diagonal strokes
        x_shape = (f"m {t} 0 l {ICON // 2} {ICON // 2 - t} {ICON - t} 0 {ICON} {t} {ICON // 2 + t} {ICON // 2} "
                   f"{ICON} {ICON - t} {ICON - t} {ICON} {ICON // 2} {ICON // 2 + t} {t} {ICON} 0 {ICON - t} "
                   f"{ICON // 2 - t} {ICON // 2} 0 {t}")
        return [
            f"{{\\an7\\pos({x0},{top})\\bord3\\shad0\\3c{OUTLINE}\\1c{BOX}\\1a&H20&\\p1}}"
            f"m 0 0 l {box_w} 0 {box_w} {BOX_H} 0 {BOX_H}{{\\p0}}",
            f"{{\\an7\\pos({ix},{iy})\\bord2\\shad0\\3c{OUTLINE}\\1c{RED}\\p1}}{x_shape}{{\\p0}}",
            f"{{\\an4\\pos({ix + ICON + GAP},{mid_y}){FONT}\\1c{WHITE}}}{text}",
        ]
