import logging
import threading

from fs42.channel_banner import CANVAS_H

# The channel number as it's typed on the remote: green digits in a see-through
# black box in the bottom left corner (clear of the channel banner across the top), with a blinking underscore waiting for the next
# digit, in the same pixel font as the volume read-out (VT323). Drawn with mpv's OSD;
# a web channel draws the same thing in its page (fs42/webrender/web_render.py).

OVERLAY_ID = 50  # 48 volume, 49 notice
MAX_DIGITS = 3  # the remote tunes as soon as three are in
BLINK = 0.5  # seconds the underscore is on, then off
TIMEOUT = 4  # gone by itself if no tune follows
LEFT, BOTTOM = 80, 60  # in from the bottom left corner of the picture, on the 1080-high canvas
PAD_X, BOX_H = 34, 130
FONT = "\\fnVT323\\fs120\\bord0\\shad0"
CHAR_W = 48  # VT323 is monospaced: 0.4em a character, and size 120 is a 120px em

GREEN = "&H40FF40&"
BLACK = "&H000000&"

_l = logging.getLogger("ChannelEntryOSD")


class ChannelEntryOSD:
    def __init__(self, mpv):
        self.mpv = mpv
        self._lock = threading.Lock()
        self._digits = ""
        self._generation = 0
        self._hide_timer = None

    def show(self, digits):
        """Show what's been typed so far ("" takes it down)."""
        digits = "".join(c for c in str(digits) if c.isdigit())[:MAX_DIGITS]
        if not digits:
            self.hide()
            return
        with self._lock:
            self._digits = digits
            self._generation += 1
            generation = self._generation
            if self._hide_timer:
                self._hide_timer.cancel()
            self._hide_timer = threading.Timer(TIMEOUT, self.hide)
            self._hide_timer.daemon = True
            self._hide_timer.start()
        self._draw(True)
        if len(digits) < MAX_DIGITS:
            threading.Thread(target=self._blink, args=(generation,), daemon=True).start()

    def hide(self):
        with self._lock:
            self._generation += 1
            self._digits = ""
            if self._hide_timer:
                self._hide_timer.cancel()
                self._hide_timer = None
            try:
                self.mpv.command("osd-overlay", OVERLAY_ID, "none", "")
            except Exception as e:
                _l.debug(f"Could not hide channel entry: {e}")

    def _blink(self, generation):
        on = True
        while True:
            threading.Event().wait(BLINK)
            on = not on
            with self._lock:
                if generation != self._generation:
                    return
            self._draw(on)

    def _draw(self, cursor_on):
        with self._lock:
            digits = self._digits
            if not digits:
                return
            try:
                dims = self.mpv.command("get_property", "osd-dimensions")
                canvas_w = round(CANVAS_H * dims["aspect"])
                waiting = len(digits) < MAX_DIGITS
                # the box is sized for the full three characters, so it doesn't jump about
                box_w = PAD_X * 2 + CHAR_W * MAX_DIGITS
                # a 4:3 show has black bars at the sides - stay inside the picture, like the bug
                left_bar = dims.get("ml", 0) * canvas_w / dims["w"] if dims.get("w") else 0
                bottom_bar = dims.get("mb", 0) * CANVAS_H / dims["h"] if dims.get("h") else 0
                x0 = round(left_bar + LEFT)
                top = round(CANVAS_H - bottom_bar - BOTTOM - BOX_H)
                mid_y = top + BOX_H // 2
                # the underscore keeps its place while it blinks off (drawn clear)
                cursor = ("{\\1a&H00&}_" if cursor_on else "{\\1a&HFF&}_") if waiting else ""
                events = [
                    f"{{\\an7\\pos({x0},{top})\\bord0\\shad0\\1c{BLACK}\\1a&H50&\\p1}}"
                    f"m 0 0 l {box_w} 0 {box_w} {BOX_H} 0 {BOX_H}{{\\p0}}",
                    f"{{\\an4\\pos({x0 + PAD_X},{mid_y}){FONT}\\1c{GREEN}}}{digits}{cursor}",
                ]
                self.mpv.command("osd-overlay", OVERLAY_ID, "ass-events", "\n".join(events),
                                 canvas_w, CANVAS_H, 0, False)
            except Exception as e:
                _l.debug(f"Could not draw channel entry: {e}")
