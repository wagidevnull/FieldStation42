import datetime
import json
import logging
import os
import random
import tempfile

# Viewer-facing settings changed from the on-TV settings menu. They live in runtime/
# rather than confs/ because every json file in confs/ is loaded as a station.
SETTINGS_PATH = "runtime/user_settings.json"

# Sub-menus of the settings menu. A setting with "group" goes in that group's
# sub-menu; the rest sit on the main menu.
SETTINGS_GROUPS = [
    {
        "key": "video",
        "label": "Video",
        "description": "The shape of the TV and how the picture fills it - aspect ratio and picture size.",
    },
    {
        "key": "sound",
        "label": "Sound",
        "description": "Which audio track plays, and evening out the volume between shows, ads and movies.",
    },
    {
        "key": "appearance",
        "label": "Appearance",
        "description": "How the guide and on-screen graphics look - logos, guide theme, the channel logo bug and the channel banner.",
    },
    {
        "key": "weather",
        "label": "Weather",
        "description": "The current conditions shown at the top of the guide - on or off, in °F or °C, and the ZIP code they're for.",
    },
]

# Each entry is one row in the settings menu - add an entry here to add a setting.
SETTINGS_SCHEMA = [
    {
        "key": "aspect_ratio",
        "group": "video",
        "label": "Aspect Ratio",
        "description": "Shape of the TV this is connected to. Use 4:3 for a CRT, 16:9 for a widescreen TV.",
        "default": "16:9",
        "options": [
            {"value": "16:9", "label": "16:9 Widescreen"},
            {"value": "4:3", "label": "4:3 Standard"},
        ],
    },
    {
        "key": "picture_size",
        "group": "video",
        "label": "Picture Size",
        "description": "Zoom fills the screen by trimming the edges of the picture. Use it to get rid of black bars, like widescreen video on a 4:3 TV.",
        "default": "normal",
        "options": [
            {"value": "normal", "label": "Normal"},
            {"value": "zoom", "label": "Zoom to Fill"},
        ],
    },
    {
        "key": "provider_logo",
        "group": "appearance",
        "label": "Provider Logo",
        "description": "The TV provider logo shown on the guide and in this menu. Random shows a different one each time the guide opens.",
        "default": "directv.svg",
        # values are files in fs42/fs42_server/static/customguide/logos/ - or
        # "random", which picks one of them (see pick_provider_logo)
        "options": [
            {"value": "directv.svg", "label": "DirecTV"},
            {"value": "comcast.svg", "label": "Comcast"},
            {"value": "dish.svg", "label": "Dish Network"},
            {"value": "random", "label": "Random"},
        ],
    },
    {
        "key": "guide_theme",
        "group": "appearance",
        "label": "Guide Theme",
        "description": "The look of the channel guide. Open the list to see what each theme looks like.",
        "default": "default",
        # values other than default name a stylesheet in customguide/themes/ laid over the
        # base theme. "seasonal" ones belong to a time of year: with Seasonal Themes on,
        # the guide never falls back to one between seasons (see everyday_theme). An
        # option's "description" shows while the cursor is on it in the menu's list
        "options": [
            {"value": "default", "label": "Default",
             "description": "The classic blue guide."},
            {"value": "halloween", "label": "Halloween", "seasonal": True,
             "description": "A haunted night sky, slime around the picture and pumpkins along the bottom."},
            {"value": "frutiger", "label": "Frutiger Aero",
             "description": "Dark glass over a sunny meadow, with a glass frame around the picture."},
            {"value": "fall", "label": "Fall", "seasonal": True,
             "description": "A leafy street in muted oranges and browns, with fall leaves heaped around the picture."},
            {"value": "winter", "label": "Winter", "seasonal": True,
             "description": "A snowy porch, icicles on the logos and blinking Christmas lights around the picture."},
            {"value": "directv", "label": "DirecTV",
             "description": "The satellite box's own guide and On Demand screens: white and blue, Trade Gothic, the selected show in orange."},
        ],
    },
    {
        "key": "seasonal_themes",
        "group": "appearance",
        "label": "Seasonal Themes",
        "description": "Changes the guide theme with the calendar: Frutiger Aero in spring, Fall from late September, Halloween for October's last three weeks, Fall again until Thanksgiving, then Winter until January 20. Between seasons the guide uses the everyday (non-seasonal) theme you last picked as the Guide Theme.",
        "default": "off",
        # see SEASONS and guide_look()
        "options": [
            {"value": "off", "label": "Off"},
            {"value": "on", "label": "On"},
        ],
    },
    {
        "key": "audio_language",
        "group": "sound",
        "label": "Audio Language",
        "description": "English plays the English audio track whenever an episode has one, even if the file marks a dub as its default.",
        "default": "english",
        "options": [
            {"value": "english", "label": "English"},
            {"value": "file", "label": "File Default"},
        ],
    },
    {
        "key": "subtitles",
        "label": "Subtitles",
        "description": "Which subtitles come on when an episode starts. The blue button changes them for the episode you're watching.",
        "default": "off",
        "options": [
            {"value": "off", "label": "Off"},
            {"value": "english", "label": "English"},
            {"value": "file", "label": "File Default"},
        ],
    },
    {
        "key": "audio_normalize",
        "group": "sound",
        "label": "Audio Normalization",
        "description": "Evens out loudness differences between shows, ads, and movies, keeping them at an equal volume.",
        "default": "off",
        "options": [
            {"value": "off", "label": "Off"},
            {"value": "on", "label": "On"},
        ],
    },
    {
        "key": "channel_bug",
        "group": "appearance",
        "label": "Channel Logo Bug",
        "description": "Show the channel's logo faintly in the bottom right corner while a show is on, like a real network.",
        "default": "on",
        "options": [
            {"value": "on", "label": "On"},
            {"value": "off", "label": "Off"},
        ],
    },
    {
        "key": "channel_banner",
        "group": "appearance",
        "label": "Channel Banner",
        "description": "Show the channel, what's on and the time slot across the top of the screen for a few seconds whenever a channel is tuned.",
        "default": "on",
        "options": [
            {"value": "on", "label": "On"},
            {"value": "off", "label": "Off"},
        ],
    },
    {
        "key": "weather_display",
        "group": "weather",
        "label": "Weather Display",
        "description": "Show the current conditions and temperature at the top of the guide, beside the date and time.",
        "default": "on",
        "options": [
            {"value": "on", "label": "On"},
            {"value": "off", "label": "Off"},
        ],
    },
    {
        "key": "weather_units",
        "group": "weather",
        "label": "Temperature Units",
        "description": "Show the temperature in degrees Fahrenheit or Celsius.",
        "default": "F",
        "options": [
            {"value": "F", "label": "°F Fahrenheit"},
            {"value": "C", "label": "°C Celsius"},
        ],
    },
    {
        "key": "weather_zip",
        "group": "weather",
        "label": "ZIP Code",
        "description": "The US ZIP code the weather is for. Press OK, type the five digits with the number keys, then OK to save. Left erases a digit.",
        "default": "98604",
        # typed in rather than picked from options: exactly `digits` number keys
        "digits": 5,
    },
]

