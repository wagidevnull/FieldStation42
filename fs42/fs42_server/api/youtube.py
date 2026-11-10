import asyncio
import logging
from fastapi import APIRouter, HTTPException
from fs42 import youtube_channel

router = APIRouter(prefix="/youtube", tags=["youtube"])
_l = logging.getLogger("YouTubeAPI")

CHECK_SECONDS = 15 * 60


@router.get("/{network_name}/now")
async def now_playing(network_name: str, after: float = None):
    """The video a YouTube playlist channel should be showing now, and how far in."""
    if youtube_channel._station(network_name) is None:
        raise HTTPException(status_code=404, detail=f"{network_name} is not a YouTube playlist channel")
    playing = await asyncio.to_thread(youtube_channel.now_playing, network_name, after)
    if playing is None:
        # the playlists haven't been read yet - the page asks again shortly
        raise HTTPException(status_code=503, detail="Playlists not loaded yet")
    return playing


async def youtube_refresh_monitor():
    """Background task: keep the channels' playlists read and fresh."""
    while True:
        try:
            await asyncio.to_thread(youtube_channel.refresh_due)
        except Exception as e:
            _l.warning(f"Playlist refresh failed: {e}")
        await asyncio.sleep(CHECK_SECONDS)
