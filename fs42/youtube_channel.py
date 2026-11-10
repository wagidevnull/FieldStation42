import datetime
import json
import logging
import os
import random
import re
import subprocess
import sys
import tempfile
import threading
import time

# A web channel that plays YouTube playlists on a real schedule. A station config
# with "youtube_playlists": [ids] gets one: the playlists are read with yt-dlp
# (titles and lengths only - nothing is downloaded), and each day gets a fixed
# shuffled lineup, saved so it doesn't change once made. The guide lists that
# lineup, and the channel's page plays whatever it says is on now, joining
# part-way through like any other channel.

CACHE_DIR = "runtime/youtube"
# seconds cut from the end of every video, so the channel moves on before the
# creator's end screen (channel icon, "watch next" tiles) shows - youtube_end_trim
# in the station config overrides it
END_TRIM = 20
REFRESH_SECONDS = 6 * 60 * 60

_l = logging.getLogger("YouTubeChannel")
_lock = threading.Lock()


def youtube_stations():
    from fs42.station_manager import StationManager
    return [s for s in StationManager().stations if s.get("youtube_playlists")]


def _station(network_name):
    for s in youtube_stations():
        if s["network_name"] == network_name:
            return s
    return None


def _write_json(path, data):
    # write to a temp file and rename so a reader never sees a half-written file
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
    os.replace(tmp_path, path)


def _read_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except Exception as e:
        _l.warning(f"Could not read {path}: {e}")
        return None


def _playlist_path(list_id):
    return os.path.join(CACHE_DIR, f"playlist_{list_id}.json")


def _ytdlp():
    # the venv's own yt-dlp - the system one is too old to read playlists
    local = os.path.join(os.path.dirname(sys.executable), "yt-dlp")
    return local if os.path.exists(local) else "yt-dlp"


def refresh_playlist(list_id):
    """Read a playlist's videos (id, title, length) with yt-dlp and cache them."""
    url = f"https://www.youtube.com/playlist?list={list_id}"
    result = subprocess.run(
        [_ytdlp(), "--flat-playlist", "-J", "--no-warnings", url],
        capture_output=True, text=True, timeout=600,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip()[-300:] or f"yt-dlp exited with {result.returncode}")
    data = json.loads(result.stdout)
    videos = [
        {"id": e["id"], "title": e.get("title") or "", "duration": int(e["duration"])}
        # a video without a length can't be scheduled
        for e in data.get("entries") or []
        if e.get("id") and e.get("duration")
    ]
    _write_json(_playlist_path(list_id), {"title": data.get("title"), "fetched": time.time(), "videos": videos})
    _l.info(f"Playlist {data.get('title')!r}: {len(videos)} videos")
    return videos


def refresh_due():
    """Refresh every configured playlist that is missing or older than REFRESH_SECONDS."""
    for station in youtube_stations():
        for list_id in station["youtube_playlists"]:
            cached = _read_json(_playlist_path(list_id))
            if cached and time.time() - cached.get("fetched", 0) < REFRESH_SECONDS:
                continue
            try:
                refresh_playlist(list_id)
            except Exception as e:
                _l.warning(f"Could not refresh playlist {list_id}: {e}")


def _pool(station):
    # youtube_exclude: videos whose title contains any of these (any case) are left
    # out - the NHL in ASL broadcasts, say
    exclude = [x.lower() for x in station.get("youtube_exclude", [])]
    seen = set()
    videos = []
    for list_id in station["youtube_playlists"]:
        cached = _read_json(_playlist_path(list_id)) or {}
        for v in cached.get("videos", []):
            if v["id"] not in seen and not any(x in v["title"].lower() for x in exclude):
                seen.add(v["id"])
                videos.append(v)
    return videos


def _day_path(station, day):
    safe = "".join(c if c.isalnum() else "_" for c in station["network_name"])
    return os.path.join(CACHE_DIR, f"lineup_{safe}_{day.isoformat()}.json")


def _day_start(day):
    return datetime.datetime.combine(day, datetime.time())


def _lineup(station, day, make=True):
    """The day's lineup: [{id, title, start, end}] with start/end as epoch seconds.
    It picks up where the day before left off, so nothing is cut at midnight."""
    path = _day_path(station, day)
    with _lock:
        lineup = _read_json(path)
        if lineup is not None or not make:
            return lineup
        pool = _pool(station)
        if not pool:
            return None
        before = _read_json(_day_path(station, day - datetime.timedelta(days=1)))
        midnight = _day_start(day).timestamp()
        start = before[-1]["end"] if before else midnight
        until = (_day_start(day) + datetime.timedelta(days=1)).timestamp()
        rng = random.Random(f"{station['network_name']}-{day.isoformat()}")
        trim = station.get("youtube_end_trim", END_TRIM)
        lineup = []
        order = []
        while start < until:
            if not order:
                order = rng.sample(pool, len(pool))
            video = order.pop()
            # a short video keeps at least half its length
            length = max(video["duration"] - trim, video["duration"] / 2)
            lineup.append({"id": video["id"], "title": video["title"], "start": start, "end": start + length})
            start += length
        _write_json(path, lineup)
        # old lineups aren't needed once the guide can't page back to them
        prefix = os.path.basename(path).rsplit("_", 1)[0] + "_"
        oldest = (day - datetime.timedelta(days=3)).isoformat()
        for name in os.listdir(CACHE_DIR):
            if name.startswith(prefix) and name[len(prefix):-len(".json")] < oldest:
                os.remove(os.path.join(CACHE_DIR, name))
        return lineup


