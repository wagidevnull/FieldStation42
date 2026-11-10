import logging
import threading

from fs42.channel_banner import CANVAS_H, NAVY, ORANGE, WHITE, MUTED, _ass_text

# Which game a YouTube highlight is - "Panthers at Oilers", the date, and any playoff
# note - in a box in the bottom left as each highlight starts (fs42/youtube_channel.py
# reads it from the video's title). Drawn with mpv's OSD like the channel banner, so
# it sits on the video and follows the screen aspect ratio the same way.

CAPTION_SECONDS = 10
OVERLAY_ID = 45  # 42 is the banner, 43 the track picker, 44 the banner's measuring overlay
MEASURE_OVERLAY_ID = 46

LEFT = 60
BOTTOM = CANVAS_H - 76
PAD_X = 30
PAD_Y = 20
BAR_W = 10
LINES = [
    # (game key, font size, colour, bold)
    ("matchup", 52, WHITE, True),
    ("date", 34, MUTED, False),
    ("note", 32, ORANGE, True),
]

_l = logging.getLogger("GameCaption")


class GameCaption:
    def __init__(self, mpv):
        self.mpv = mpv
        self._timer = None
        self._lock = threading.Lock()

    def show(self, game):
        """Put up the caption for a game ({"matchup", "date", "note"}) for a while."""
        if not game:
            self.hide()
            return
        try:
            dims = self.mpv.command("get_property", "osd-dimensions")
            canvas_w = round(CANVAS_H * dims["aspect"])
            lines = [(game[key], size, color, bold) for key, size, color, bold in LINES if game.get(key)]
            texts = [self._font(size, color, bold) + _ass_text(text) for text, size, color, bold in lines]
            width = max(self._text_width(t, canvas_w) for t in texts) or 600
            height = sum(round(size * 1.2) for _, size, _, _ in lines)
            top = BOTTOM - height - 2 * PAD_Y
            box_w = width + 2 * PAD_X + BAR_W
            events = [
                f"{{\\an7\\pos({LEFT},{top})\\bord0\\shad0\\1c{NAVY}\\1a&H30&\\p1}}"
                f"m 0 0 l {box_w} 0 {box_w} {height + 2 * PAD_Y} 0 {height + 2 * PAD_Y}{{\\p0}}",
                f"{{\\an7\\pos({LEFT},{top})\\bord0\\shad0\\1c{ORANGE}\\p1}}"
                f"m 0 0 l {BAR_W} 0 {BAR_W} {height + 2 * PAD_Y} 0 {height + 2 * PAD_Y}{{\\p0}}",
            ]
            y = top + PAD_Y
            for text, (_, size, _, _) in zip(texts, lines):
                events.append(f"{{\\an7\\pos({LEFT + BAR_W + PAD_X},{y})}}{text}")
                y += round(size * 1.2)
            with self._lock:
                self._cancel_timer()
                self.mpv.command("osd-overlay", OVERLAY_ID, "ass-events", "\n".join(events),
                                 canvas_w, CANVAS_H, 0, False)
                self._timer = threading.Timer(CAPTION_SECONDS, self.hide)
                self._timer.daemon = True
                self._timer.start()
        except Exception as e:
            _l.warning(f"Could not show game caption: {e}")

    def hide(self):
        with self._lock:
            self._cancel_timer()
            try:
                self.mpv.command("osd-overlay", OVERLAY_ID, "none", "")
            except Exception as e:
                _l.debug(f"Could not hide game caption: {e}")

    @staticmethod
    def _font(size, color, bold):
        return f"{{\\fnArial\\fs{size}\\b{1 if bold else 0}\\bord2\\shad1\\3c{NAVY}\\1c{color}}}"

    def _text_width(self, ass_text, canvas_w):
        # render the text into a hidden overlay and ask mpv how wide it came out
        try:
            res = self.mpv.command(
                "osd-overlay", MEASURE_OVERLAY_ID, "ass-events", f"{{\\an7\\pos(0,0)}}{ass_text}",
                canvas_w, CANVAS_H, 0, True, True,
            )
            self.mpv.command("osd-overlay", MEASURE_OVERLAY_ID, "none", "")
            if res and "x0" in res:
                return res["x1"] - res["x0"]
        except Exception as e:
            _l.debug(f"Could not measure caption text: {e}")
        return 0

    def _cancel_timer(self):
        if self._timer:
            self._timer.cancel()
            self._timer = None
