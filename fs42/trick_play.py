import logging
import time

from fs42.channel_banner import CANVAS_H, NAVY, ORANGE, WHITE, MUTED, _ass_text

# Play, pause, fast forward and rewind for on-demand movies, with a DVR-style bar
# along the bottom of the screen showing what's happening and how far in it is.
# Each fast forward or rewind press steps the speed up (2x, 4x ... 32x); play goes
# back to normal and pause freezes the picture (a second pause plays on).
#
# 2x and 4x fast forward just run mpv faster. Past that, and for all rewinding, mpv
# sits paused while this jumps the picture along a few times a second, the way a
# DVR scans - mpv can't play backwards smoothly, and decoding a big movie at 8x+
# would choke.

SPEEDS = [2, 4, 8, 16, 32]
SMOOTH_FF = {2, 4}          # fast forward speeds mpv plays itself
SCAN_INTERVAL = 0.25        # seconds between jumps while scanning
BAR_SECONDS = 4             # the bar stays this long after going back to play
OVERLAY_ID = 47             # 42 banner, 43 track picker, 44/46 measuring, 45 game caption

LEFT = 80
BAR_H = 112
BOTTOM_GAP = 70
TRACK_H = 10

_l = logging.getLogger("TrickPlay")


def _clock(seconds):
    seconds = max(0, int(seconds))
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