_l = logging.getLogger("UserSettings")


def _schema_entry(key):
    for entry in SETTINGS_SCHEMA:
        if entry["key"] == key:
            return entry
    return None


_last_random_logo = None


def pick_provider_logo():
    """The provider logo file to show now: the setting's, or for Random one of the
    logos - never the same one twice running, so each guide looks different."""
    global _last_random_logo
    value = load_settings()["provider_logo"]
    if value != "random":
        return value
    files = [o["value"] for o in _schema_entry("provider_logo")["options"] if o["value"] != "random"]
    choices = [f for f in files if f != _last_random_logo] or files
    _last_random_logo = random.choice(choices)
    return _last_random_logo


# The looks Seasonal Themes switches between, first match wins. Each runs from its
# start date to its end date, both included; a season whose end comes before its
# start (Winter) runs over New Year. "thanksgiving" is the fourth Thursday of
# November and "after_thanksgiving" the Friday after it. A look whose stylesheet
# isn't in customguide/themes/ yet (summer) is skipped, so that season falls back
# to the Guide Theme setting until it's made.
SEASONS = [
    ("frutiger", (3, 16), (6, 4)),
    ("summer", (6, 5), (8, 31)),
    ("fall", (9, 25), (10, 10)),
    ("halloween", (10, 11), (10, 31)),
    ("fall", (11, 1), "thanksgiving"),
    ("winter", "after_thanksgiving", (1, 20)),
]

