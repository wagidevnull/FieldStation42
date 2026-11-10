import datetime
import logging
import os
import threading
import time

from fs42.track_picker import YELLOW, BLUE, current_label

# The channel banner shown across the top of the screen when a channel is tuned.
# It is drawn by mpv's own OSD (an ASS overlay), so it sits on the video itself -
# no extra window to fight the window manager over - and it follows the screen
# aspect ratio from the settings menu the same way the video does.

BANNER_SECONDS = 6
OVERLAY_ID = 42
# a hidden overlay used only to measure how wide a piece of text renders
MEASURE_OVERLAY_ID = 44  # 43 is the track picker
LOGO_OVERLAY_ID = 0
LOGO_RAW_PATH = "runtime/banner_logo.bgra"
# channel_logo in a station config names a file here - the web server serves the
# same folder at /static/logos/, so the guide shows the same logo
LOGO_DIR = "fs42/fs42_server/static/logos"

# layout is worked out on a canvas 1080 high; its width follows the screen shape
CANVAS_H = 1080
BAND_H = 215
LOGO_BOX = (40, 32, 230, 150)  # x, y, w, h
# the Audio/Subtitles values get this share of the width - longer track names scroll
TRACK_VALUE_SHARE = 0.2
TRACK_FONT = "\\fnArial\\fs34\\bord2\\shad0"
TITLE_FONT = "\\fnArial\\b1\\fs64\\bord3\\shad0"
TITLE_GAP = 40  # room kept between the title and what's either side of it
SCROLL_FPS = 30
SCROLL_SPEED = 90  # canvas pixels a second
SCROLL_PAUSE = 1.2  # seconds held at each end

# ASS colours are &HBBGGRR& and alpha is 00 (solid) to FF (clear)
NAVY = "&H501E0A&"
ORANGE = "&H00AAFF&"
WHITE = "&HFFFFFF&"
MUTED = "&HEAC8B9&"

_l = logging.getLogger("ChannelBanner")


def _ass_text(text):
    # keep viewer-facing strings from being read as ASS override tags
    return str(text).replace("\\", "/").replace("{", "(").replace("}", ")").replace("\n", " ")


def logo_file(logo_name):
    """Path of a channel_logo from a station config, or None if it isn't there."""
    if not logo_name:
        return None
    path = os.path.join(LOGO_DIR, os.path.basename(logo_name))
    return path if os.path.isfile(path) else None


def short_time(when):
    # 11:00p style, like a satellite box banner
    return when.strftime("%I:%M").lstrip("0") + ("a" if when.hour < 12 else "p")


