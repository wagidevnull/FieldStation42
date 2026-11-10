import logging
import threading

# Quick audio / subtitle picker - the yellow (audio) and blue (subtitles) buttons.
# The first press shows the choices with the current one marked; each press after
# that, while the list is up, moves to the next choice and switches to it.
# Drawn with mpv's OSD like the channel banner.

PICKER_SECONDS = 4
OVERLAY_ID = 43
CANVAS_H = 1080
# rows shown at once - a longer list scrolls to keep the current choice in view
MAX_ROWS = 10

# ASS colours are &HBBGGRR&
NAVY = "&H501E0A&"
ORANGE = "&H00AAFF&"
WHITE = "&HFFFFFF&"
YELLOW = "&H00D7FF&"
BLUE = "&HE07A2A&"

KINDS = {
    "audio": {"track_type": "audio", "property": "aid", "label": "Audio", "color": YELLOW},
    "sub": {"track_type": "sub", "property": "sid", "label": "Subtitles", "color": BLUE},
}

LANGUAGES = {
    "en": "English", "eng": "English", "es": "Spanish", "spa": "Spanish",
    "fr": "French", "fre": "French", "fra": "French", "de": "German", "ger": "German", "deu": "German",
    "it": "Italian", "ita": "Italian", "pt": "Portuguese", "por": "Portuguese",
    "ru": "Russian", "rus": "Russian", "ja": "Japanese", "jpn": "Japanese",
    "zh": "Chinese", "chi": "Chinese", "zho": "Chinese", "ko": "Korean", "kor": "Korean",
    "ar": "Arabic", "ara": "Arabic", "nl": "Dutch", "dut": "Dutch", "nld": "Dutch",
    "sv": "Swedish", "swe": "Swedish", "pl": "Polish", "pol": "Polish",
    "hi": "Hindi", "hin": "Hindi", "tr": "Turkish", "tur": "Turkish",
}

_l = logging.getLogger("TrackPicker")


def _ass_text(text):
    return str(text).replace("\\", "/").replace("{", "(").replace("}", ")").replace("\n", " ")


def track_label(track):
    """Short viewer-facing name for an mpv track-list entry."""
    lang = (track.get("lang") or "").lower()
    name = LANGUAGES.get(lang, lang.upper() if lang else "")
    title = track.get("title") or ""
    if title.lower() in LANGUAGES or title.lower() == name.lower():
        title = ""  # "Eng" on an English track says nothing new
    if track.get("external") and title.lower().endswith((".srt", ".ass", ".ssa", ".vtt", ".sub")):
        # sidecar files get their filename suffix as a title, e.g. "es.hi.srt"
        parts = title.lower().split(".")
        title = "SDH" if {"hi", "sdh", "cc"} & set(parts) else ""
    if name and title:
        # a title that already names the language ("English (SDH)") says it best
        return title if name.lower() in title.lower() else f"{name} - {title}"
    return name or title or f"Track {track.get('id')}"


def tracks(mpv, kind):
    track_type = KINDS[kind]["track_type"]
    return [t for t in (mpv.command("get_property", "track-list") or []) if t.get("type") == track_type]


def current_label(mpv, kind):
    """What the banner shows next to the yellow / blue key."""
    try:
        for t in tracks(mpv, kind):
            if t.get("selected"):
                return track_label(t)
        return "Off" if kind == "sub" else "None"
    except Exception:
        return ""


