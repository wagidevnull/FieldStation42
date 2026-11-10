import asyncio
import json
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from fs42 import autotune
from fs42.station_manager import StationManager

router = APIRouter(prefix="/autotune", tags=["autotune"])
_l = logging.getLogger("AutoTuneAPI")

CHECK_SECONDS = 2


class AutoTuneRequest(BaseModel):
    channel: int
    start: int  # program start, ms since the epoch
    network_name: str = ""
    title: str = ""


@router.get("")
async def list_autotunes():
    return {"autotunes": autotune.load()}


@router.post("")
async def add_autotune(req: AutoTuneRequest):
    if StationManager().station_by_channel(req.channel) is None:
        raise HTTPException(status_code=404, detail=f"No channel {req.channel}")
    try:
        entries = autotune.add(req.channel, req.start, req.network_name, req.title)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"autotunes": entries}


@router.delete("/{entry_id}")
async def remove_autotune(entry_id: str):
    return {"autotunes": autotune.remove(entry_id)}


def _playing_channel():
    try:
        with open(StationManager().server_conf["status_socket"]) as f:
            return json.loads(f.read().strip()).get("channel_number")
    except Exception:
        return None


def _tune(channel):
    # the same direct-tune command /player/channels/{n} sends
    with open(StationManager().server_conf["channel_socket"], "w") as f:
        f.write(json.dumps({"command": "direct", "channel": channel}))


async def autotune_monitor():
    """Background task: tune to each auto-tuned channel as its program begins."""
    while True:
        await asyncio.sleep(CHECK_SECONDS)
        try:
            for entry in autotune.take_due():
                if _playing_channel() == entry["channel"]:
                    _l.info(f"Auto-tune: already on channel {entry['channel']} for {entry['title']}")
                    continue
                _l.info(f"Auto-tune: switching to channel {entry['channel']} for {entry['title']}")
                _tune(entry["channel"])
        except Exception as e:
            _l.warning(f"Auto-tune check failed: {e}")
