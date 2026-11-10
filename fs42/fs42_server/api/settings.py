import asyncio
import logging
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from fs42 import user_settings, weather
from .player import connected_command_queue

router = APIRouter(prefix="/settings", tags=["settings"])


class SettingValue(BaseModel):
    value: str


@router.get("")
async def get_settings():
    """The settings menu layout and the current value of each setting."""
    return {
        "schema": user_settings.SETTINGS_SCHEMA,
        "groups": user_settings.SETTINGS_GROUPS,
        "values": user_settings.load_settings(),
        # the look the guide wears today - the Guide Theme, or the season's
        # when Seasonal Themes is on
        "guide_look": user_settings.guide_look(),
    }


@router.get("/provider_logo/pick")
async def pick_provider_logo():
    """The provider logo for a guide that's opening - one at random if the setting is Random."""
    return {"file": user_settings.pick_provider_logo()}


@router.put("/{key}")
async def put_setting(key: str, setting: SettingValue, request: Request):
    if key == "weather_zip":
        # only take a ZIP code that's real, so a typo doesn't leave the guide without weather
        try:
            await asyncio.to_thread(weather.locate, setting.value)
        except weather.ZipNotFound:
            raise HTTPException(status_code=400, detail=f"ZIP code {setting.value} not found")
        except Exception as e:
            logging.getLogger("SettingsAPI").warning(f"Could not check ZIP {setting.value}: {e}")
    try:
        values = user_settings.save_setting(key, setting.value)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # let a running player pick up the change right away
    try:
        connected_command_queue(request).put({"command": "apply_settings"})
    except HTTPException:
        logging.getLogger("SettingsAPI").info("Player not connected - setting applies on next start")
    return {"values": values}
