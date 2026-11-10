from fastapi import APIRouter
from .summary import router as summary_router
from .catalogs import router as catalogs_router
from .schedules import router as schedules_router
from .player import router as player_router
from .build import router as build_router
from .themes import router as themes_router
from .stations import router as stations_router
from .ppv_series import router as ppv_series_router
from .ppv import router as ppv_router
from .media import router as media_router
from .settings import router as settings_router
from .autotune import router as autotune_router
from .youtube import router as youtube_router
from .weather import router as weather_router
from .manage import router as manage_router

# Create a list of all routers to be included
routers = [
    summary_router,
    catalogs_router,
    schedules_router,
    player_router,
    build_router,
    themes_router,
    stations_router,
    ppv_series_router,
    ppv_router,
    media_router,
    settings_router,
    autotune_router,
    youtube_router,
    weather_router,
    manage_router,
]