class TrickPlay:
    def __init__(self, mpv, title):
        self.mpv = mpv
        self.title = title
        self.direction = 0       # 1 fast forward, -1 rewind, 0 playing or paused
        self.level = 0           # index into SPEEDS
        self.paused = False
        self.position = 0.0      # where a scan has got to
        self._last_scan = 0.0
        self._hide_at = None
        self._shown = False

    # ---- remote buttons ----
    def press(self, action):
        if action == "play":
            self._play()
        elif action == "pause":
            if self.paused and not self.direction:
                self._play()
            else:
                self._stop_scan()
                self.paused = True
                self._set("pause", True)
        elif action in ("fast_forward", "rewind"):
            direction = 1 if action == "fast_forward" else -1
            if self.direction == direction:
                self.level = min(self.level + 1, len(SPEEDS) - 1)
            else:
                # a scan already knows where it is; mpv's position lags behind its seeks
                was_scanning = self._scanning()
                self._stop_scan()
                if not was_scanning:
                    self.position = self._get("time-pos") or 0.0
                self.direction = direction
                self.level = 0
            self.paused = False
            self._apply_speed()
        else:
            return
        self._hide_at = None if (self.paused or self.direction) else time.time() + BAR_SECONDS
        self.draw()

    # ---- called from the playback loop ----
    def tick(self):
        """Move a scan along and keep the bar up to date. Call it every loop pass."""
        now = time.time()
        if self._scanning() and now - self._last_scan >= SCAN_INTERVAL:
            step = SPEEDS[self.level] * (now - self._last_scan if self._last_scan else SCAN_INTERVAL)
            self._last_scan = now
            duration = self._get("duration") or 0
            self.position += self.direction * step
            if self.position <= 0:
                # back at the start - play from there
                self.position = 0
                self._seek(0, exact=True)
                self._play(seek=False)
            elif duration and self.position >= duration - 2:
                # run off the end - let it finish, which goes back to the menu
                self._seek(max(0, duration - 2), exact=True)
                self._play(seek=False)
            else:
                # exact frames at the slower speeds (keyframes can be 10s apart, which would
                # leave a slow rewind stuck on one picture); keyframes when going fast
                self._seek(self.position, exact=SPEEDS[self.level] <= 8)
            self.draw()
        elif self._shown and now >= (self._hide_at or now + 1):
            self.hide()
        elif self._shown and int(now * 2) != int((now - 0.05) * 2):
            # keep the clock on the bar ticking
            self.draw()

    def active(self):
        return bool(self.direction or self.paused)

    def hide(self):
        self._shown = False
        self._hide_at = None
        try:
            self.mpv.command("osd-overlay", OVERLAY_ID, "none", "")
        except Exception as e:
            _l.debug(f"Could not hide the trick play bar: {e}")

    def reset(self):
        """Put mpv back to normal playback (speed, pause, sound) and take the bar down."""
        self.direction = 0
        self.paused = False
        self._set("speed", 1.0)
        self._set("mute", False)
        self.hide()

    # ---- internals ----
    def _scanning(self):
        return self.direction == -1 or (self.direction == 1 and SPEEDS[self.level] not in SMOOTH_FF)

    def _apply_speed(self):
        speed = SPEEDS[self.level]
        self._set("mute", True)
        if self.direction == 1 and speed in SMOOTH_FF:
            self._set("speed", float(speed))
            self._set("pause", False)
        else:
            if self.direction == 1 and SPEEDS[self.level - 1] in SMOOTH_FF and self.level:
                # coming up from a smooth speed - mpv has been playing, so ask it where
                self.position = self._get("time-pos") or self.position
            self._set("speed", 1.0)
            self._set("pause", True)
            self._last_scan = time.time()

    def _stop_scan(self):
        if self._scanning():
            # carry on from where the scan got to, at the exact frame
            self._seek(self.position, exact=True)
        self.direction = 0
        self.level = 0
        self._last_scan = 0.0
        self._set("speed", 1.0)
        self._set("mute", False)

    def _play(self, seek=True):
        if seek:
            self._stop_scan()
        else:
            self.direction = 0
            self.level = 0
            self._last_scan = 0.0
            self._set("speed", 1.0)
            self._set("mute", False)
        self.paused = False
        self._set("pause", False)
        self._hide_at = time.time() + BAR_SECONDS

    def _seek(self, where, exact=False):
        try:
            self.mpv.command("seek", where, "absolute+exact" if exact else "absolute+keyframes")
        except Exception as e:
            _l.debug(f"Seek to {where} failed: {e}")

    def _get(self, prop):
        try:
            return self.mpv.command("get_property", prop)
        except Exception:
            return None

    def _set(self, prop, value):
        try:
            self.mpv.command("set_property", prop, value)
        except Exception as e:
            _l.debug(f"Could not set {prop}: {e}")

    def draw(self):
        try:
            dims = self._get("osd-dimensions") or {}
            canvas_w = round(CANVAS_H * (dims.get("aspect") or 16 / 9))
            duration = self._get("duration") or 0
            position = self.position if self._scanning() else (self._get("time-pos") or 0)
            right = canvas_w - LEFT
            width = right - LEFT
            top = CANVAS_H - BOTTOM_GAP - BAR_H
            events = [
                # the box, with an orange edge down the left like the channel banner
                f"{{\\an7\\pos({LEFT},{top})\\bord0\\shad0\\1c{NAVY}\\1a&H30&\\p1}}"
                f"m 0 0 l {width} 0 {width} {BAR_H} 0 {BAR_H}{{\\p0}}",
                f"{{\\an7\\pos({LEFT},{top})\\bord0\\shad0\\1c{ORANGE}\\p1}}"
                f"m 0 0 l 10 0 10 {BAR_H} 0 {BAR_H}{{\\p0}}",
            ]
            # the mode: an icon and a word
            icon_x, icon_y = LEFT + 44, top + 26
            events.append(f"{{\\an7\\pos({icon_x},{icon_y})\\bord0\\shad0\\1c{WHITE}\\p1}}{self._icon()}{{\\p0}}")
            label = self._label()
            text_x = icon_x + 86
            events.append(f"{{\\an4\\pos({text_x},{top + 44})\\fnArial\\fs40\\b1\\bord0\\shad0\\1c{ORANGE}}}"
                          f"{_ass_text(label)}")
            events.append(f"{{\\an4\\pos({text_x + 190},{top + 44})\\fnArial\\fs36\\b0\\bord0\\shad0\\1c{WHITE}\\q2}}"
                          f"{_ass_text(self.title if len(self.title) <= 48 else self.title[:46] + '…')}")
            # times, and the progress track under them
            times = f"{_clock(position)} / {_clock(duration)}" if duration else _clock(position)
            events.append(f"{{\\an6\\pos({right - 34},{top + 44})\\fnArial\\fs34\\b0\\bord0\\shad0\\1c{MUTED}}}"
                          f"{_ass_text(times)}")
            track_x, track_y = text_x, top + 80
            track_w = right - 34 - track_x
            done = round(track_w * min(1, position / duration)) if duration else 0
            events.append(f"{{\\an7\\pos({track_x},{track_y})\\bord0\\shad0\\1c{WHITE}\\1a&HB0&\\p1}}"
                          f"m 0 0 l {track_w} 0 {track_w} {TRACK_H} 0 {TRACK_H}{{\\p0}}")
            if done > 0:
                events.append(f"{{\\an7\\pos({track_x},{track_y})\\bord0\\shad0\\1c{ORANGE}\\p1}}"
                              f"m 0 0 l {done} 0 {done} {TRACK_H} 0 {TRACK_H}{{\\p0}}")
            self.mpv.command("osd-overlay", OVERLAY_ID, "ass-events", "\n".join(events),
                             canvas_w, CANVAS_H, 0, False)
            self._shown = True
        except Exception as e:
            _l.warning(f"Could not draw the trick play bar: {e}")

    def _label(self):
        if self.direction == 1:
            return f"FF  {SPEEDS[self.level]}x"
        if self.direction == -1:
            return f"REW  {SPEEDS[self.level]}x"
        return "PAUSED" if self.paused else "PLAY"

    def _icon(self):
        # ASS vector drawings, about 60x60
        if self.paused and not self.direction:
            return "m 4 0 l 22 0 22 60 4 60 m 38 0 l 56 0 56 60 38 60"
        if self.direction == 1:
            return "m 0 0 l 30 30 0 60 m 30 0 l 60 30 30 60"
        if self.direction == -1:
            return "m 30 0 l 0 30 30 60 m 60 0 l 30 30 60 60"
        return "m 8 0 l 56 30 8 60"
