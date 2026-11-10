"""TV series for the pay-per-view channel's Series tab.

A PPV station config can name folders of series beside its movies:

    "series_dirs": [
        {"dir": "catalog/ppv-series/tvshows"},
        {"dir": "catalog/ppv-series/anime", "tag": "Anime"},
        {"dir": "catalog/ppv-series/other-anime", "tag": "Anime", "hidden": true}
    ]

Each folder inside one of those is a series ("Show (Year)"). Its episodes are found
anywhere below it and sorted into seasons by their SxxEyy names, or by the season
folder they sit in when the name has none. Titles, descriptions, posters and episode
stills come from TMDB (cached in catalog/.tmdb_cache/tv/); a file's own name, or an
.nfo sidecar, wins over TMDB for an episode's title. A hidden folder's series are
only listed when asked for (the menu's secret: right five times quickly).
"""

import json
import logging
import os
import random
import re
import time
from pathlib import Path
from typing import List, Optional

import requests
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from fs42.station_manager import StationManager
from fs42.nfo_agent import NFOAgent

router = APIRouter(prefix="/ppv", tags=["ppv"])
_l = logging.getLogger("PPV_Series")

VIDEO_EXTENSIONS = {".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".m2ts", ".ts"}
TMDB_BASE = "https://api.themoviedb.org/3"
POSTER_BASE = "https://image.tmdb.org/t/p/w500"
BACKDROP_BASE = "https://image.tmdb.org/t/p/w1280"
STILL_BASE = "https://image.tmdb.org/t/p/w780"
CACHE_DIR = Path("catalog/.tmdb_cache/tv")
# a failed lookup is tried again after this long, rather than on every page load
MISS_RETRY = 7 * 24 * 3600

_SXXEYY = re.compile(r"[Ss](\d{1,2})[\s._-]*[Ee](\d{1,3})")
_TITLE_AFTER = re.compile(r"[Ss]\d{1,2}[\s._-]*[Ee]\d{1,3}(?:[\s._-]*[Ee]\d{1,3})*\s*-\s*(.+)$")
_SEASON_WORD = re.compile(r"\bSeason[\s._-]*(\d{1,2})\b(?:[\s._-]*Part[\s._-]*(\d))?", re.I)
_EP_NUMBER = re.compile(r"(?:\bEP?\.?[\s._-]*(\d{1,3})\b|[\s._-]-[\s._-]*(\d{1,3})(?=\D|$))", re.I)


# ---- models ----

class SeriesItem(BaseModel):
    key: str
    title: str
    year: str = ""
    overview: str = ""
    poster_url: Optional[str] = None
    backdrop_url: Optional[str] = None
    tag: Optional[str] = None
    hidden: bool = False


class SeriesListResponse(BaseModel):
    channel_number: int
    count: int
    series: List[SeriesItem]


class Episode(BaseModel):
    path: str
    number: Optional[int] = None
    title: str
    overview: str = ""
    still_url: Optional[str] = None


class Season(BaseModel):
    label: str
    number: Optional[int] = None
    overview: str = ""
    poster_url: Optional[str] = None
    episodes: List[Episode]


class SeriesDetail(BaseModel):
    series: SeriesItem
    episode_count: int
    seasons: List[Season]


# ---- TMDB ----

def _api_key():
    return StationManager().server_conf.get("tmdb_api_key", "")


def _cache_get(name):
    path = CACHE_DIR / f"{name}.json"
    try:
        with open(path) as f:
            data = json.load(f)
        if data.get("_miss") and time.time() - data.get("_at", 0) > MISS_RETRY:
            return None
        return data
    except (OSError, ValueError):
        return None


def _cache_put(name, data):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CACHE_DIR / f".{name}.tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, CACHE_DIR / f"{name}.json")


def _safe(text):
    return "".join(c if c.isalnum() else "_" for c in text)[:120]


def _tmdb(path, **params):
    key = _api_key()
    if not key:
        return None
    try:
        r = requests.get(f"{TMDB_BASE}{path}", params={"api_key": key, **params}, timeout=6)
        if r.status_code == 404:
            return {}
        r.raise_for_status()
        return r.json()
    except Exception as e:
        _l.warning(f"TMDB {path} failed: {e}")
        return None


def _split_name(folder):
    # "Better Call Saul (2015)" -> ("Better Call Saul", "2015")
    m = re.match(r"^(.*?)\s*\((\d{4})\)\s*$", folder)
    return (m.group(1).strip(), m.group(2)) if m else (folder.strip(), "")


def _show_info(folder):
    """TMDB's record for a series folder: {id, title, year, overview, poster, backdrop} or {}."""
    name = f"show_{_safe(folder)}"
    cached = _cache_get(name)
    if cached is not None:
        return {} if cached.get("_miss") else cached
    title, year = _split_name(folder)
    params = {"query": title}
    if year:
        params["first_air_date_year"] = year
    data = _tmdb("/search/tv", **params)
    if data is None:
        return {}  # TMDB unreachable - try again next time
    results = data.get("results") or []
    if not results and year:
        data = _tmdb("/search/tv", query=title) or {}
        results = data.get("results") or []
    if not results:
        _cache_put(name, {"_miss": True, "_at": time.time()})
        return {}
    r = results[0]
    info = {
        "id": r.get("id"),
        "title": r.get("name") or title,
        "year": (r.get("first_air_date") or "")[:4] or year,
        "overview": r.get("overview") or "",
        "poster": f"{POSTER_BASE}{r['poster_path']}" if r.get("poster_path") else None,
        "backdrop": f"{BACKDROP_BASE}{r['backdrop_path']}" if r.get("backdrop_path") else None,
    }
    _cache_put(name, info)
    return info


def _season_info(show_id, number):
    """TMDB's season: {name, overview, poster, episodes: {n: {name, overview, still}}} or {}."""
    name = f"season_{show_id}_{number}"
    cached = _cache_get(name)
    if cached is not None:
        return {} if cached.get("_miss") else cached
    data = _tmdb(f"/tv/{show_id}/season/{number}")
    if data is None:
        return {}
    if not data:
        _cache_put(name, {"_miss": True, "_at": time.time()})
        return {}
    info = {
        "name": data.get("name") or "",
        "overview": data.get("overview") or "",
        "poster": f"{POSTER_BASE}{data['poster_path']}" if data.get("poster_path") else None,
        "episodes": {
            str(e["episode_number"]): {
                "name": e.get("name") or "",
                "overview": e.get("overview") or "",
                "still": f"{STILL_BASE}{e['still_path']}" if e.get("still_path") else None,
            }
            for e in data.get("episodes") or [] if e.get("episode_number") is not None
        },
    }
    _cache_put(name, info)
    return info


# ---- the folders ----

def _station(channel_number):
    station = StationManager().station_by_channel(channel_number)
    if station is None:
        raise HTTPException(status_code=404, detail=f"Channel {channel_number} not found")
    return station


def _series_dirs(station):
    return [d for d in station.get("series_dirs", []) if isinstance(d, dict) and d.get("dir")]


def _series_folders(station, include_hidden):
    """(key, folder path, folder name, tag, hidden) for every series, alphabetical."""
    found = []
    for i, spec in enumerate(_series_dirs(station)):
        hidden = bool(spec.get("hidden"))
        if hidden and not include_hidden:
            continue
        base = spec["dir"]
        try:
            names = sorted(os.listdir(base))
        except OSError as e:
            _l.warning(f"Could not read series folder {base}: {e}")
            continue
        for name in names:
            path = os.path.join(base, name)
            # dot folders, and DOS-style short names ("HZ6HK7~P") left by a copy gone wrong
            if name.startswith(".") or re.fullmatch(r"[A-Z0-9]{1,6}~[A-Z0-9]{1,3}", name) or not os.path.isdir(path):
                continue
            found.append((f"{i}/{name}", path, name, spec.get("tag"), hidden))
    return found


def _sort_title(title):
    t = title.lower()
    for article in ("the ", "a ", "an "):
        if t.startswith(article):
            return t[len(article):]
    return t


def _item(key, name, tag, hidden):
    info = _show_info(name)
    title, year = _split_name(name)
    return SeriesItem(
        key=key, title=title, year=info.get("year") or year, overview=info.get("overview", ""),
        poster_url=info.get("poster"), backdrop_url=info.get("backdrop"), tag=tag, hidden=hidden,
    )


# extras folders that sit beside the episodes - creditless openings, featurettes - aren't episodes
_EXTRAS = re.compile(r"^(NC|NCOP|NCED|Creditless|Extras?|Featurettes?|Bonus|Trailers?|Behind[ ._-]the[ ._-]Scenes|Interviews?|Deleted[ ._-]Scenes)$", re.I)


def _episode_files(folder):
    for root, dirs, files in os.walk(folder, followlinks=True):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and not _EXTRAS.match(d))
        for f in sorted(files):
            if os.path.splitext(f)[1].lower() in VIDEO_EXTENSIONS and not f.startswith("."):
                yield os.path.join(root, f)