class ChannelBanner:
    def __init__(self, mpv):
        self.mpv = mpv
        self._timer = None
        self._lock = threading.Lock()
        self.showing = False
        # bumped on every show/hide, so a scroll thread from an earlier banner stops
        self._generation = 0

    def show(self, station_config, block=None, now=None):
        now = now or datetime.datetime.now()
        try:
            dims = self.mpv.command("get_property", "osd-dimensions")
            # canvas width matches the shape the screen is set to, so nothing gets stretched
            canvas_w = round(CANVAS_H * dims["aspect"])
            tracks = self._track_rows(canvas_w)
            title = self._title_row(station_config, block, canvas_w, tracks)
            tracks = tracks + [title]
            with self._lock:
                self._cancel_timer()
                self._generation += 1
                self._draw(station_config, block, now, canvas_w, tracks, 0.0)
                self._show_logo(station_config.get("channel_logo"), dims, canvas_w)
                self._timer = threading.Timer(BANNER_SECONDS, self.hide)
                self._timer.daemon = True
                self._timer.start()
                self.showing = True
                if any(t["overflow"] for t in tracks):
                    scroller = threading.Thread(
                        target=self._scroll,
                        args=(self._generation, station_config, block, now, canvas_w, tracks),
                        daemon=True,
                    )
                    scroller.start()
        except Exception as e:
            _l.warning(f"Could not show channel banner: {e}")

    def _draw(self, station_config, block, now, canvas_w, tracks, elapsed):
        events = self._events(station_config, block, now, canvas_w, tracks, elapsed)
        self.mpv.command(
            "osd-overlay", OVERLAY_ID, "ass-events", "\n".join(events),
            canvas_w, CANVAS_H, 0, False,
        )

    def _scroll(self, generation, station_config, block, now, canvas_w, tracks):
        # mpv doesn't animate OSD overlays, so redraw the banner with the long track
        # names slid along a little each frame
        start = time.monotonic()
        while True:
            time.sleep(1 / SCROLL_FPS)
            with self._lock:
                if generation != self._generation or not self.showing:
                    return
                try:
                    self._draw(station_config, block, now, canvas_w, tracks, time.monotonic() - start)
                except Exception as e:
                    _l.debug(f"Banner scroll stopped: {e}")
                    return

    def _text_width(self, ass_text, canvas_w):
        # render the text into a hidden overlay and ask mpv how wide it came out
        try:
            res = self.mpv.command(
                "osd-overlay", MEASURE_OVERLAY_ID, "ass-events", ass_text,
                canvas_w, CANVAS_H, 0, True, True,
            )
            self.mpv.command("osd-overlay", MEASURE_OVERLAY_ID, "none", "")
            if res and "x0" in res:
                return res["x1"] - res["x0"]
        except Exception as e:
            _l.debug(f"Could not measure banner text: {e}")
        return 0

    def _track_rows(self, canvas_w):
        """The Audio and Subtitles rows, with how much each value has to scroll."""
        box = round(canvas_w * TRACK_VALUE_SHARE)
        rows = []
        for row_y, color, label, kind in ((40, YELLOW, "Audio", "audio"), (100, BLUE, "Subtitles", "sub")):
            value = _ass_text(current_label(self.mpv, kind))
            width = self._text_width(f"{{\\an7\\pos(0,0){TRACK_FONT}\\b1}}{value}", canvas_w)
            rows.append({
                "y": row_y, "color": color, "label": label, "value": value,
                "width": min(width, box) if width else box, "overflow": max(0, width - box),
            })
        return rows

    def _title_row(self, station_config, block, canvas_w, tracks):
        """What's on, with the space it has between the channel name on the left and
        the Audio/Subtitles box on the right - a longer title scrolls inside it."""
        title = block.title if block is not None and block.title else station_config.get("network_name", "")
        value = _ass_text(title)
        lx, ly, lw, lh = LOGO_BOX
        info_x = lx + lw + 30
        left = info_x + max(
            self._text_width(f"{{\\an7\\pos(0,0)\\fnArial\\b1\\fs96\\bord3}}{_ass_text(station_config.get('channel_number', ''))}", canvas_w),
            self._text_width(f"{{\\an7\\pos(0,0)\\fnArial\\b1\\fs40\\bord2}}{_ass_text(station_config.get('network_name', ''))}", canvas_w),
        ) + TITLE_GAP
        right = canvas_w - 40
        for row in tracks:
            label = self._text_width(f"{{\\an7\\pos(0,0){TRACK_FONT}}}\u25CF {row['label']}", canvas_w)
            right = min(right, canvas_w - 40 - row["width"] - 14 - label - TITLE_GAP)
        # stay centred on the screen like a short title, as wide as both sides allow
        mid = canvas_w // 2
        half = max(100, min(mid - left, right - mid))
        width = self._text_width(f"{{\\an7\\pos(0,0){TITLE_FONT}}}{value}", canvas_w)
        x0, x1 = mid - half, mid + half
        if width > x1 - x0:
            # too long to stay centred: take all the room between the two sides
            x0, x1 = left, max(left + 200, right)
        box = x1 - x0
        return {"title": True, "value": value, "x0": x0, "x1": x1,
                "width": min(width, box) if width else box, "overflow": max(0, width - box)}

    @staticmethod
    def _scroll_offset(overflow, elapsed):
        # hold, slide to the end, hold, jump back to the start - and round again
        if not overflow:
            return 0
        travel = overflow / SCROLL_SPEED
        t = elapsed % (travel + 2 * SCROLL_PAUSE)
        if t < SCROLL_PAUSE:
            return 0
        if t < SCROLL_PAUSE + travel:
            return (t - SCROLL_PAUSE) * SCROLL_SPEED
        return overflow

    def hide(self):
        with self._lock:
            self._cancel_timer()
            self._generation += 1
            self.showing = False
            try:
                self.mpv.command("osd-overlay", OVERLAY_ID, "none", "")
                self.mpv.command("overlay-remove", LOGO_OVERLAY_ID)
            except Exception as e:
                _l.debug(f"Could not hide channel banner: {e}")

    def _cancel_timer(self):
        if self._timer:
            self._timer.cancel()
            self._timer = None

    def _events(self, station_config, block, now, canvas_w, tracks, elapsed=0.0):
        events = []
        # the band itself, with an orange rule along the bottom
        events.append(
            f"{{\\an7\\pos(0,0)\\bord0\\shad0\\1c{NAVY}\\1a&H30&\\p1}}"
            f"m 0 0 l {canvas_w} 0 {canvas_w} {BAND_H} 0 {BAND_H}{{\\p0}}"
        )
        events.append(
            f"{{\\an7\\pos(0,{BAND_H})\\bord0\\shad0\\1c{ORANGE}\\p1}}"
            f"m 0 0 l {canvas_w} 0 {canvas_w} 5 0 5{{\\p0}}"
        )

        # top left: logo spot, then channel number and name beside it
        lx, ly, lw, lh = LOGO_BOX
        if not logo_file(station_config.get("channel_logo")):
            # an empty frame keeps the layout steady until a logo is added
            events.append(
                f"{{\\an7\\pos({lx},{ly})\\bord0\\shad0\\1c&H8A4A1E&\\1a&H40&\\p1}}"
                f"m 0 0 l {lw} 0 {lw} {lh} 0 {lh}{{\\p0}}"
            )
        info_x = lx + lw + 30
        events.append(
            f"{{\\an7\\pos({info_x},{ly - 6})\\fnArial\\b1\\fs96\\bord3\\shad0\\3c{NAVY}\\1c{WHITE}}}"
            f"{_ass_text(station_config.get('channel_number', ''))}"
        )
        events.append(
            f"{{\\an7\\pos({info_x},{ly + 102})\\fnArial\\b1\\fs40\\bord2\\shad0\\3c{NAVY}\\1c{MUTED}}}"
            f"{_ass_text(station_config.get('network_name', ''))}"
        )

        # top middle: what's on, then the date and time, then the time slot
        mid = canvas_w // 2
        title = next(row for row in tracks if row.get("title"))
        if title["overflow"]:
            # too long for the space between the channel name and the track box: it
            # starts at the left of that space and scrolls, clipped to it
            offset = self._scroll_offset(title["overflow"], elapsed)
            events.append(
                f"{{\\an7\\pos({title['x0'] - offset:.1f},26){TITLE_FONT}"
                f"\\clip({title['x0'] - 4},10,{title['x1'] + 4},103)\\3c{NAVY}\\1c{ORANGE}}}"
                f"{title['value']}"
            )
        else:
            events.append(
                f"{{\\an8\\pos({mid},26){TITLE_FONT}\\3c{NAVY}\\1c{ORANGE}}}"
                f"{title['value']}"
            )
        events.append(
            f"{{\\an8\\pos({mid},104)\\fnArial\\b0\\fs40\\bord2\\shad0\\3c{NAVY}\\1c{WHITE}}}"
            f"{now.strftime('%a %m/%d').upper()}   {short_time(now)}"
        )
        if block is not None:
            events.append(
                f"{{\\an8\\pos({mid},154)\\fnArial\\b1\\fs40\\bord2\\shad0\\3c{NAVY}\\1c{WHITE}}}"
                f"{short_time(block.start_time)} - {short_time(block.end_time)}"
            )

        # top right: what the yellow and blue buttons change, and what they're on now
        # a value too long for its box scrolls inside it rather than running into the title
        right = canvas_w - 40
        for row in tracks:
            if row.get("title"):
                continue
            x0 = right - row["width"]
            y = row["y"]
            events.append(
                f"{{\\an9\\pos({x0 - 14},{y}){TRACK_FONT}\\3c{NAVY}\\1c{MUTED}}}"
                f"{{\\1c{row['color']}}}\u25CF{{\\1c{MUTED}}} {row['label']}"
            )
            offset = self._scroll_offset(row["overflow"], elapsed)
            clip = f"\\clip({x0 - 4},{y - 10},{right + 4},{y + 50})" if row["overflow"] else ""
            events.append(
                f"{{\\an7\\pos({x0 - offset:.1f},{y}){TRACK_FONT}{clip}\\b1\\3c{NAVY}\\1c{WHITE}}}"
                f"{row['value']}"
            )
        return events

    def _show_logo(self, logo_name, dims, canvas_w):
        self.mpv.command("overlay-remove", LOGO_OVERLAY_ID)
        show_logo_overlay(self.mpv, LOGO_OVERLAY_ID, LOGO_RAW_PATH, logo_name, LOGO_BOX, dims, canvas_w)