class TrackPicker:
    def __init__(self, mpv):
        self.mpv = mpv
        self._lock = threading.Lock()
        self._timer = None
        self._open_kind = None
        # called when the list opens and when it closes - the channel bug steps aside
        # meanwhile, since mpv draws image overlays (the bug) above any OSD text
        self.on_open = None
        self.on_close = None

    def press(self, kind):
        if kind not in KINDS:
            return
        with self._lock:
            try:
                choices = self._choices(kind)
                if not choices:
                    return
                current = next((i for i, c in enumerate(choices) if c["selected"]), 0)
                if self._open_kind == kind:
                    # list already up - this press moves on and switches
                    current = (current + 1) % len(choices)
                    self.mpv.command("set_property", KINDS[kind]["property"], choices[current]["value"])
                    for i, c in enumerate(choices):
                        c["selected"] = i == current
                if self._open_kind is None and self.on_open:
                    self.on_open()
                self._draw(kind, choices)
                self._open_kind = kind
                self._restart_timer()
            except Exception as e:
                _l.warning(f"Could not show {kind} picker: {e}")

    def hide(self):
        with self._lock:
            self._hide_locked()

    def _hide_locked(self):
        if self._timer:
            self._timer.cancel()
            self._timer = None
        was_open = self._open_kind is not None
        self._open_kind = None
        try:
            self.mpv.command("osd-overlay", OVERLAY_ID, "none", "")
        except Exception as e:
            _l.debug(f"Could not hide track picker: {e}")
        if was_open and self.on_close:
            self.on_close()

    def _restart_timer(self):
        if self._timer:
            self._timer.cancel()
        self._timer = threading.Timer(PICKER_SECONDS, self.hide)
        self._timer.daemon = True
        self._timer.start()

    def _choices(self, kind):
        choices = [
            {"value": t["id"], "label": track_label(t), "selected": bool(t.get("selected"))}
            for t in tracks(self.mpv, kind)
        ]
        if kind == "sub":
            # subtitles can always be turned off
            choices.insert(0, {"value": "no", "label": "Off", "selected": not any(c["selected"] for c in choices)})
        return choices

    def _draw(self, kind, choices):
        dims = self.mpv.command("get_property", "osd-dimensions")
        canvas_w = round(CANVAS_H * dims["aspect"])
        info = KINDS[kind]
        line_h = 50
        width = 620
        current = next((i for i, c in enumerate(choices) if c["selected"]), 0)
        rows = min(len(choices), MAX_ROWS)
        # the window of rows on screen, keeping the current choice in the middle where it can
        first = min(max(0, current - rows // 2), len(choices) - rows)
        more_above, more_below = first, len(choices) - first - rows
        # room for the "more" markers above and below a list that scrolls
        top_pad = 40 if len(choices) > rows else 0
        height = 90 + top_pad * 2 + line_h * rows
        x = canvas_w - width - 50
        y = CANVAS_H - height - 60

        events = [
            f"{{\\an7\\pos({x},{y})\\bord0\\shad0\\1c{NAVY}\\1a&H18&\\p1}}"
            f"m 0 0 l {width} 0 {width} {height} 0 {height}{{\\p0}}",
            f"{{\\an7\\pos({x},{y})\\bord0\\shad0\\1c{info['color']}\\p1}}"
            f"m 0 0 l {width} 0 {width} 6 0 6{{\\p0}}",
            # the coloured dot says which remote button this is
            f"{{\\an7\\pos({x + 28},{y + 30})\\bord0\\shad0\\1c{info['color']}\\p1}}"
            f"m 14 0 b 22 0 28 6 28 14 b 28 22 22 28 14 28 b 6 28 0 22 0 14 b 0 6 6 0 14 0{{\\p0}}",
            f"{{\\an7\\pos({x + 72},{y + 22})\\fnArial\\b1\\fs40\\bord0\\shad0\\1c{WHITE}}}{info['label']}",
        ]
        if len(choices) > rows:
            for marker_y, count, arrow in ((y + 76, more_above, "▲"), (y + height - 50, more_below, "▼")):
                if count:
                    events.append(
                        f"{{\\an8\\pos({x + width // 2},{marker_y})\\fnArial\\fs30\\bord0\\shad0\\1c{info['color']}}}"
                        f"{arrow} {count} more"
                    )
        for i, c in enumerate(choices[first:first + rows]):
            row_y = y + 82 + top_pad + i * line_h
            if c["selected"]:
                events.append(
                    f"{{\\an7\\pos({x + 16},{row_y - 4})\\bord0\\shad0\\1c{ORANGE}\\p1}}"
                    f"m 0 0 l {width - 32} 0 {width - 32} {line_h - 4} 0 {line_h - 4}{{\\p0}}"
                )
            color = NAVY if c["selected"] else WHITE
            mark = "▶ " if c["selected"] else "   "
            events.append(
                f"{{\\an7\\pos({x + 30},{row_y})\\fnArial\\b{1 if c['selected'] else 0}\\fs36\\bord0\\shad0\\1c{color}}}"
                f"{mark}{_ass_text(c['label'])}"
            )
        self.mpv.command("osd-overlay", OVERLAY_ID, "ass-events", "\n".join(events), canvas_w, CANVAS_H, 1, False)
