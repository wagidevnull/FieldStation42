import logging
import threading

from fs42.channel_banner import CANVAS_H

# The volume read-out an old CRT set put up when you pressed volume on the remote:
# "VOLUME", a row of green bars and the number, low on the screen in a pixel font
# (VT323), gone a few seconds after the last press. Drawn with mpv's OSD like the
# channel banner, so it sits on the picture; a web channel draws the same thing in
# its page (fs42/webrender/web_render.py), since mpv's OSD is hidden under it.

SHOW_SECONDS = 3
OVERLAY_ID = 48  # 42 banner, 43 track picker, 44/46 measuring, 45 game caption, 47 trick play
SEGMENTS = 50  # one per press - the remote moves the volume 2% at a time
SEG_W, SEG_H, SEG_GAP = 9, 46, 4
Y = CANVAS_H - 190  # top of the bars
FONT = "\\fnVT323\\fs86\\bord3\\shad0"

# ASS colours are &HBBGGRR&
GREEN = "&H40FF40&"
DIM = "&H123A12&"
OUTLINE = "&H000000&"

_l = logging.getLogger("VolumeOSD")


class VolumeOSD:
    def __init__(self, mpv):
        self.mpv = mpv
        self._timer = None
        self._lock = threading.Lock()

    def show(self, level, muted):
        """Put up the volume read-out (level 0-100), or MUTE, for a few seconds."""
        try:
            dims = self.mpv.command("get_property", "osd-dimensions")
            canvas_w = round(CANVAS_H * dims["aspect"])
            events = self._events(canvas_w, max(0, min(100, int(level))), muted)
            with self._lock:
                if self._timer:
                    self._timer.cancel()
                self.mpv.command("osd-overlay", OVERLAY_ID, "ass-events", "\n".join(events),
                                 canvas_w, CANVAS_H, 0, False)
                self._timer = threading.Timer(SHOW_SECONDS, self.hide)
                self._timer.daemon = True
                self._timer.start()
        except Exception as e:
            _l.warning(f"Could not show the volume: {e}")

    def hide(self):
        with self._lock:
            if self._timer:
                self._timer.cancel()
                self._timer = None
            try:
                self.mpv.command("osd-overlay", OVERLAY_ID, "none", "")
            except Exception as e:
                _l.debug(f"Could not hide the volume: {e}")

    @staticmethod
    def _events(canvas_w, level, muted):
        bars_w = SEGMENTS * SEG_W + (SEGMENTS - 1) * SEG_GAP
        x0 = (canvas_w - bars_w) // 2
        mid_y = Y + SEG_H // 2
        lit = 0 if muted else round(level / 100 * SEGMENTS)
        events = [
            # the word on the left and the number (or MUTE) on the right, either side of the bars
            f"{{\\an6\\pos({x0 - 28},{mid_y}){FONT}\\3c{OUTLINE}\\1c{GREEN}}}VOLUME",
            f"{{\\an4\\pos({x0 + bars_w + 28},{mid_y}){FONT}\\3c{OUTLINE}\\1c{GREEN}}}"
            f"{'MUTE' if muted else level}",
        ]
        lit_shapes, dim_shapes = [], []
        for i in range(SEGMENTS):
            x = i * (SEG_W + SEG_GAP)
            shape = f"m {x} 0 l {x + SEG_W} 0 {x + SEG_W} {SEG_H} {x} {SEG_H}"
            (lit_shapes if i < lit else dim_shapes).append(shape)
        for shapes, colour in ((dim_shapes, DIM), (lit_shapes, GREEN)):
            if shapes:
                # a black edge round each bar keeps them crisp over a bright picture
                events.append(f"{{\\an7\\pos({x0},{Y})\\bord2\\shad0\\3c{OUTLINE}\\1c{colour}\\p1}}"
                              f"{' '.join(shapes)}{{\\p0}}")
        return events