def show_logo_overlay(mpv, overlay_id, raw_path, logo_name, box, dims, canvas_w, opacity=1.0, align="center"):
    """Draw a channel logo as an mpv image overlay, fitted into box (x, y, w, h on the
    1080-high canvas) - centred in it, or tucked into its bottom right corner."""
    # mpv draws raw images in real screen pixels, so map the canvas spot onto the
    # window - in 4:3 mode that widens the logo the same way the TV narrows it back
    logo_path = logo_file(logo_name)
    if not logo_path:
        return False
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    sx = dims["w"] / canvas_w
    sy = dims["h"] / CANVAS_H
    lx, ly, lw, lh = box

    svg = QSvgRenderer(logo_path) if logo_path.lower().endswith(".svg") else None
    source = None if svg else QImage(logo_path)
    size = svg.defaultSize() if svg else source.size()
    if size.isEmpty():
        _l.warning(f"Could not read channel logo {logo_path}")
        return False
    fit = min(lw / size.width(), lh / size.height())
    w = max(1, round(size.width() * fit * sx))
    h = max(1, round(size.height() * fit * sy))

    # premultiplied ARGB32 is laid out as B,G,R,A bytes - the format mpv's overlay takes
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)
    painter.setOpacity(opacity)
    if svg:
        svg.render(painter, QRectF(0, 0, w, h))
    else:
        painter.drawImage(QRectF(0, 0, w, h), source)
    painter.end()
    with open(raw_path, "wb") as f:
        f.write(bytes(img.constBits())[: img.sizeInBytes()])

    if align == "bottom-right":
        x = round((lx + lw) * sx) - w
        y = round((ly + lh) * sy) - h
    else:
        x = round((lx + (lw - w / sx) / 2) * sx)
        y = round((ly + (lh - h / sy) / 2) * sy)
    mpv.command(
        "overlay-add", overlay_id, x, y, os.path.abspath(raw_path), 0, "bgra", w, h, img.bytesPerLine()
    )
    return True