THEMES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fs42_server", "static", "customguide", "themes")


def _season_date(when, year):
    if when in ("thanksgiving", "after_thanksgiving"):
        first = datetime.date(year, 11, 1)
        # weekday() counts Monday as 0, so Thursday is 3
        thanksgiving = first + datetime.timedelta(days=(3 - first.weekday()) % 7 + 21)
        return thanksgiving + datetime.timedelta(days=1 if when == "after_thanksgiving" else 0)
    return datetime.date(year, *when)


def _in_season(today, start, end):
    begin = _season_date(start, today.year)
    finish = _season_date(end, today.year)
    if begin <= finish:
        return begin <= today <= finish
    # runs over New Year: either this year's start onward, or up to this year's end
    return today >= begin or today <= finish


def guide_look(today=None):
    """The look the guide should wear today. With Seasonal Themes off, the Guide
    Theme. With it on, the season's look when today falls in one (and that look
    exists), otherwise the everyday theme picked most recently."""
    settings = load_settings()
    if settings["seasonal_themes"] != "on":
        return settings["guide_theme"]
    today = today or datetime.date.today()
    for look, start, end in SEASONS:
        if _in_season(today, start, end) and os.path.exists(os.path.join(THEMES_DIR, f"{look}.css")):
            return look
    return settings["everyday_theme"]


def _everyday_themes():
    return [o["value"] for o in _schema_entry("guide_theme")["options"] if not o.get("seasonal")]


def _valid(entry, value):
    """Whether a value is one this setting can take: one of its options, or for a
    typed-in setting, exactly its number of digits."""
    if "digits" in entry:
        return isinstance(value, str) and len(value) == entry["digits"] and value.isdigit()
    return value in {o["value"] for o in entry["options"]}


def load_settings():
    """All settings, with defaults filled in for anything unset or no longer valid."""
    stored = {}
    if os.path.exists(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH) as f:
                stored = json.load(f)
        except Exception as e:
            _l.warning(f"Could not read {SETTINGS_PATH}, using defaults: {e}")

    settings = {}
    for entry in SETTINGS_SCHEMA:
        value = stored.get(entry["key"], entry["default"])
        settings[entry["key"]] = value if _valid(entry, value) else entry["default"]

    # not in the menu: the everyday (non-seasonal) Guide Theme picked most recently -
    # what the guide wears between seasons, and with Seasonal Themes off whenever the
    # Guide Theme itself is an everyday one
    everyday = _everyday_themes()
    if settings["guide_theme"] in everyday:
        settings["everyday_theme"] = settings["guide_theme"]
    else:
        remembered = stored.get("everyday_theme")
        settings["everyday_theme"] = remembered if remembered in everyday else "default"
    return settings


def save_setting(key, value):
    """Validate and store one setting. Raises ValueError for an unknown key or value."""
    entry = _schema_entry(key)
    if entry is None:
        raise ValueError(f"Unknown setting '{key}'")
    if not _valid(entry, value):
        raise ValueError(f"'{value}' is not a valid value for '{key}'")

    settings = load_settings()
    settings[key] = value
    if key == "guide_theme" and value in _everyday_themes():
        settings["everyday_theme"] = value

    # write to a temp file and rename so a reader never sees a half-written file
    os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(SETTINGS_PATH), suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(settings, f, indent=2)
    os.replace(tmp_path, SETTINGS_PATH)
    return settings
