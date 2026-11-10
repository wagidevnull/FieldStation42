import logging
import threading

from fs42 import user_settings
from fs42.channel_banner import CANVAS_H, show_logo_overlay

# The channel's logo, faint, in the bottom right corner while a show plays - the
# "bug" a real network keeps on screen. Drawn as an mpv image overlay like the
# banner's logo, so it sits on the video and follows the aspect ratio setting.

OVERLAY_ID = 1  # the banner's logo is 0
RAW_PATH = "runtime/bug_logo.bgra"
OPACITY = 0.55
# where the logo goes on the 1080-high canvas, measured in from the bottom right
# corner of the picture - far enough in that a CRT's overscan doesn't crop it. A 4:3
# show on a widescreen set has black bars at the sides, and the bug sits in the
# picture's corner rather than out on the bar, the way a 4:3 broadcast's own bug did
BOX_W, BOX_H = 170, 85
MARGIN_X, MARGIN_Y = 70, 60

_l = logging.getLogger("ChannelBug")


class ChannelBug:
    def __init__(self, mpv):
        self.mpv = mpv
        self._lock = threading.Lock()
        self._shown = None  # (logo, w, h, aspect, bars) of what's on screen now
        self._recheck = None
        # while something is drawn where the bug sits (the audio/subtitle list), it's
        # taken down and comes back afterwards - _conf is what to bring back
        self._suspended = False
        self._conf = None

    RECHECKS = (1.5, 3, 6)  # seconds after a show to look again

    def show(self, station_config, _recheck=0):
        """Show the station's logo, unless it's already up at this size and place."""
        logo = station_config.get("channel_logo")
        if not logo or user_settings.load_settings().get("channel_bug") == "off":
            self.hide()
            return
        self._conf = station_config
        if self._suspended:
            return
        with self._lock:
            try:
                dims = self.mpv.command("get_property", "osd-dimensions")
                # the black bars mpv leaves round the picture, in screen pixels
                bars = tuple(round(dims.get(k, 0)) for k in ("ml", "mr", "mt", "mb"))
                key = (logo, dims["w"], dims["h"], round(dims["aspect"], 3), bars)
                if key == self._shown:
                    self._schedule_recheck(station_config, _recheck)
                    return
                canvas_w = round(CANVAS_H * dims["aspect"])
                right_bar = bars[1] * canvas_w / dims["w"] if dims["w"] else 0
                bottom_bar = bars[3] * CANVAS_H / dims["h"] if dims["h"] else 0
                box = (round(canvas_w - right_bar - MARGIN_X - BOX_W), round(CANVAS_H - bottom_bar - MARGIN_Y - BOX_H),
                       BOX_W, BOX_H)
                self.mpv.command("overlay-remove", OVERLAY_ID)
                if show_logo_overlay(self.mpv, OVERLAY_ID, RAW_PATH, logo, box, dims, canvas_w,
                                     opacity=OPACITY, align="bottom-right"):
                    self._shown = key
                else:
                    self._shown = None
            except Exception as e:
                _l.warning(f"Could not show channel bug: {e}")
                return
            self._schedule_recheck(station_config, _recheck)

    def _schedule_recheck(self, station_config, done):
        # the window can still be settling (back from the guide's preview, or a new
        # aspect ratio), and a new file's bars aren't known until its first frame -
        # look again a few times and redraw if any of that has changed
        if self._recheck:
            self._recheck.cancel()
            self._recheck = None
        if done >= len(self.RECHECKS):
            return
        wait = self.RECHECKS[done] - (self.RECHECKS[done - 1] if done else 0)
        self._recheck = threading.Timer(wait, self._redraw_if_shown, args=(station_config, done + 1))
        self._recheck.daemon = True
        self._recheck.start()

    def _redraw_if_shown(self, station_config, done):
        if self._shown is not None:
            self.show(station_config, done)

    def suspend(self):
        """Take the bug down for now, remembering to bring it back on resume()."""
        with self._lock:
            if self._suspended:
                return
            self._suspended = True
            was_shown = self._shown is not None
            if self._recheck:
                self._recheck.cancel()
                self._recheck = None
            self._shown = None
            if not was_shown:
                self._conf = None
            try:
                self.mpv.command("overlay-remove", OVERLAY_ID)
            except Exception as e:
                _l.debug(f"Could not suspend channel bug: {e}")

    def resume(self):
        with self._lock:
            self._suspended = False
            conf = self._conf
        if conf is not None:
            self.show(conf)

    def hide(self):
        self._conf = None
        with self._lock:
            if self._recheck:
                self._recheck.cancel()
                self._recheck = None
            if self._shown is None:
                return
            self._shown = None
            try:
                self.mpv.command("overlay-remove", OVERLAY_ID)
            except Exception as e:
                _l.debug(f"Could not hide channel bug: {e}")
