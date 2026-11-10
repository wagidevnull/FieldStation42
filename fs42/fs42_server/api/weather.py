import asyncio
import logging
from fastapi import APIRouter
from fs42 import user_settings, weather

router = APIRouter(prefix="/weather", tags=["weather"])
_l = logging.getLogger("WeatherAPI")


@router.get("")
async def get_weather():
    """Current conditions for the guide, at the Weather ZIP Code setting - or
    {"enabled": false} when the Weather Display setting is off or the weather
    can't be had, so the guide leaves the corner empty."""
    settings = user_settings.load_settings()
    if settings["weather_display"] != "on":
        return {"enabled": False}
    try:
        now = await asyncio.to_thread(weather.current, settings["weather_zip"])
        units = settings["weather_units"]
        return {
            "enabled": True,
            "temp": weather.temperature(now["temp_f"], units),
            "unit": units,
            "icon": now["icon"],
            "caption": now["caption"],
            "place": now["place"],
        }
    except Exception as e:
        _l.warning(f"No weather for {settings['weather_zip']}: {e}")
        return {"enabled": False}
