import logging
import threading
import time

import requests

# Current conditions for the guide's weather corner. A US ZIP code is turned into
# a place with Zippopotam.us, and the weather there comes from Open-Meteo - both
# free and keyless. Conditions are fetched at most every REFRESH_SECONDS; the
# guide asks often, but only the first ask after that goes out to the network.
# The icons are the 1992 Weather Channel "current conditions" set in
# fs42_server/static/weather/, picked by icon_for().

ZIP_URL = "https://api.zippopotam.us/us/{zip}"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
REFRESH_SECONDS = 10 * 60
TIMEOUT = 8

_l = logging.getLogger("Weather")
_lock = threading.Lock()
# zip -> {"place", "lat", "lon"}; a ZIP doesn't move, so these are kept for good
_places = {}
# zip -> (fetched at, conditions)
_current = {}


class ZipNotFound(Exception):
    pass


def locate(zip_code):
    """The place a US ZIP code is in. Raises ZipNotFound if there's no such ZIP."""
    with _lock:
        if zip_code in _places:
            return _places[zip_code]
    res = requests.get(ZIP_URL.format(zip=zip_code), timeout=TIMEOUT)
    if res.status_code == 404:
        raise ZipNotFound(zip_code)
    res.raise_for_status()
    first = res.json()["places"][0]
    place = {
        "place": f'{first["place name"]}, {first["state abbreviation"]}',
        "lat": float(first["latitude"]),
        "lon": float(first["longitude"]),
    }
    with _lock:
        _places[zip_code] = place
    return place


def icon_for(code, is_day, cloud_cover, temp_f, wind_mph):
    """The icon (a file in static/weather/) and a caption for Open-Meteo's
    conditions - its weather code is the WMO one."""
    freezing = temp_f <= 32
    if code in (95, 96, 99):
        return ("ThunderSnow", "Thundersnow") if freezing else ("Thunderstorm", "Thunderstorms")
    if code in (71, 73, 75, 85, 86):
        if wind_mph >= 25:
            return "Blowing-Snow", "Blowing Snow"
        if 32 < temp_f <= 36:
            # snow just above freezing comes down part sleet
            return "Snow-Sleet", "Snow and Sleet"
        if code in (75, 86):
            return "Heavy-Snow", "Heavy Snow"
        return ("Light-Snow", "Light Snow") if code in (71, 85) else ("Heavy-Snow", "Snow")
    if code == 77:
        return "Sleet", "Sleet"
    if code in (66, 67):
        if temp_f <= 28:
            return "Ice-Snow", "Ice and Snow"
        return ("Freezing-Rain-Sleet", "Freezing Rain") if code == 67 else ("Freezing-Rain", "Freezing Rain")
    if code in (56, 57):
        return "Wintry-Mix", "Wintry Mix"
    if code in (61, 63, 65, 80, 81, 82, 51, 53, 55):
        # rain right at freezing is likely mixed with snow
        if freezing:
            return "Rain-Snow", "Rain and Snow"
        if code in (65, 82):
            return "Rain", "Heavy Rain"
        if code in (51, 53, 55):
            return "Shower", "Drizzle"
        return ("Shower", "Showers") if code in (61, 80, 81) else ("Rain", "Rain")
    if code in (45, 48):
        return "Cloudy", "Fog"
    # clear to overcast: cloud cover picks how cloudy, day or night picks sun or moon
    if cloud_cover < 15:
        return ("Sunny", "Sunny") if is_day else ("Clear", "Clear")
    if cloud_cover < 35:
        return ("Sunny", "Mostly Sunny") if is_day else ("Mostly-Clear", "Mostly Clear")
    if cloud_cover < 60:
        return ("Partly-Cloudy", "Partly Cloudy") if is_day else ("Partly-Clear", "Partly Cloudy")
    if cloud_cover < 85:
        # the Mostly Cloudy icon has the sun peeking out - at night the cloudiest moon
        # (Partly Clear) stands in for it
        return ("Mostly-Cloudy", "Mostly Cloudy") if is_day else ("Partly-Clear", "Mostly Cloudy")
    return "Cloudy", "Cloudy"


def temperature(temp_f, units):
    """A temperature to show, rounded, in "F" or "C"."""
    return round(temp_f if units == "F" else (temp_f - 32) * 5 / 9)


def current(zip_code):
    """Conditions now at a US ZIP code: {"temp_f", "icon", "caption", "place"},
    the temperature unrounded in Fahrenheit (see temperature() to show it).
    Raises ZipNotFound for a ZIP that doesn't exist, or a requests error when the
    weather can't be reached and nothing has been fetched before."""
    with _lock:
        cached = _current.get(zip_code)
    if cached and time.time() - cached[0] < REFRESH_SECONDS:
        return cached[1]
    try:
        place = locate(zip_code)
        res = requests.get(WEATHER_URL, timeout=TIMEOUT, params={
            "latitude": place["lat"],
            "longitude": place["lon"],
            "current": "temperature_2m,weather_code,is_day,cloud_cover,wind_speed_10m",
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "mph",
            "timezone": "auto",
        })
        res.raise_for_status()
        now = res.json()["current"]
    except ZipNotFound:
        raise
    except Exception as e:
        if cached:
            # keep showing the last conditions rather than nothing
            _l.warning(f"Weather update failed, showing the last one: {e}")
            return cached[1]
        raise
    icon, caption = icon_for(now["weather_code"], now["is_day"], now["cloud_cover"],
                             now["temperature_2m"], now["wind_speed_10m"])
    conditions = {
        "temp_f": now["temperature_2m"],
        "icon": icon,
        "caption": caption,
        "place": place["place"],
    }
    with _lock:
        _current[zip_code] = (time.time(), conditions)
    return conditions