def _clean_folder_label(name):
    # "[Anime Time] Attack On Titan (Season 4 Part 2)" -> "Season 4 Part 2"
    inner = re.findall(r"\(([^)]*)\)", name)
    for part in inner:
        if _SEASON_WORD.search(part):
            return part.strip()
    label = re.sub(r"^\[[^\]]*\]\s*", "", name).strip()
    return label or name


def _parse_episode(path, folder):
    """(season number or None, season label, episode number or None, title from the name)."""
    base = os.path.splitext(os.path.basename(path))[0]
    rel_dir = os.path.relpath(os.path.dirname(path), folder)
    m = _SXXEYY.search(base)
    if m:
        season, number = int(m.group(1)), int(m.group(2))
        t = _TITLE_AFTER.search(base)
        title = t.group(1).strip() if t else None
        return season, ("Specials" if season == 0 else f"Season {season}"), number, title
    # no SxxEyy: the season comes from the folder it's in
    season, label = None, None
    if rel_dir != ".":
        folder_name = rel_dir.split(os.sep)[0]
        sm = _SEASON_WORD.search(folder_name)
        if sm and not sm.group(2):
            season = int(sm.group(1))
            label = f"Season {season}"
        elif sm:
            # "Season 4 Part 2" - a part of season 4, listed on its own
            season = int(sm.group(1))
            label = f"Season {season} Part {int(sm.group(2))}"
        elif re.search(r"special|oad|ova", folder_name, re.I):
            season, label = 0, _clean_folder_label(folder_name)
        else:
            label = _clean_folder_label(folder_name)
    else:
        season, label = 1, "Season 1"
    # "Show - 88-91": several episodes in one file
    rng = re.search(r"-\s*(\d{1,3})-(\d{1,3})\s*$", base)
    if rng:
        return season, label, int(rng.group(1)), f"Episodes {int(rng.group(1))}\u2013{int(rng.group(2))}"
    em = _EP_NUMBER.search(base)
    number = int(em.group(1) or em.group(2)) if em else None
    # "Wangan Midnight - 20 - Osaka Midnight   [DarkDream]" -> "Osaka Midnight"
    t = re.search(r"-\s*\d{1,3}\s+-\s+(.+?)(?:\s*\[[^\]]*\])?\s*$", base)
    return season, label, number, (t.group(1).strip() if t else None)


