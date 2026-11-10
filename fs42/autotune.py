import json
import logging
import os
import tempfile
import threading
import time

# Auto-tune: pick a program in the guide that hasn't started yet and the player
# switches to its channel when it begins. Kept in a small JSON file so a restart
# doesn't lose them; the web server's background task does the tuning.

AUTOTUNE_PATH = "runtime/autotune.json"
# a program that started longer ago than this is dropped rather than tuned to late
LATE_LIMIT_SECONDS = 5 * 60

_l = logging.getLogger("AutoTune")
_lock = threading.Lock()


def _entry_id(channel, start_ms):
    return f"{int(channel)}-{int(start_ms)}"


def load():
    try:
        with open(AUTOTUNE_PATH) as f:
            entries = json.load(f)
        return entries if isinstance(entries, list) else []
    except FileNotFoundError:
        return []
    except Exception as e:
        _l.warning(f"Could not read {AUTOTUNE_PATH}: {e}")
        return []


def _save(entries):
    # write to a temp file and rename so a reader never sees a half-written file
    os.makedirs(os.path.dirname(AUTOTUNE_PATH), exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(AUTOTUNE_PATH), suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(entries, f, indent=2)
    os.replace(tmp_path, AUTOTUNE_PATH)


def _current(entries, now_ms):
    return [e for e in entries if e["start"] + LATE_LIMIT_SECONDS * 1000 > now_ms]


def add(channel, start_ms, network_name="", title=""):
    """Set an auto-tune; setting one twice for the same program just keeps it."""
    now_ms = time.time() * 1000
    if start_ms <= now_ms:
        raise ValueError("That program has already started")
    with _lock:
        entries = _current(load(), now_ms)
        entry_id = _entry_id(channel, start_ms)
        entries = [e for e in entries if e["id"] != entry_id]
        entries.append({
            "id": entry_id,
            "channel": int(channel),
            "start": int(start_ms),
            "network_name": network_name,
            "title": title,
        })
        entries.sort(key=lambda e: e["start"])
        _save(entries)
        return entries


def remove(entry_id):
    with _lock:
        entries = [e for e in load() if e["id"] != entry_id]
        _save(entries)
        return entries


def take_due(now_ms=None):
    """Auto-tunes whose program has begun, removed from the list. Ones far past
    their start (the player was off) are dropped without being returned."""
    now_ms = now_ms if now_ms is not None else time.time() * 1000
    with _lock:
        entries = load()
        due = [e for e in entries if e["start"] <= now_ms]
        if not due:
            return []
        _save([e for e in entries if e["start"] > now_ms])
        return [e for e in due if now_ms - e["start"] < LATE_LIMIT_SECONDS * 1000]