def _entries(station, start_ts, end_ts):
    entries = []
    day = datetime.date.fromtimestamp(start_ts) - datetime.timedelta(days=1)
    last_day = datetime.date.fromtimestamp(end_ts)
    while day <= last_day:
        # yesterday's lineup is only read, never made - it may run past midnight
        lineup = _lineup(station, day, make=day >= datetime.date.today())
        for e in lineup or []:
            if e["end"] > start_ts and e["start"] < end_ts and e not in entries:
                entries.append(e)
        day += datetime.timedelta(days=1)
    return sorted(entries, key=lambda e: e["start"])


_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
# "Panthers @ Oilers", "Oilers vs. Rangers", "Flames at Golden Knights", "Red Wings and Sabres"
_MATCHUP = re.compile(
    r"(?:^|:\s*|\|\s*)(?P<a>[A-Z][A-Za-z.']*(?:\s+[A-Z][A-Za-z.']*)*)\s+(?:@|at|vs\.?|and)\s+"
    r"(?P<b>[A-Z][A-Za-z.']*(?:\s+[A-Z][A-Za-z.']*)*)")
_LONG_DATE = re.compile(r"\b(?P<m>[A-Z][a-z]{2,8})\.?\s+(?P<d>\d{1,2}),\s*(?P<y>\d{4})")
_SHORT_DATE = re.compile(r"(?<![\d/])(?P<m>\d{1,2})/(?P<d>\d{1,2})(?:/(?P<y>\d{2,4}))?")
_GAME_NO = re.compile(r"\b(?:Gm|Game)\s*(\d)\b")
_EVENTS = ["Stanley Cup Final", "Heritage Classic", "Winter Classic", "Stadium Series",
           "Global Series", "4 Nations Face-Off", "All-Star"]


def game_info(title):
    """What game a highlight is, from its title: {"matchup": "Panthers at Oilers",
    "date": "June 24, 2024" (no year when the title has none), "note": "2024 Stanley
    Cup Final, Game 7" or ""} - or None when no matchup can be found in it."""
    m = _MATCHUP.search(title)
    if not m:
        return None
    event = next((e for e in _EVENTS if e.lower() in title.lower().replace("cupplayoffs", "cup playoffs")), None)
    # all-star and 4 Nations games aren't home and away
    joiner = "vs." if event in ("All-Star", "4 Nations Face-Off") else "at"
    matchup = f'{m.group("a").strip()} {joiner} {m.group("b").strip()}'

    date = ""
    long = _LONG_DATE.search(title)
    month = _MONTHS.get(long.group("m")[:3].lower()) if long else None
    if month:
        date = datetime.date(int(long.group("y")), month, int(long.group("d")))
        date = f"{date:%B} {date.day}, {date.year}"
    else:
        short = _SHORT_DATE.search(title)
        if short and 1 <= int(short.group("m")) <= 12:
            year = short.group("y")
            if year:
                year = int(year) + (2000 if len(year) == 2 else 0)
            else:
                # "Red Wings @ Penguins 10/1 | NHL Preseason Highlights 2024" - the year
                # is somewhere else in the title, if it's there at all
                found = re.search(r"\b(20\d\d)\b", title)
                year = int(found.group(1)) if found else None
            month, day = int(short.group("m")), int(short.group("d"))
            name = datetime.date(2000, month, 1).strftime("%B")
            date = f"{name} {day}, {year}" if year else f"{name} {day}"

    notes = []
    if event == "Stanley Cup Final" or "cup final" in title.lower():
        year = re.search(r"\b(20\d\d)\b", title)
        notes.append(f"{year.group(1)} Stanley Cup Final" if year else "Stanley Cup Final")
    elif event:
        notes.append(event)
    elif "playoff" in title.lower() or re.search(r"\bRound\b", title):
        notes.append("Playoffs")
    elif "preseason" in title.lower():
        notes.append("Preseason")
    game = _GAME_NO.search(title)
    if game:
        notes.append(f"Game {game.group(1)}")
    return {"matchup": matchup, "date": date, "note": ", ".join(notes)}


def _split_title(title):
    # "Red Wings vs. Oilers | NHL Highlights | Oct 26, 2026" or "NHL Highlights | Jets vs.
    # Flames | October 20, 2025" - the matchup is the title, the rest the description
    parts = [p.strip() for p in title.split("|") if p.strip()]
    if len(parts) < 2:
        return title, ""
    main = next((p for p in parts if " vs. " in p or " vs " in p or " @ " in p or " at " in p), parts[0])
    return main, "  ·  ".join(p for p in parts if p is not main)


def listings(network_name, start, end):
    """Guide listings, shaped like /schedules/all's."""
    station = _station(network_name)
    if station is None:
        return []
    out = []
    for e in _entries(station, start.timestamp(), end.timestamp()):
        # a game reads as its matchup, with the date and any playoff note under it -
        # the same as the caption and banner; anything else by its own title
        game = game_info(e["title"])
        if game:
            title, detail = game["matchup"], "  ·  ".join(x for x in (game["date"], game["note"]) if x)
        else:
            title, detail = _split_title(e["title"])
        listing = {
            "title": title,
            "start_time": datetime.datetime.fromtimestamp(e["start"]).isoformat(),
            "end_time": datetime.datetime.fromtimestamp(e["end"]).isoformat(),
        }
        if detail:
            listing["meta"] = {"plot": detail}
        out.append(listing)
    return out


def now_playing(network_name, after=None):
    """What's on now (or the first video starting at or after `after`), with how far in."""
    station = _station(network_name)
    if station is None:
        return None
    now = time.time()
    at = max(now, after) if after else now
    for e in _entries(station, at - 6 * 60 * 60, at + 6 * 60 * 60):
        if (after and e["start"] >= after) or (not after and e["start"] <= at < e["end"]):
            return {
                "id": e["id"],
                "title": e["title"],
                "game": game_info(e["title"]),
                "offset": max(0.0, now - e["start"]),
                "remaining": e["end"] - now,
            }
    return None