def _detail(station, key):
    for k, path, name, tag, hidden in _series_folders(station, include_hidden=True):
        if k == key:
            break
    else:
        raise HTTPException(status_code=404, detail="Series not found")
    item = _item(key, name, tag, hidden)
    show = _show_info(name)

    groups = {}
    for f in _episode_files(path):
        season, label, number, title = _parse_episode(f, path)
        meta = NFOAgent.read_metadata_from_disk(f) or {}
        if meta.get("type") == "episode":
            title = meta.get("title") or title
            number = meta.get("episode") if isinstance(meta.get("episode"), int) else number
        elif meta.get("title"):
            title = meta["title"]
        g = groups.setdefault(label, {"number": season, "episodes": {}})
        ep_key = number if number is not None else f
        # the same episode twice (a tidy copy and a release-group copy): keep the named one
        if ep_key in g["episodes"] and g["episodes"][ep_key]["title"] and not title:
            continue
        g["episodes"][ep_key] = {"path": f, "number": number, "title": title}

    seasons = []
    for label, g in groups.items():
        info = _season_info(show["id"], g["number"]) if show.get("id") and g["number"] is not None else {}
        # some releases number straight through the series (Season 2 starting at 26) - TMDB
        # counts from 1 each season, so look episodes up by their place in the season
        # (a season split into parts counts from the first part's first episode)
        numbers = [e["number"] for other in groups.values() if other["number"] == g["number"]
                   for e in other["episodes"].values() if e["number"] is not None]
        offset = min(numbers) - 1 if numbers and g["number"] and g["number"] > 1 and min(numbers) > 1 else 0
        eps = []
        for e in g["episodes"].values():
            tm = (info.get("episodes") or {}).get(str(e["number"] - offset)) if e["number"] is not None else None
            title = e["title"] or (tm or {}).get("name") or (f"Episode {e['number']}" if e["number"] else
                                                               os.path.splitext(os.path.basename(e["path"]))[0])
            eps.append(Episode(path=e["path"], number=e["number"], title=title,
                               overview=(tm or {}).get("overview", ""), still_url=(tm or {}).get("still")))
        eps.sort(key=lambda e: (e.number is None, e.number or 0, e.title))
        seasons.append(Season(label=label, number=g["number"], overview=info.get("overview", ""),
                              poster_url=info.get("poster") or item.poster_url, episodes=eps))
    # Season 1, 2 ... in order, then specials and anything else
    seasons.sort(key=lambda s: (s.number is None or s.number == 0, s.number if s.number else 0, s.label))
    return SeriesDetail(series=item, episode_count=sum(len(s.episodes) for s in seasons), seasons=seasons)


# ---- endpoints (plain def - they do file and network work, so FastAPI runs them off the loop) ----

@router.get("/{channel_number}/series", response_model=SeriesListResponse)
def list_series(channel_number: int, hidden: bool = False):
    """The channel's series; hidden folders only with ?hidden=true."""
    station = _station(channel_number)
    items = [_item(k, name, tag, h) for k, path, name, tag, h in _series_folders(station, hidden)]
    items.sort(key=lambda s: _sort_title(s.title))
    return SeriesListResponse(channel_number=channel_number, count=len(items), series=items)


@router.get("/{channel_number}/series/detail", response_model=SeriesDetail)
def series_detail(channel_number: int, key: str):
    """One series' seasons and episodes (key from the list, as a query parameter)."""
    return _detail(_station(channel_number), key)


@router.get("/{channel_number}/series/random")
def random_episode(channel_number: int, key: str):
    """A random episode's file from anywhere in a series."""
    detail = _detail(_station(channel_number), key)
    eps = [e for s in detail.seasons for e in s.episodes]
    if not eps:
        raise HTTPException(status_code=404, detail="No episodes found")
    e = random.choice(eps)
    return {"path": e.path, "title": e.title}


# ---- where the menu was, so it comes back there after an episode or movie ----
# Kept in a file the player deletes on any channel change (field_player.py), so the
# menu only picks up where it was when it comes straight back from something it started.
MENU_STATE_FILE = "runtime/ppv_menu_state.json"


class MenuState(BaseModel):
    state: dict


@router.post("/{channel_number}/menu_state")
def save_menu_state(channel_number: int, body: MenuState):
    with open(MENU_STATE_FILE, "w") as f:
        json.dump({"channel": channel_number, "state": body.state, "at": time.time()}, f)
    return {"success": True}


@router.get("/{channel_number}/menu_state")
def get_menu_state(channel_number: int):
    """The saved place, once - reading it uses it up."""
    try:
        with open(MENU_STATE_FILE) as f:
            saved = json.load(f)
        os.remove(MENU_STATE_FILE)
    except (OSError, ValueError):
        return {"state": None}
    if saved.get("channel") != channel_number or time.time() - saved.get("at", 0) > 6 * 3600:
        return {"state": None}
    return {"state": saved["state"]}
