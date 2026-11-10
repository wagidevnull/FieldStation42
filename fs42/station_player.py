from enum import Enum
import logging

import multiprocessing
import threading
import time
import datetime
from types import SimpleNamespace
import json
import os
import glob
import random
import sys
import base64
import logging
import time
from python_mpv_jsonipc import MPV

from fs42.guide_tk import guide_channel_runner, GuideCommands
from fs42.autobump_agent import AutoBumpAgent
from fs42 import user_settings
from fs42.channel_banner import ChannelBanner, logo_file, short_time
from fs42 import youtube_channel
from fs42.channel_bug import ChannelBug
from fs42.track_picker import TrackPicker, tracks as mpv_tracks

# Try to import web_render_runner, but handle gracefully if PySide6 (with QtWebEngine)
# isn't available -- web rendering is an optional feature.
try:
    from fs42.webrender.web_render import web_render_runner
    WEB_RENDER_AVAILABLE = True
except ImportError as e:
    logging.getLogger("station_player").info(
        "Web rendering disabled (PySide6 QtWebEngine not available): %s", e
    )
    WEB_RENDER_AVAILABLE = False
    web_render_runner = None

from fs42.reception import (
    ReceptionStatus,
    HLScrambledVideoFilter,
    DiagonalScrambledVideoFilter,
    ColorInvertedScrambledVideoFilter,
    ChunkyScrambledVideoFilter,
)
from fs42.liquid_manager import LiquidManager, PlayPoint, ScheduleNotFound, ScheduleQueryNotInBounds

from fs42.liquid_schedule import LiquidSchedule
from fs42.station_manager import StationManager
from fs42.slot_reader import SlotReader
from fs42.game_caption import GameCaption
from fs42.trick_play import TrickPlay
from fs42.volume_osd import VolumeOSD
from fs42.notice_osd import NoticeOSD
from fs42.channel_entry_osd import ChannelEntryOSD
from fs42.x11_focus import activate_window

# YouTube channels (youtube_playlists) are played by mpv, which hands the video to
# yt-dlp - the browser's embedded player only ever gets 360p. The venv's yt-dlp, as
# the system one is too old for YouTube. Up to 1080p, H.264 first as it's the
# lightest to decode, then VP9, then anything; plain https streams before HLS, as
# they seek faster.
YTDL_PATH = os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "yt-dlp")
YTDL_FORMAT = ("bv*[height<=1080][vcodec^=avc1][protocol^=https]+ba[protocol^=https]"
               "/bv*[height<=1080][vcodec^=vp9][protocol^=https]+ba[protocol^=https]"
               "/bv*[height<=1080]+ba/b[height<=1080]/b")
# how long a YouTube video may take to start before it's skipped
YOUTUBE_START_TIMEOUT = 30

logging.basicConfig(format="%(asctime)s %(levelname)s:%(name)s:%(message)s", level=logging.INFO)


def update_status_socket(
    status,
    network_name,
    channel,
    title=None,
    timestamp="%Y-%m-%dT%H:%M:%S",
    duration=None,
    file_path=None,
    content_type=None,
    awaiting_pin=False,
    pin_digits_entered=0,
    metadata=None,
):
    status_obj = {
        "status": status,
        "network_name": network_name,
        "channel_number": channel,
        "timestamp": datetime.datetime.now().strftime(timestamp),
        "awaiting_pin": awaiting_pin,
        "pin_digits_entered": pin_digits_entered,
    }
    if title is not None:
        status_obj["title"] = title
    if duration is not None:
        status_obj["duration"] = duration
    if file_path is not None:
        status_obj["file_path"] = file_path
    if content_type is not None:
        status_obj["content_type"] = content_type
    # the remote sends number keys to the settings menu (for typing a ZIP code)
    # rather than changing channel while it's up
    manager = StationManager()
    settings_conf = getattr(manager, "settings_config", None)
    status_obj["settings_menu"] = bool(settings_conf and channel == settings_conf["channel_number"])
    # and BACK/EXIT closes the guide back to the channel it was opened from
    guide_conf = getattr(manager, "guide_config", None)
    status_obj["guide"] = bool(guide_conf and channel == guide_conf["channel_number"])
    if metadata:
        from fs42.nfo_agent import NFOAgent

        # Metadata never overrides the player's own fields.
        for key, value in metadata.items():
            status_obj.setdefault(key, value)
        if "content_rating" in metadata:
            status_obj["content_rating"] = NFOAgent.normalize_content_rating(metadata["content_rating"])
    status_socket = StationManager().server_conf["status_socket"]
    as_str = json.dumps(status_obj)
    with open(status_socket, "w") as fp:
        fp.write(as_str)


class PlayerState(Enum):
    FAILED = 1
    EXITED = 2
    SUCCESS = 3
    CHANNEL_CHANGE = 4
    EXIT_COMMAND = 5
    PLAY_FILE = 6
    PARENTAL_CONTROLS = 7


class PlayerOutcome:
    def __init__(self, status=PlayerState.SUCCESS, payload=None):
        self.status = status
        self.payload = payload


class StationPlayer:
    MPV_RUNTIME_COMMANDS = {
        "toggle_subtitles": ("cycle", "sub-visibility"),
        "cycle_subtitles": ("cycle", "sub"),
        "cycle_audio": ("cycle", "audio"),
    }

    scramble_effects = {
        "horizontal_line": "lavfi=[geq='if(mod(floor(Y/4),2),p(X,Y+20*sin(2*PI*X/50)),p(X,Y))']",
        "diagonal_lines": "lavfi=[geq='p(X+10*sin(2*PI*Y/30),Y)']",
        "static_overlay": "lavfi=[geq='if(gt(random(X+Y*W),0.85),128+127*random(X*Y),if(mod(floor(Y/4),2),p(X+20,Y),p(X,Y)))']",
        "pixel_block": "lavfi=[scale=160:120,scale=640:480:flags=neighbor,geq='if(gt(random(floor(X/40)*floor(Y/30)),0.7),128,p(X,Y))']",
        "color_inversion": "lavfi=[geq='if(mod(floor(Y/16),2),255-p(X,Y),p(X,Y))']",
        "severe_noise": "lavfi=[geq='if(gt(random(X*Y),0.7),random(255),p(X,Y))']",
        "wavy": "lavfi=[geq='p(X+15*sin(2*PI*Y/40),Y+10*cos(2*PI*X/60))']",
        "random_block": "lavfi=[geq='if(gt(random(floor(X/20)*floor(Y/20)),0.6),p(X+random(100)-20,Y+random(70)-20),p(X,Y))']",
        "chunky_scramble": "lavfi=[scale=320:240,split[base][aux];[aux]geq=r='p(X+floor((random(1000+floor(N*0.05)+floor(Y/16))-0.5)*W*0.4),Y)':g='p(X+floor((random(2000+floor(N*0.05)+floor(Y/16))-0.5)*W*0.4),Y)':b='p(X+floor((random(3000+floor(N*0.05)+floor(Y/16))-0.5)*W*0.4),Y)'[warped];[base][warped]overlay,scale=640:480]",
        "spicy" : (
            "lavfi=["
            "scale=720:480:flags=fast_bilinear,"
            "noise=alls=12:allf=t,"
            "eq=contrast=1.10:brightness=-0.04:saturation=2.4,"
            "geq="
            "r='p(X + 40*sin(2*PI*Y/60) + 12*sin(2*PI*N/10), Y)':"
            "g='p(X + 32*sin(2*PI*Y/64) + 10*sin(2*PI*N/11), Y)':"
            "b='p(X + 24*sin(2*PI*Y/68) +  8*sin(2*PI*N/12), Y)',"
            "scale=640:480:flags=neighbor"
            "]"
        ),
        "special_sauce" : (
            "lavfi=["
            "scale=360:240:flags=fast_bilinear,"
            "format=gbrp,"
            "geq="
            "r='p(mod(X + 80*sin(2*PI*Y/45 + N*0.4) + 20*sin(2*PI*Y/13 + N*0.7),W), Y)':"
            "g='p(mod(X + 70*sin(2*PI*Y/48 + N*0.43) + 17*sin(2*PI*Y/14 + N*0.73),W), Y)':"
            "b='p(mod(X + 60*sin(2*PI*Y/50 + N*0.46) + 13*sin(2*PI*Y/15 + N*0.76),W), Y)'"
            ":interpolation=nearest,"
            "noise=alls=15:allf=t,"
            "eq=contrast=1.2:brightness=-0.05:saturation=1.2,"
            "format=yuv420p,"
            "scale=640:480:flags=neighbor"
            "]"
        ),
        "glitchtastic" : (
            "lavfi=["
            "scale=360:240:flags=fast_bilinear,"
            "format=gbrp,"
            "geq="
            "r='if(gt(pow(abs(sin(N*0.08)*sin(N*0.11)),0.15),0.7),"
            "p(mod(X+80*sin(2*PI*Y/45+N*0.4)+20*sin(2*PI*Y/13+N*0.7),W),Y),"
            "if(gt(mod(Y+N*4,H),H-30),255-p(X,Y),"
            "p(X+15*sin(2*PI*Y/45+N*0.4),Y)))':"
            "g='if(gt(pow(abs(sin(N*0.08)*sin(N*0.11)),0.15),0.7),"
            "p(mod(X+70*sin(2*PI*Y/48+N*0.43)+17*sin(2*PI*Y/14+N*0.73),W),Y),"
            "if(gt(mod(Y+N*4,H),H-30),255-p(X,Y),"
            "p(X+12*sin(2*PI*Y/48+N*0.43),Y)))':"
            "b='if(gt(pow(abs(sin(N*0.08)*sin(N*0.11)),0.15),0.7),"
            "p(mod(X+60*sin(2*PI*Y/50+N*0.46)+13*sin(2*PI*Y/15+N*0.76),W),Y),"
            "if(gt(mod(Y+N*4,H),H-30),255-p(X,Y),"
            "p(X+10*sin(2*PI*Y/50+N*0.46),Y)))'"
            ":interpolation=nearest,"
            "noise=alls=15:allf=t,"
            "eq=contrast=1.2:brightness=-0.05:saturation=1.2,"
            "format=yuv420p,"
            "scale=640:480:flags=neighbor"
            "]"
        )
    }

    audio_scramble_effects = {
        "special_sauce": "lavfi=[afreqshift=shift=-2000,vibrato=f=2.5:d=0.4,volume=0.8]",
        "the_jitters": "lavfi=[afreqshift=shift=-3000,aecho=0.6:0.5:50|80:0.4|0.3,tremolo=f=8:d=0.9,volume=0.7]",
        "possessed": "lavfi=[chorus=0.3:0.3:40|60|80:0.4|0.3|0.2:0.8|1.2|1.6:3|4|5,afreqshift=shift=-1500,lowpass=f=2500,volume=0.8]",
        "demonic": "lavfi=[rubberband=pitch=0.5,chorus=0.3:0.3:40|60:0.4|0.3:1.0|1.4:3|4,volume=1.0]",
        "slightly_borked": "lavfi=[acrusher=bits=3:samples=12:lfo=true:lforange=50:lforate=0.3,vibrato=f=3:d=0.5,volume=0.25]"
    }

    def __init__(self, station_config, input_check_fn, mpv=None):
        self._l = logging.getLogger("FieldPlayer")

        start_it = True

        if "start_mpv" in StationManager().server_conf:
            start_it = StationManager().server_conf["start_mpv"]

        if not mpv:
            self._l.info("Starting MPV instance")
            # command on client: mpv --input-ipc-server=runtime/mpv.socket --idle --force-window

            # if not running on trixie
            self.mpv = MPV(
                start_mpv=start_it,
                ipc_socket="runtime/mpv.socket",
                input_default_bindings=False,
                fs=True,
                idle=True,
                force_window=True,
                script_opts=f"osc-idlescreen=no,ytdl_hook-ytdl_path={YTDL_PATH}",
                ytdl_format=YTDL_FORMAT,
                hr_seek="yes",
                image_display_duration="inf",
                # OpenGL, not Vulkan: Mesa's Vulkan swapchain on X11 can deadlock when the
                # window is resized or covered - the guide preview does both - and mpv
                # then freezes for good (seen twice, the WSI swapchain threads stuck)
                gpu_api="opengl",
            )

        self.station_config = station_config
        # self.playlist = self.read_json(runtime_filepath)
        self.input_check_fn = input_check_fn
        self.index = 0
        self.reception = ReceptionStatus()
        self.current_playing_file_path = None
        self.skip_reception_check = False
        self.web_process = None
        self.web_queue = None
        self._guide_preview_active = False
        self._guide_preview_rect = None
        # the last scheduled channel played - the guide preview follows its schedule
        self._preview_network = None
        # a web channel kept running while the guide or menu is up, so the guide can
        # preview it and tuning back finds it still going: (network_name, process, queue)
        self._parked_web = None
        # the last channel tuned that isn't hidden (set by the main loop) - the guide
        # starts with it selected
        self.last_channel = None
        self.parental_controls_process = None
        self.parental_controls_queue = None
        self.parental_unlocked_network = None
        self.scrambler = None
        self.now_playing_process = None
        self.schedule_lock = None
        self._active_afx = None
        self._pending_response = None
        self.banner = ChannelBanner(self.mpv)
        # the channel's logo in the bottom right corner while a show plays
        self.bug = ChannelBug(self.mpv)
        self.track_picker = TrackPicker(self.mpv)
        self.track_picker.on_open = self.bug.suspend
        self.track_picker.on_close = self.bug.resume
        # which game a YouTube highlight is, in the bottom left as it starts
        self.caption = GameCaption(self.mpv)
        self.volume_osd = VolumeOSD(self.mpv)
        self.notice_osd = NoticeOSD(self.mpv)
        self.channel_entry = ChannelEntryOSD(self.mpv)
        # YouTube videos that wouldn't play - the lineup's next one stands in for them
        self._youtube_broken = set()
        # set by the main loop on every tune; the banner then shows once the channel is playing
        self.banner_pending = False
        self._banner_request = None
        self.apply_user_settings()

    # mpv's monitoraspect is the physical shape of the screen, so the picture stays
    # correct whatever resolution the output runs at (a CRT often gets 720x480)
    ASPECT_RATIOS = {"16:9": 16 / 9, "4:3": 4 / 3}

    def _panscan(self):
        # zoom from the settings menu fills the screen; otherwise the station decides
        if user_settings.load_settings()["picture_size"] == "zoom":
            return 1.0
        return self.station_config.get("panscan", 0.0)

    # Audio Normalization: ffmpeg's dynamic normalizer, which follows the loudness gently
    # over a few seconds (no pumping), boosts quiet audio at most 10x and keeps peaks
    # clear of clipping. Labelled, so it can be found and removed again.
    NORMALIZE_AF = "@fs42norm:lavfi=[dynaudnorm=f=400:g=21:p=0.89:m=10:s=0]"

    def apply_audio_normalize(self):
        """Add or remove the normalization filter to match the setting."""
        on = user_settings.load_settings().get("audio_normalize") == "on"
        try:
            chain = self.mpv.command("get_property", "af") or []
            present = any(f.get("label") == "fs42norm" for f in chain)
            if on and not present:
                self.mpv.command("af", "add", self.NORMALIZE_AF)
            elif not on and present:
                self.mpv.command("af", "remove", "@fs42norm")
        except Exception as e:
            self._l.warning(f"Could not apply audio normalization: {e}")

    def apply_user_settings(self):
        """Apply the settings menu values to the running player."""
        settings = user_settings.load_settings()
        self.apply_audio_normalize()
        aspect = self.ASPECT_RATIOS.get(settings["aspect_ratio"], 16 / 9)
        try:
            changed = abs(self.mpv.command("get_property", "monitoraspect") - aspect) > 0.001
            self.mpv.command("set_property", "monitoraspect", aspect)
            if changed:
                self._relayout_video()
            self._l.info(f"Screen aspect ratio set to {settings['aspect_ratio']}")
        except Exception as e:
            self._l.warning(f"Could not apply aspect ratio setting: {e}")
        try:
            self.mpv.panscan = self._panscan()
            # zoom pushes the video past the screen edges, and mpv then centers
            # subtitles on the whole video rather than the screen - keep them on screen
            self.mpv.command("set_property", "sub-use-margins", settings["picture_size"] != "zoom")
            self._l.info(f"Picture size set to {settings['picture_size']}")
        except Exception as e:
            self._l.warning(f"Could not apply picture size setting: {e}")

    def _already_playing(self, file_path, offset_seconds):
        """True when mpv is already on this file within a few seconds of where the schedule is."""
        try:
            path = self.mpv.command("get_property", "path")
            pos = self.mpv.command("get_property", "time-pos")
        except Exception:
            return False
        if not path or pos is None:
            return False
        # mpv reports a relative path resolved against its own working directory,
        # so match on the path as scheduled rather than the absolute one
        wanted = os.path.normpath(file_path)
        if not (os.path.normpath(path) == os.path.abspath(wanted) or os.path.normpath(path).endswith(os.sep + wanted)):
            return False
        return abs(pos - (offset_seconds or 0)) < 3

    ENGLISH = {"en", "eng"}

    def _prepare_tracks(self):
        # set before the file opens, so the wrong language never plays for a moment
        settings = user_settings.load_settings()
        try:
            self.mpv.command("set_property", "alang", "eng,en" if settings["audio_language"] == "english" else "")
            self.mpv.command("set_property", "sid", "auto" if settings["subtitles"] == "file" else "no")
        except Exception as e:
            self._l.warning(f"Could not set track preferences: {e}")

    def _choose_tracks(self):
        # files can flag any track as the default - a dub, or a sidecar .srt in another
        # language - so pick by language rather than trusting the file
        settings = user_settings.load_settings()
        try:
            if settings["audio_language"] == "english":
                english = [t for t in mpv_tracks(self.mpv, "audio") if (t.get("lang") or "").lower() in self.ENGLISH]
                if english and not any(t.get("selected") for t in english):
                    english.sort(key=lambda t: not t.get("default"))
                    self.mpv.command("set_property", "aid", english[0]["id"])
            if settings["subtitles"] == "english":
                english = [t for t in mpv_tracks(self.mpv, "sub") if (t.get("lang") or "").lower() in self.ENGLISH]
                # embedded before sidecar files, then the file's own default
                english.sort(key=lambda t: (bool(t.get("external")), not t.get("default")))
                self.mpv.command("set_property", "sid", english[0]["id"] if english else "no")
        except Exception as e:
            self._l.warning(f"Could not choose audio/subtitle tracks: {e}")

    def _web_banner(self, conf):
        """The channel banner for a web channel, as a message for its page to draw:
        mpv's own banner would be hidden under the page. None for the guide and the
        settings menu (hidden channels), which have their own screens."""
        if conf is None or conf.get("network_type") != "web" or conf.get("hidden"):
            return None
        now = datetime.datetime.now()
        info = {
            "number": conf.get("channel_number", ""),
            "name": conf.get("network_name", ""),
            "title": conf.get("network_long_name") or conf.get("network_name", ""),
            "subtitle": "",
            "when": f"{now.strftime('%a %m/%d').upper()}   {short_time(now)}",
            "slot": "",
            "logo": None,
        }
        logo = logo_file(conf.get("channel_logo"))
        if logo:
            kind = "image/svg+xml" if logo.lower().endswith(".svg") else "image/png"
            with open(logo, "rb") as f:
                # sent inline, so it shows on pages from other sites too
                info["logo"] = f"data:{kind};base64," + base64.b64encode(f.read()).decode()
        if conf.get("youtube_playlists"):
            try:
                on = youtube_channel.now_playing(conf["network_name"])
            except Exception as e:
                self._l.warning(f"Could not look up what's on {conf['network_name']}: {e}")
                on = None
            if on:
                game = on.get("game")
                info["title"] = game["matchup"] if game else on["title"]
                info["subtitle"] = " · ".join(x for x in (game["date"], game["note"]) if x) if game else ""
                start = now - datetime.timedelta(seconds=on["offset"])
                end = now + datetime.timedelta(seconds=on["remaining"])
                info["slot"] = f"{short_time(start)} - {short_time(end)}"
        return info

    def show_volume(self, level, muted):
        """The volume read-out after a volume or mute press - in the page when a web
        channel (the guide, a menu) is in front, since mpv's OSD is hidden under it."""
        if self.web_process is not None and self.web_queue:
            self.web_queue.put("volume:" + json.dumps({"level": level, "muted": muted}))
        else:
            self.notice_osd.hide()
            self.volume_osd.show(level, muted)

    def show_channel_entry(self, digits):
        """The channel number being typed, top right - in the page when a web channel is in front."""
        if self.web_process is not None and self.web_queue:
            self.web_queue.put("entry:" + json.dumps({"digits": digits}))
        else:
            self.channel_entry.show(digits)

    def show_notice_invalid(self):
        """ACTION NOT VALID, low on the screen - in the page when a web channel is in front."""
        if self.web_process is not None and self.web_queue:
            self.web_queue.put("notice:" + json.dumps({"text": "ACTION NOT VALID"}))
        else:
            # they share the bottom of the screen - the newest one wins
            self.volume_osd.hide()
            self.notice_osd.invalid()

    def toggle_banner(self):
        """INFO button: show the channel banner for what's on now, or hide it if it's up."""
        if self.web_process is not None:
            # a web channel draws it in its page; the guide and menu have their own screens
            info = self._web_banner(self.station_config)
            if info and self.web_queue:
                self.web_queue.put("banner:" + json.dumps(info))
            return
        if self.banner.showing:
            self.banner.hide()
            return
        network_name = self.station_config["network_name"]
        try:
            if self.plays_youtube(self.station_config):
                block = self._youtube_block(self._youtube_entry(network_name))
            else:
                block = LiquidManager().get_programming_block(network_name, datetime.datetime.now())
        except Exception:
            block = None
        self.banner.show(self.station_config, block)

    def _relayout_video(self):
        # mpv only works out the screen's pixel shape when the video is reconfigured,
        # so a new monitoraspect does nothing mid-file. Nudging the aspect override
        # forces that reconfigure without reloading the file.
        try:
            params = self.mpv.command("get_property", "video-params")
        except Exception:
            params = None  # mpv reports the property as unavailable while idle
        if not params:
            return  # nothing loaded - the next file picks the new shape up
        fullscreen = self.mpv.command("get_property", "fullscreen")
        self.mpv.command("set_property", "video-aspect-override", params["aspect"] * 1.01)
        time.sleep(0.1)
        self.mpv.command("set_property", "video-aspect-override", "-1")
        # a reconfigure can resize a windowed mpv, so put the window back how it was
        if self._guide_preview_active and self._guide_preview_rect:
            self._start_guide_preview(self._guide_preview_rect)
        elif fullscreen and not self.mpv.command("get_property", "fullscreen"):
            self.mpv.command("set_property", "fullscreen", True)

    def load_up(self):
        start_time = time.perf_counter()
        liquid = LiquidManager()
        liquid_init_time = time.perf_counter() - start_time
        self._l.info(f"LiquidManager() initialization took {liquid_init_time:.3f} seconds")

    def show_text(self, text, duration=4):
        self.mpv.command("show-text", text, duration)

    # the yellow and blue buttons - the remotes send these as cycle_audio / cycle_subtitles
    TRACK_PICKER_COMMANDS = {"cycle_audio": "audio", "cycle_subtitles": "sub"}

    def mpv_runtime_command(self, action):
        """Run a small set of user-facing mpv runtime commands."""
        if action in self.TRACK_PICKER_COMMANDS:
            if self.web_process is None:
                self.track_picker.press(self.TRACK_PICKER_COMMANDS[action])
            return True
        mpv_command = self.MPV_RUNTIME_COMMANDS.get(action)
        if not mpv_command:
            self._l.warning(f"Unknown mpv runtime command: {action}")
            return False

        try:
            self.mpv.command(*mpv_command)
            self._l.info(f"Ran mpv runtime command: {action}")
            return True
        except Exception as e:
            self._l.warning(f"Failed to run mpv runtime command {action}: {e}")
            return False

    def handle_runtime_command_outcome(self, response):
        """Handle non-interrupting player commands and continue playback."""
        if (
            response
            and response.status == PlayerState.SUCCESS
            and isinstance(response.payload, str)
            and response.payload.startswith("mpv_command:")
        ):
            action = response.payload.split(":", 1)[1]
            self.mpv_runtime_command(action)
            return True

        if (
            response
            and response.status == PlayerState.SUCCESS
            and isinstance(response.payload, str)
            and response.payload.startswith("entry:")
        ):
            self.show_channel_entry(response.payload.split(":", 1)[1])
            return True

        if (
            response
            and response.status == PlayerState.SUCCESS
            and isinstance(response.payload, str)
            and response.payload.startswith("trick:")
        ):
            # play/pause/ff/rewind only work in an on-demand movie (play_and_wait takes
            # them before they get here) - anywhere else, say so
            self.show_notice_invalid()
            return True

        if (
            response
            and response.status == PlayerState.SUCCESS
            and isinstance(response.payload, str)
            and response.payload.startswith("volume:")
        ):
            _, level, muted = response.payload.split(":")
            self.show_volume(int(level), muted == "1")
            return True

        if (
            response
            and response.status == PlayerState.SUCCESS
            and response.payload == "banner"
        ):
            self.toggle_banner()
            return True

        if (
            response
            and response.status == PlayerState.SUCCESS
            and response.payload == "apply_settings"
        ):
            self.apply_user_settings()
            return True

        return False

    @staticmethod
    def is_non_interrupting(response):
        return response.status == PlayerState.SUCCESS

    def _start_parental_controls_overlay(self, network_name):
        self._close_parental_controls_overlay()

        try:
            from fs42.overlay.parental_controls import run_parental_controls

            self.parental_controls_queue = multiprocessing.Queue()
            self.parental_controls_process = run_parental_controls(
                network_name,
                self.parental_controls_queue,
                self._parental_controls_theme(),
            )
            self._update_parental_controls_overlay()
        except Exception as e:
            self._l.warning(f"Could not start parental controls overlay: {e}")
            self.parental_controls_process = None
            self.parental_controls_queue = None

    def _update_parental_controls_overlay(self, digits=0, error=False):
        if self.parental_controls_queue:
            self.parental_controls_queue.put({
                "digits": digits,
                "error": error
            })

    def _close_parental_controls_overlay(self):
        if self.parental_controls_queue:
            try:
                self.parental_controls_queue.put({"close": True})
            except Exception:
                pass

        if self.parental_controls_process and self.parental_controls_process.is_alive():
            try:
                self.parental_controls_process.join(timeout=0.2)
                if self.parental_controls_process.is_alive():
                    self.parental_controls_process.terminate()
                    self.parental_controls_process.join(timeout=0.2)
                if self.parental_controls_process.is_alive():
                    self.parental_controls_process.kill()
                    self.parental_controls_process.join(timeout=0.1)
            except Exception as e:
                self._l.warning(f"Error terminating parental controls overlay: {e}")

        self.parental_controls_process = None
        self.parental_controls_queue = None

    def _parental_controls_pin(self):
        pin = str(StationManager().server_conf.get("parental_controls_pin", ""))
        if len(pin) == 4 and pin.isdigit():
            return pin

        if pin:
            self._l.warning("parental_controls_pin must be exactly 4 digits")
        return None

    def _parental_controls_theme(self):
        theme = StationManager().server_conf.get("parental_controls_theme", "minimal")
        if theme in ("classic", "modern", "minimal"):
            return theme

        self._l.warning(f"Unknown parental_controls_theme: {theme}")
        return "minimal"

    def _parental_controls_required(self, network_name):
        if not self._parental_controls_pin():
            return False

        station_config = StationManager().station_by_name(network_name)
        if not station_config:
            return False

        station_conf = station_config.get("station_conf", {})
        return bool(
            station_config.get("parental_controls")
            or station_conf.get("parental_controls")
        )

    def prompt_parental_controls(self, station_config):
        network_name = station_config["network_name"]
        channel_number = station_config["channel_number"]
        pin = self._parental_controls_pin()

        if not pin:
            return PlayerOutcome(PlayerState.SUCCESS)

        entered = ""
        self.stop_player()
        self._start_parental_controls_overlay(network_name)
        update_status_socket(
            "playing",
            network_name,
            channel_number,
            title="Parental Controls",
            awaiting_pin=True,
            pin_digits_entered=0,
        )

        try:
            while True:
                response = self.input_check_fn()
                if not response:
                    time.sleep(0.05)
                    continue

                if self.handle_runtime_command_outcome(response):
                    continue

                if response.status != PlayerState.SUCCESS:
                    return response

                if not isinstance(response.payload, str):
                    continue

                if response.payload.startswith("parental_digit:"):
                    digit = response.payload.split(":", 1)[1]
                    if not digit.isdigit() or len(digit) != 1:
                        continue

                    entered += digit
                    self._update_parental_controls_overlay(len(entered), False)
                    update_status_socket(
                        "playing",
                        network_name,
                        channel_number,
                        title="Parental Controls",
                        awaiting_pin=True,
                        pin_digits_entered=len(entered),
                    )

                    if len(entered) >= len(pin):
                        if entered == pin:
                            self.parental_unlocked_network = network_name
                            return PlayerOutcome(PlayerState.SUCCESS)

                        entered = ""
                        self._update_parental_controls_overlay(0, True)
                        update_status_socket(
                            "playing",
                            network_name,
                            channel_number,
                            title="Parental Controls",
                            awaiting_pin=True,
                            pin_digits_entered=0,
                        )

                elif response.payload == "parental_clear":
                    entered = ""
                    self._update_parental_controls_overlay(0, False)
                    update_status_socket(
                        "playing",
                        network_name,
                        channel_number,
                        title="Parental Controls",
                        awaiting_pin=True,
                        pin_digits_entered=0,
                    )
        finally:
            self._close_parental_controls_overlay()
            update_status_socket(
                "idle",
                network_name,
                channel_number,
                awaiting_pin=False,
                pin_digits_entered=0,
            )

    def _close_now_playing(self):
        # terminate the Now Playing overlay if it's running
        if self.now_playing_process and self.now_playing_process.is_alive():
            try:
                self.now_playing_process.terminate()
                self.now_playing_process.join(timeout=0.2)

                # Force kill if still alive
                if self.now_playing_process.is_alive():
                    self.now_playing_process.kill()
                    self.now_playing_process.join(timeout=0.1)

                self._l.debug("Closed Now Playing overlay")
            except Exception as e:
                self._l.warning(f"Error terminating overlay: {e}")

            self.now_playing_process = None

    def _nfo_overlay_data(self, file_path):

        from fs42.metadata_io import MetadataIO
        from fs42.nfo_agent import NFOAgent, NFOData

        meta = MetadataIO.read(file_path)
        lines = NFOAgent.overlay_lines(meta)
        return NFOData(lines) if lines else None

    def _read_playback_metadata(self, file_path):
        from fs42.metadata_io import MetadataIO
        return MetadataIO.read(file_path) or {}

    def _show_now_playing(self, file_path):
        # show the Now Playing overlay for an audio file
        import time
        self._close_now_playing()
        # give a brief moment for cleanup
        time.sleep(0.1)

        # Start new overlay
        try:
            from fs42.overlay.now_playing import run_now_playing
            db_path = StationManager().server_conf["db_path"]
            self.now_playing_process = run_now_playing(file_path, db_path)
            self._l.info(f"Started Now Playing overlay for {file_path}")
        except Exception as e:
            self._l.error(f"Failed to start Now Playing overlay: {e}")

    def _show_stream_down(self):
        """Stop playback and display a stream-unavailable OSD message."""
        message = "TECHNICAL DIFFICULTIES"
        if self.station_config:
            message = self.station_config.get("stream_down_message", message)
        self._l.warning(f"Stream down — showing fallback: {message}")
        try:
            self.mpv.command("playlist-clear")
            self.mpv.stop()
        except Exception:
            pass
        try:
            self.mpv.command("show-text", message, 10000)
        except Exception as e:
            self._l.debug(f"Could not show stream down OSD: {e}")

    def shutdown(self):
        self.current_playing_file_path = None
        self.release_parked_web()
        # Terminate any running web process
        if self.web_process and self.web_process.is_alive():
            self._l.info("Terminating web process")
            try:
                if self.web_queue:
                    self.web_queue.put("hide_window")
                self.web_process.join(timeout=2)
            except Exception:
                pass

            # Check if process is still alive and has valid _popen
            if self.web_process and hasattr(self.web_process, '_popen') and self.web_process._popen and self.web_process.is_alive():
                try:
                    self.web_process.terminate()
                    self.web_process.join(timeout=1)
                except Exception:
                    pass

        self.web_process = None
        self.web_queue = None

        self._close_parental_controls_overlay()

        # Terminate any running now playing overlay
        self._l.info("Terminating now playing overlay")
        self._close_now_playing()

        self.mpv.terminate()

    def update_filters(self):
        self.mpv.vf = self.reception.filter()

    def update_reception(self):
        if self.reception.is_perfect():
            return
        self.reception.improve()
        try:
            self.mpv.vf = "" if self.reception.is_perfect() else self.reception.filter()
        except TimeoutError:
            self._l.warning("mpv did not respond to reception filter update")

    def play_file(self, file_path, file_duration=None, offset_seconds=None, is_stream=False, title="Unknown", content_type=None, media_type=None):
        try:
            if os.path.exists(file_path) or is_stream or AutoBumpAgent.is_autobump_url(file_path):
                self._l.debug(f"%%%Attempting to play {file_path}")
                self.current_playing_file_path = file_path

                if self.station_config:
                    self._l.debug("Got station config, updating status socket")
                    if "date_time_format" in StationManager().server_conf:
                        ts_format = StationManager().server_conf["date_time_format"]
                    else:
                        ts_format = "%Y-%m-%dT%H:%M:%S"
                    duration = (
                        f"{str(datetime.timedelta(seconds=int(offset_seconds)))}/{str(datetime.timedelta(seconds=int(file_duration)))}"
                        if file_duration
                        else "n/a"
                    )
                    metadata = {}
                    if media_type == "video" and not is_stream:
                        try:
                            metadata = self._read_playback_metadata(file_path)
                        except Exception as e:
                            self._l.warning(
                                f"Could not read playback metadata: {e}"
                            )

                    update_status_socket(
                        "playing",
                        self.station_config["network_name"],
                        self.station_config["channel_number"],
                        title,
                        timestamp=ts_format,
                        duration=duration,
                        file_path=file_path,
                        content_type=content_type,
                        metadata=metadata,
                    )
                          
                else:
                    self._l.warning(
                        "station_config not available in play_file, cannot update status socket with title."
                    )
                
                                #now see if this is an autobump

                if AutoBumpAgent.is_autobump_url(file_path):
                    from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
                    web_url = AutoBumpAgent.extract_url(file_path)
                    remaining = file_duration - (offset_seconds or 0) if file_duration else None
                    if remaining is not None:
                        parsed = urlparse(web_url)
                        params = parse_qs(parsed.query, keep_blank_values=True)
                        params['duration'] = [str(int(remaining * 1000))]
                        web_url = urlunparse(parsed._replace(query=urlencode({k: v[0] for k, v in params.items()})))
                    conf = {
                        "web_url": web_url
                    }
                    if remaining:
                        conf["duration"] = remaining
                    self.show_web(conf, blocking=False)
                    return True

                self.mpv.panscan = self._panscan()

                if "video_keepaspect" in self.station_config:
                    self.mpv.keepaspect = self.station_config["video_keepaspect"]
                else:
                    self.mpv.keepaspect = True

                self._apply_vfx(datetime.datetime.now())

                # self.mpv.vf = "lavfi=[]"
                if not is_stream and self._already_playing(file_path, offset_seconds):
                    # kept running behind the settings menu - carry on rather than reload
                    self._l.info(f"already playing {file_path} at the scheduled spot - continuing")
                else:
                    self._l.info(f"playing {file_path}")
                    self._prepare_tracks()
                    self.mpv.command("playlist-clear")
                    self.mpv.play(file_path)
                

                    timeout_seconds = StationManager().server_conf.get("video_seek_timeout", 10)
                    start_time = time.time()

                    while True:
                        try:
                            if self.mpv.time_pos is not None:
                                break
                            if time.time() - start_time > timeout_seconds:
                                self._l.error(f"Timeout waiting for playback to start on {file_path}")
                                return False
                            if is_stream:
                                response = self.input_check_fn()
                                if (
                                    response
                                    and not self.handle_runtime_command_outcome(response)
                                    and not self.is_non_interrupting(response)
                                ):
                                    self._pending_response = response
                                    return False
                            time.sleep(0.05)
                        except Exception as e:
                            if time.time() - start_time > timeout_seconds:
                                self._l.error(f"Error waiting for playback: {e}")
                                return False
                            time.sleep(0.05)

                    self._choose_tracks()

                    # Perform seek if needed (before showing overlay)
                    if not is_stream and offset_seconds is not None and offset_seconds > 0:
                        self._seek_with_verify(file_path, offset_seconds, timeout_seconds)

                # Show Now Playing overlay for audio feature files
                self._l.info(f"Media type: {media_type}, Content type: {content_type}")
                if media_type == 'audio' and content_type == 'feature':
                    self._show_now_playing(file_path)
                elif media_type == 'video':
                    # Always close any existing overlay when a new video starts,
                    # then spawn a new one only if this video has an NFO sidecar.
                    self._close_now_playing()
                    try:
                        nfo_data = self._nfo_overlay_data(file_path)
                        if nfo_data:
                            play_duration = None
                            if file_duration is not None:
                                play_duration = file_duration - (offset_seconds or 0)
                            from fs42.nfo_agent import NFOAgent
                            self.now_playing_process = NFOAgent.show_overlay(nfo_data, play_duration=play_duration)
                    except Exception as e:
                        self._l.warning(f"Could not start NFO overlay: {e}")

                return True
            else:
                self._l.error(
                    f"Trying to play file {file_path} but it doesn't exist - check your configuration and try again."
                )
                return False
        except Exception as e:
            self._l.exception(e)
            self._l.error(
                f"Encountered unknown error attempting to play {file_path} - please check your configurations."
            )
            return False

    def _seek_with_verify(self, file_path, offset_seconds, timeout_seconds,
                          tolerance=1.0, verify_window=2.0, retry_delay=0.2):

        def safe_prop(name, default=None):
            try:
                return getattr(self.mpv, name)
            except Exception:
                return default

        deadline = time.time() + timeout_seconds
        attempt = 0

        while time.time() < deadline:
            attempt += 1

            try:
                self.mpv.command("seek", offset_seconds, "absolute")
            except Exception as e:
                self._l.debug(f"Seek not accepted yet on {file_path}: {e} (attempt {attempt})")
                time.sleep(retry_delay)
                continue

            patience = time.time() + verify_window
            while time.time() < deadline:
                pos = safe_prop("time_pos")
                if pos is not None and abs(pos - offset_seconds) <= tolerance:
                    self._l.info(f"Seek landed at {pos:.2f} (target {offset_seconds}, attempt {attempt})")
                    return
                if safe_prop("seeking"):
                    patience = time.time() + verify_window
                elif time.time() >= patience:
                    break  # idle and not landed -> dropped, re-issue
                time.sleep(0.05)

            self._l.debug(f"Seek to {offset_seconds} on {file_path} did not land (attempt {attempt}); retrying")
            time.sleep(retry_delay)

        self._l.error(
            f"Seek to {offset_seconds} on {file_path} failed to land within {timeout_seconds}s; "
            f"playback may be starting from the wrong position"
        )

    def play_and_wait(self, file_path):
        self._l.info(f"Play and wait on file {file_path}")
        self._close_now_playing()
        self.mpv.vf = ""
        if self._active_afx:
            self.mpv.command("af", "remove", self._active_afx)
            self._active_afx = None
        self.apply_audio_normalize()
        self.mpv.command("playlist-clear")
        # an on-demand movie plays once, then it's back to the menu. keep-open holds the
        # last frame at the end instead of mpv dropping to idle, which can lock up its
        # video output - the end shows up as eof-reached instead
        self.mpv.loop_playlist = "no"
        self.mpv.command("loadfile", file_path, "replace", -1, "keep-open=yes")
        self.current_playing_file_path = file_path
        self._take_focus()

        # BACK/EXIT on the remote goes back to the menu while this is on
        title = os.path.splitext(os.path.basename(file_path))[0]
        if self.station_config:
            update_status_socket(
                "playing",
                self.station_config["network_name"],
                self.station_config["channel_number"],
                title,
                file_path=file_path,
                content_type="on_demand",
            )

        # show NFO overlay if the file has overlay-eligible cached metadata
        try:
            nfo_data = self._nfo_overlay_data(file_path)
            if nfo_data:
                from fs42.nfo_agent import NFOAgent
                self.now_playing_process = NFOAgent.show_overlay(nfo_data)
        except Exception as e:
            self._l.warning(f"Could not start NFO overlay: {e}")

        # play/pause/fast forward/rewind from the remote, with a bar across the bottom
        trick = TrickPlay(self.mpv, title)

        # this will keep going until the movie ends, a channel change or other interrupt
        started = False
        load_deadline = time.time() + 30
        while True:
            time.sleep(0.05)
            trick.tick()
            try:
                ended = self.mpv.command("get_property", "eof-reached")
                # mpv reports the path its own way, so match on the file name
                loaded = os.path.basename(self.mpv.command("get_property", "path") or "") == os.path.basename(file_path)
            except Exception:
                ended, loaded = False, False
            if loaded and not ended:
                started = True
            if (started and ended) or (not started and time.time() > load_deadline):
                # the movie finished (or never would load) - the main loop puts the menu back up
                self._l.info(f"On-demand playback of {file_path} ended")
                self._close_now_playing()
                trick.reset()
                self._unpause()
                return PlayerOutcome(PlayerState.SUCCESS)
            response = self.input_check_fn()
            if response:
                if isinstance(response.payload, str) and response.payload.startswith("trick:"):
                    trick.press(response.payload.split(":", 1)[1])
                    continue
                if self.handle_runtime_command_outcome(response):
                    continue
                if self.is_non_interrupting(response):
                    self._l.debug(f"Ignoring non-interrupting command during playback: {response.payload}")
                    continue
                self._close_now_playing()
                trick.reset()
                self._unpause()
                return response

    def _unpause(self):
        # keep-open leaves mpv paused on a movie's last frame, and it would stay paused
        # for whatever loads next - swap in a black frame and play on
        try:
            self.mpv.command("loadfile", "runtime/black.png", "replace")
            self.mpv.pause = False
        except Exception as e:
            self._l.debug(f"Could not unpause mpv: {e}")

    def play_file_list(self, file_list):

        try:
            # Filter out any files that don't exist
            valid_files = [f for f in file_list if os.path.exists(f)]

            if not valid_files:
                self._l.error("No valid audio files found in playlist")
                return False
    
            random.shuffle(valid_files)

            self._l.info(f"Starting shuffle playlist with {len(valid_files)} files")

            # Clear any existing playlist and load the files
            self.current_playing_file_path = "playlist"

            self.mpv.command("playlist-clear")

            # Load files using loadfile with 'append' flag
            for i, file_path in enumerate(valid_files):
                self._l.debug(f"Adding to playlist: {file_path}")
                if i == 0:
                    self.mpv.command("loadfile", file_path, "replace")
                else:
                    self.mpv.command("loadfile", file_path, "append")

            self.mpv.loop_playlist = "inf"
            self._l.info("Starting playlist playback")

            return True

        except Exception as e:
            self._l.exception(e)
            self._l.error(f"Error starting playlist: {e}")
            return False

    def _apply_vfx(self, current_time):
        vfx = None
        if "video_scramble_fx" in self.station_config:
            vfx = self.station_config["video_scramble_fx"]
        elif "station_fx" in self.station_config:
            vfx = "station_fx"
            self.scramble_effects["station_fx"] = self.station_config["station_fx"]

        # check if one is set on the slot and override if so
        slot = SlotReader.get_slot(self.station_config, current_time)
        if slot and "video_scramble_fx" in slot:
            if slot["video_scramble_fx"] in self.scramble_effects:
                vfx = slot["video_scramble_fx"]
            else:
                vfx = None

        if vfx:
            if vfx in self.scramble_effects:
                self.mpv.vf = self.scramble_effects[vfx]
                self.skip_reception_check = True
                if vfx == "horizontal_line":
                    self.scrambler = HLScrambledVideoFilter()
                elif vfx == "diagonal_lines":
                    self.scrambler = DiagonalScrambledVideoFilter()
                elif vfx == "color_inversion":
                    self.scrambler = ColorInvertedScrambledVideoFilter()
                elif vfx == "chunky_scramble":
                    self.scrambler = ChunkyScrambledVideoFilter()
            else:
                self._l.warning(f"Scrambler effect '{self.station_config['video_scramble_fx']}' does not exist.")
        else:
            self.skip_reception_check = False
            self.mpv.vf = ""
            self.scrambler = None

        # Apply audio scramble filter if configured
        afx = None
        if "audio_scramble_fx" in self.station_config:
            afx = self.station_config["audio_scramble_fx"]
        if slot and "audio_scramble_fx" in slot:
            afx = slot["audio_scramble_fx"]
        new_afx = self.audio_scramble_effects.get(afx) if afx else None
        if self._active_afx and self._active_afx != new_afx:
            self.mpv.command("af", "remove", self._active_afx)
            self._active_afx = None
        if new_afx and new_afx != self._active_afx:
            self.mpv.command("af", "add", new_afx)
            self._active_afx = new_afx
        elif afx and afx not in self.audio_scramble_effects:
            self._l.warning(f"Audio scramble effect '{afx}' does not exist.")

    def play_image(self, duration):
        pass

    def show_guide(self, guide_config):
        # create the pipe to communicate with the guide channel
        queue = multiprocessing.Queue()
        guide_process = multiprocessing.Process(
            target=guide_channel_runner,
            args=(
                guide_config,
                queue,
            ),
        )
        guide_process.start()

        if "play_sound" in guide_config and guide_config["play_sound"]:
            sound_to_play = guide_config["sound_to_play"]

            # Normalize sound_to_play to always be a list
            if isinstance(sound_to_play, str):
                # Check if it's a directory (with or without trailing slash)
                if os.path.isdir(sound_to_play):
                    # Find all mp3 files in the directory
                    mp3_files = glob.glob(os.path.join(sound_to_play, "*.mp3"))
                    if mp3_files:
                        sound_to_play = sorted(mp3_files)
                        self._l.info(f"Expanded directory {guide_config['sound_to_play']} to {len(sound_to_play)} mp3 files")
                    else:
                        self._l.error(f"Directory {sound_to_play} contains no mp3 files")
                        sound_to_play = []
                else:
                    # Single file - wrap in a list
                    sound_to_play = [sound_to_play]
            elif not isinstance(sound_to_play, list):
                self._l.error(f"Invalid sound_to_play configuration: {type(sound_to_play)}")
                sound_to_play = []

            # Now sound_to_play is always a list
            if len(sound_to_play) == 0:
                # No valid files
                self.mpv.stop()
                self.current_playing_file_path = None
            elif len(sound_to_play) == 1:
                # Single file - use the simple play_file method
                self._l.info(f"Playing guide audio from single file: {sound_to_play[0]}")
                playing = self.play_file(sound_to_play[0])
                if not playing:
                    self.mpv.stop()
                    self.current_playing_file_path = None
            else:
                # Multiple files - use shuffle playlist
                self._l.info(f"Playing guide audio as shuffle playlist with {len(sound_to_play)} files")
                playing = self.play_file_list(sound_to_play)
                if not playing:
                    self.mpv.stop()
                    self.current_playing_file_path = None
        else:
            self.mpv.stop()
            self.current_playing_file_path = None

        # update status
        update_status_socket(
            "playing",
            self.station_config["network_name"],
            self.station_config["channel_number"],
            self.station_config["network_name"],
            timestamp=StationManager().server_conf["date_time_format"],
            content_type="guide",
        )
        keep_going = True
        while keep_going:
            time.sleep(0.05)
            response = self.input_check_fn()
            if response:
                if self.handle_runtime_command_outcome(response):
                    continue
                if self.is_non_interrupting(response):
                    self._l.debug(f"Ignoring non-interrupting command on guide channel: {response.payload}")
                    continue
                self._l.info("Sending the guide channel shutdown command")
                queue.put(GuideCommands.hide_window)
                guide_process.join()
                return response

        return PlayerOutcome(PlayerState.SUCCESS)


    def stop_player(self):
        try:
            self.mpv.stop()
            self.current_playing_file_path = None
        except Exception:
            self._l.error(f"Failed to stop player - might not be running")

    def _start_guide_preview(self, rect):
        # park the still-playing mpv window over the guide's preview panel
        try:
            x, y, w, h = (int(v) for v in rect.split(","))
            self.mpv.command("set_property", "fullscreen", False)
            self.mpv.command("set_property", "border", False)
            self.mpv.command("set_property", "geometry", f"{w}x{h}+{x}+{y}")
            self.mpv.command("set_property", "ontop", True)
            # leaving fullscreen can land after the geometry, and the window manager
            # then sizes the window to the video - so check, and put it back if so
            for _ in range(5):
                time.sleep(0.2)
                dims = self.mpv.command("get_property", "osd-dimensions")
                if abs(dims["w"] - w) <= 2 and abs(dims["h"] - h) <= 2:
                    break
                self.mpv.command("set_property", "geometry", f"{w}x{h}+{x}+{y}")
            else:
                self._l.warning(f"mpv window did not settle at {w}x{h} for the guide preview")
            self._guide_preview_active = True
            self._guide_preview_rect = rect
            self._raise_guide_preview()
            # the guide window can still be mapping and get stacked over it - again shortly
            raise_again = threading.Timer(2.0, self._raise_guide_preview)
            raise_again.daemon = True
            raise_again.start()
            self._l.info(f"Guide preview placed at {w}x{h}+{x}+{y}")
        except Exception as e:
            self._l.warning(f"Could not start guide preview: {e}")

    def _raise_guide_preview(self):
        # setting ontop when it's already on does nothing, so a guide window that got
        # raised over the preview stays there (a black panel) - drop it and set it again,
        # which makes the window manager restack mpv on top
        if not self._guide_preview_active:
            return
        try:
            self.mpv.command("set_property", "ontop", False)
            self.mpv.command("set_property", "ontop", True)
        except Exception as e:
            self._l.debug(f"Could not raise guide preview: {e}")

    def _guide_preview_entry_end(self, network_name):
        # when the entry the channel is airing now is scheduled to end
        try:
            now = datetime.datetime.now()
            if self.plays_youtube(StationManager().station_by_name(network_name)):
                entry = self._youtube_entry(network_name)
                return now + datetime.timedelta(seconds=entry["remaining"]) if entry else None
            play_point = LiquidManager().get_play_point(network_name, now)
            if play_point is None or not play_point.plan:
                return None
            entry = play_point.plan[play_point.index]
            return now + datetime.timedelta(seconds=entry.duration - play_point.offset)
        except Exception as e:
            self._l.warning(f"Could not find schedule entry for guide preview: {e}")
            return None

    def _advance_guide_preview(self, network_name):
        # the previewed entry ended - load whatever the channel is airing now into the preview
        try:
            if self.plays_youtube(StationManager().station_by_name(network_name)):
                entry = self._youtube_entry(network_name)
                if entry is None or self._load_youtube(entry, watch_input=False) is not True:
                    return False
                if self._guide_preview_active and self._guide_preview_rect:
                    self._start_guide_preview(self._guide_preview_rect)
                return True
            play_point = LiquidManager().get_play_point(network_name, datetime.datetime.now())
            if play_point is None or not play_point.plan:
                return False
            entry = play_point.plan[play_point.index]
            if getattr(entry, "is_stream", False) or AutoBumpAgent.is_autobump_url(entry.path):
                return False
            self._l.info(f"Guide preview advancing to {entry.path}")
            self.mpv.command("playlist-clear")
            self.mpv.play(entry.path)
            timeout_seconds = StationManager().server_conf.get("video_seek_timeout", 10)
            start_time = time.time()
            while self.mpv.time_pos is None:
                if time.time() - start_time > timeout_seconds:
                    self._l.warning(f"Timeout waiting for guide preview to start on {entry.path}")
                    return False
                time.sleep(0.05)
            skip = entry.skip + play_point.offset
            if skip > 0:
                self._seek_with_verify(entry.path, skip, timeout_seconds)
            self.current_playing_file_path = entry.path
            # a new file can make mpv resize its window, so put it back over the panel
            if self._guide_preview_active and self._guide_preview_rect:
                self._start_guide_preview(self._guide_preview_rect)
            return True
        except Exception as e:
            self._l.warning(f"Could not advance guide preview: {e}")
            return False

    def _end_guide_preview(self):
        if not self._guide_preview_active:
            return
        self._guide_preview_active = False
        try:
            self.mpv.command("set_property", "ontop", False)
            self.mpv.command("set_property", "geometry", "")
            # border is left off - it doesn't show in fullscreen, and re-adding it makes
            # the window manager re-decorate the window, which can swallow the fullscreen request
            for _ in range(5):
                self.mpv.command("set_property", "fullscreen", True)
                time.sleep(0.2)
                if self.mpv.command("get_property", "fullscreen"):
                    break
            else:
                self._l.warning("mpv did not return to fullscreen after guide preview")
        except Exception as e:
            self._l.warning(f"Could not restore mpv after guide preview: {e}")

    def show_web(self, web_config, blocking=True):
        if not WEB_RENDER_AVAILABLE:
            self._l.error("Web rendering not available - PySide6 not installed")
            msg = "Web rendering requires PySide6 to be installed and configured. Please check documentation."
            return PlayerOutcome(PlayerState.EXIT_COMMAND, msg)

        # a web channel left running under the guide or menu: tuning back to it picks it
        # up where it is, and a guide previews it in place of mpv
        parked = self._parked_web
        resume_parked = parked is not None and parked[0] == web_config["network_name"]
        web_preview = parked is not None and not resume_parked and web_config.get("guide_preview", False)
        if parked is not None and not (resume_parked or web_preview or web_config.get("keep_playing", False)):
            self.release_parked_web()

        # Keep the current channel playing for a guide that previews it - but only a
        # real channel, not the startup standby image or nothing at all.
        standby = StationManager().server_conf.get("standby_image", "runtime/standby.png")
        playing_real_channel = self.current_playing_file_path not in (None, standby)
        guide_preview = web_config.get("guide_preview", False) and playing_real_channel
        # keep_playing leaves the channel running behind the page (the settings menu),
        # so its audio carries on and it is still playing when the page closes
        keep_playing = (guide_preview or web_config.get("keep_playing", False)) and playing_real_channel

        if resume_parked:
            _, self.web_process, self.web_queue = parked
            self._parked_web = None
            self.web_queue.put("fullscreen")
        else:
            ctx = multiprocessing.get_context("spawn")

            # create the pipe to communicate with the web channel - telling it whether it is
            # really previewing, since that decides how its window stacks against mpv, and
            # whether a parked web channel will be raised over it into its preview panel
            self.web_queue = ctx.Queue()
            self.web_process = ctx.Process(
                target=web_render_runner,
                args=(
                    {**web_config, "guide_preview": guide_preview, "web_preview": web_preview,
                     "web_url": self._guide_url(web_config)},
                    self.web_queue,
                ),
            )
            self.web_process.start()

        # the banner belongs to the channel being left; a web channel's page draws its own
        # (the guide and menu have none, and the bug would only be a speck in the guide's preview)
        self.banner.hide()
        if user_settings.load_settings()["channel_banner"] == "on" and not (guide_preview or web_preview):
            info = self._web_banner(web_config)
            if info:
                # the page shows it once it has loaded
                self.web_queue.put("banner:" + json.dumps(info))
        self.bug.hide()
        self.track_picker.hide()
        self.banner_pending = False
        self._banner_request = None

        # Stop any currently playing content - unless it keeps running behind this page.
        if not keep_playing:
            self.mpv.stop()
            # a file kept playing keeps its path, so re-tuning the guide keeps the preview
            self.current_playing_file_path = None

        # update status
        update_status_socket(
            "playing",
            self.station_config["network_name"],
            self.station_config["channel_number"],
            self.station_config.get("network_long_name") or self.station_config["network_name"],
            timestamp=StationManager().server_conf["date_time_format"],
            content_type="web",
        )

        if not blocking:
            return PlayerOutcome(PlayerState.SUCCESS)

        # Check if duration is specified for auto-bumps
        duration = web_config.get("duration")
        stop_time = None
        if duration:
            stop_time = datetime.datetime.now() + datetime.timedelta(seconds=duration)
            self._l.info(f"Web content will auto-stop after {duration} seconds")

        # follow the previewed channel's schedule so the next entry plays in the preview
        preview_network = self._preview_network if keep_playing else None
        preview_end = self._guide_preview_entry_end(preview_network) if preview_network else None

        # a full-screen page outside the window manager's control can end up under the
        # desktop taskbar (it gets restacked when nothing has focus), so while this is
        # the channel on screen, have it raise itself now and then - a page parked in
        # the background never gets asked, so it can't come up over the guide
        raise_page = not (guide_preview or web_config.get("guide_preview") or keep_playing)
        next_raise = time.time() + 2

        keep_going = True
        while keep_going:
            time.sleep(0.05)

            if raise_page and self.web_queue and time.time() >= next_raise:
                self.web_queue.put("raise")
                next_raise = time.time() + 2

            # mpv keeps playing under a previewing guide, so let the
            # channel-change static clear like it does during normal playback
            if keep_playing:
                self.update_reception()

            if preview_end and datetime.datetime.now() >= preview_end:
                if self._advance_guide_preview(preview_network):
                    preview_end = self._guide_preview_entry_end(preview_network)
                else:
                    # try again shortly rather than leaving the preview dead
                    preview_end = datetime.datetime.now() + datetime.timedelta(seconds=5)

            # Check if duration has expired
            if stop_time and datetime.datetime.now() >= stop_time:
                self._l.info("Web content duration expired, shutting down")
                try:
                    self.web_queue.put("hide_window")
                    self._l.info("Sent hide_window message to web process")
                    self.web_process.join(timeout=3)  # Wait up to 3 seconds
                    if self.web_process.is_alive():
                        self._l.warning("Web process did not terminate gracefully, forcing termination")
                        self.web_process.terminate()
                        self.web_process.join(timeout=1)
                    self._l.info("Web process terminated successfully")
                except Exception as e:
                    self._l.error(f"Error shutting down web process: {e}")
                finally:
                    self.web_process = None
                    self.web_queue = None
                self._end_guide_preview()
                return PlayerOutcome(PlayerState.SUCCESS)

            response = self.input_check_fn()
            if response:
                if isinstance(response.payload, str) and response.payload.startswith("preview_rect:"):
                    rect = response.payload[len("preview_rect:"):]
                    if guide_preview:
                        self._start_guide_preview(rect)
                    elif web_preview and self._parked_web:
                        self._parked_web[2].put(f"geometry:{rect}")
                        self._l.info(f"Guide preview of {self._parked_web[0]} placed at {rect}")
                    continue
                # Check if this is a web_key command - forward to web process
                if self.handle_runtime_command_outcome(response):
                    continue
                if response.payload and isinstance(response.payload, str) and response.payload.startswith("web_key:"):
                    key_name = response.payload[8:]
                    if self.web_queue:
                        self.web_queue.put(f"key:{key_name}")
                        self._l.info(f"Forwarded key '{key_name}' to web process")
                elif self.is_non_interrupting(response):
                    self._l.debug(f"Ignoring non-interrupting command on web channel: {response.payload}")
                else:
                    # an on-demand pick plays in mpv, so the menu page closes (music and all)
                    if self._parkable(web_config) and response.status != PlayerState.PLAY_FILE:
                        # leave it running - the main loop closes it unless the next stop is
                        # the guide, the menu, or this channel again (release_parked_web)
                        self._l.info(f"Keeping web channel {web_config['network_name']} running in the background")
                        self._parked_web = (web_config["network_name"], self.web_process, self.web_queue)
                    else:
                        self._l.info("Sending the web channel shutdown command")
                        self.web_queue.put("hide_window")
                        self.web_process.join()
                        if not keep_playing:
                            # mpv sat idle under the page, so it has to win focus back
                            # (a preview or the menu leaves it playing and focused)
                            self._refocus_mpv()
                    self.web_process = None
                    self.web_queue = None
                    self._end_guide_preview()
                    return response
        return PlayerOutcome(PlayerState.SUCCESS)

    def _guide_url(self, web_config):
        # tell a guide which channel it was opened from, so that's the one selected
        url = web_config.get("web_url")
        if url and web_config.get("guide_preview") and self.last_channel is not None:
            url += ("&" if "?" in url else "?") + f"current={self.last_channel}"
        return url

    @staticmethod
    def _parkable(web_config):
        # an ordinary web channel - not the guide or menu, and not a timed bump
        return not (web_config.get("guide_preview") or web_config.get("keep_playing") or web_config.get("duration"))

    def release_parked_web(self, keep_for=None):
        """Close the web channel left running in the background - unless keep_for, the
        channel being tuned to, is that channel again, or the guide or menu over it."""
        if self._parked_web is None:
            return
        name, process, queue = self._parked_web
        if keep_for is not None and (
            keep_for["network_name"] == name or keep_for.get("guide_preview") or keep_for.get("keep_playing")
        ):
            return
        self._parked_web = None
        self._l.info(f"Closing background web channel {name}")
        try:
            queue.put("hide_window")
            process.join(timeout=3)
            if process.is_alive():
                process.terminate()
                process.join(timeout=1)
        except Exception as e:
            self._l.error(f"Error closing background web channel: {e}")
        if keep_for is not None:
            self._refocus_mpv()

    def _take_focus(self):
        """On a tune, give the TV focus back if something on the desktop took it - a
        fullscreen window without focus has the taskbar stacked over it."""
        try:
            if not self.mpv.command("get_property", "focused"):
                activate_window(self.mpv.command("get_property", "window-id"))
        except Exception as e:
            self._l.debug(f"Could not give mpv focus: {e}")

    def _refocus_mpv(self):
        # with the web window gone, nothing has focus and the taskbar stacks over mpv -
        # going out of fullscreen and back makes the window manager focus it again
        try:
            self.mpv.command("set_property", "fullscreen", False)
            time.sleep(0.3)
            self.mpv.command("set_property", "fullscreen", True)
        except Exception as e:
            self._l.warning(f"Could not refocus mpv: {e}")

    def schedule_panic(self, network_name):
        self._l.critical("*********************Schedule Panic*********************")
        self._l.critical(f"Schedule not found for {network_name} - attempting to generate a one-day extention")
        if self.schedule_lock:
            self.schedule_lock.acquire()
        try:
            schedule = LiquidSchedule(StationManager().station_by_name(network_name))
            schedule.add_days(1)
            self._l.warning(f"Schedule extended for {network_name} - reloading schedules now")
            LiquidManager().reload_schedules()
        except Exception as e:
            self._l.error(f"Schedule panic failed for {network_name}: {e}")
        finally:
            if self.schedule_lock:
                self.schedule_lock.release()

    @staticmethod
    def plays_youtube(conf):
        """Whether a channel is a YouTube playlist channel that mpv plays (rather than
        the browser page, kept for "youtube_player": "web")."""
        return bool(conf and conf.get("youtube_playlists")) and conf.get("youtube_player", "mpv") == "mpv"

    def _youtube_entry(self, network_name, finished=None):
        """What's on a YouTube channel now - or when that video wouldn't play (or has
        already played to its end), the next one in the lineup instead."""
        entry = youtube_channel.now_playing(network_name)
        for _ in range(5):
            if entry is None or (entry["id"] not in self._youtube_broken and entry["id"] != finished):
                break
            entry = youtube_channel.now_playing(network_name, after=time.time() + entry["remaining"])
        return entry

    @staticmethod
    def _youtube_block(entry):
        """A stand-in schedule block for the channel banner: the game and its slot."""
        now = datetime.datetime.now()
        game = entry.get("game")
        return SimpleNamespace(
            title=game["matchup"] if game else entry["title"],
            start_time=now - datetime.timedelta(seconds=entry["offset"]),
            end_time=now + datetime.timedelta(seconds=entry["remaining"]),
        )

    def _load_youtube(self, entry, watch_input=True):
        """Start a YouTube video at the point the lineup is up to. Returns True once
        it's playing, False if it never started, or a PlayerOutcome if a channel
        change came in while waiting (watch_input off leaves the remote's presses to
        whoever else is reading them - the guide, under a preview)."""
        url = f"https://www.youtube.com/watch?v={entry['id']}"
        self._l.info(f"Loading YouTube video {entry['id']} at {entry['offset']:.0f}s: {entry['title']}")
        self._prepare_tracks()
        self.mpv.command("playlist-clear")
        # yt-dlp takes a few seconds to find the streams; starting at the right point
        # saves a seek afterwards
        self.mpv.command("loadfile", url, "replace", -1, f"start={entry['offset']:.1f}")
        self.current_playing_file_path = url
        started = time.time()
        while time.time() - started < YOUTUBE_START_TIMEOUT:
            try:
                if self.mpv.time_pos is not None:
                    self._choose_tracks()
                    return True
            except Exception:
                pass
            response = self.input_check_fn() if watch_input else None
            if response:
                if self.handle_runtime_command_outcome(response) or self.is_non_interrupting(response):
                    continue
                return response
            time.sleep(0.05)
        self._l.warning(f"YouTube video {entry['id']} did not start - skipping it")
        self._youtube_broken.add(entry["id"])
        return False

    def play_youtube(self, network_name):
        """Play a YouTube playlist channel (fs42/youtube_channel.py) through mpv: the
        lineup says what's on and how far in, mpv plays it, and on to the next when
        its slot ends - until a channel change."""
        if self._parental_controls_required(network_name):
            if self.parental_unlocked_network != network_name:
                return PlayerOutcome(PlayerState.PARENTAL_CONTROLS, network_name)
        self._preview_network = network_name
        self._close_now_playing()
        conf = self.station_config
        if self.banner_pending:
            # a new tune
            self._take_focus()
            self.banner_pending = False
            self._banner_request = user_settings.load_settings()["channel_banner"] == "on"

        finished = None
        while True:
            try:
                entry = self._youtube_entry(network_name, finished)
            except Exception as e:
                self._l.error(f"No lineup for {network_name}: {e}")
                entry = None
            if entry is None:
                return PlayerOutcome(PlayerState.FAILED)
            game = entry.get("game")
            url = f"https://www.youtube.com/watch?v={entry['id']}"
            update_status_socket(
                "playing", network_name, conf["channel_number"],
                game["matchup"] if game else entry["title"],
                file_path=url, content_type="feature",
            )

            if self.current_playing_file_path == url and self.mpv.time_pos is not None:
                # still playing from before the guide or the menu - carry on
                outcome = True
            else:
                self.mpv.panscan = self._panscan()
                self.mpv.keepaspect = True
                self.mpv.vf = ""
                outcome = self._load_youtube(entry)
                if outcome is True:
                    self.caption.show(game)
            if isinstance(outcome, PlayerOutcome):
                self.caption.hide()
                return outcome
            if outcome is False:
                continue  # marked broken - the next one in the lineup stands in

            self.bug.show(conf)
            if self._banner_request:
                self._banner_request = None
                self.banner.show(conf, self._youtube_block(entry))

            # play out the slot, or until mpv runs out of video first - then that one is
            # done, and the next in the lineup comes on early rather than replaying it
            slot_end = time.time() + entry["remaining"]
            finished = None
            while time.time() < slot_end:
                time.sleep(0.05)
                # a tune starts with static and a rolling picture that settles - like
                # every other channel, this is where it settles
                if not self.skip_reception_check:
                    self.update_reception()
                try:
                    if self.mpv.command("get_property", "idle-active"):
                        finished = entry["id"]
                        break
                except Exception:
                    pass
                response = self.input_check_fn()
                if response:
                    if self.handle_runtime_command_outcome(response):
                        continue
                    if self.is_non_interrupting(response):
                        continue
                    self.caption.hide()
                    return response
            self.caption.hide()

    def play_slot(self, network_name, when):
        liquid = LiquidManager()

        if self._parental_controls_required(network_name):
            if self.parental_unlocked_network != network_name:
                return PlayerOutcome(PlayerState.PARENTAL_CONTROLS, network_name)

        self._preview_network = network_name
        try:
            play_point = liquid.get_play_point(network_name, when)
            self._current_playing = play_point
        except (ScheduleNotFound, ScheduleQueryNotInBounds):
            self.schedule_panic(network_name)
            self._l.warning(f"Schedules reloaded - retrying play for: {network_name}")
            # fail so we can return and try again
            return PlayerOutcome(PlayerState.FAILED)
        
        if play_point is None:
            self.current_playing_file_path = None
            self.current_playing_block_title = None
            return PlayerOutcome(PlayerState.FAILED)

        if self.banner_pending:
            # a new tune
            self._take_focus()
            self.banner_pending = False
            if user_settings.load_settings()["channel_banner"] == "on":
                try:
                    block = liquid.get_programming_block(network_name, when)
                except Exception:
                    block = None  # streams have no schedule block - show the channel alone
                self._banner_request = (self.station_config, block)

        return self._play_from_point(play_point)

    def _play_from_point(self, play_point: PlayPoint):
        # Fade to black duration before commercial breaks (in seconds)
        FADE_DURATION = 0.5
        fade_active = False

        # Close any existing now playing overlay when starting a new play point
        # This handles channel changes and ensures clean state
        self._close_now_playing()

        if len(play_point.plan):
            initial_skip = play_point.offset

            # iterate over the slice from index to end
            for entry in play_point.plan[play_point.index :]:
                self._l.info(f"Starting entry at {datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]}")
                self._l.info(f"Playing entry {entry}")
                self._l.info(f"Initial Skip: {initial_skip}")
                total_skip = entry.skip + initial_skip

                is_stream = False

                if hasattr(entry, "is_stream"):
                    is_stream = entry.is_stream

                title = play_point.block_title
                content_type = getattr(entry, 'content_type', 'feature')  # Get content_type from entry, default to 'feature'
                media_type = getattr(entry, 'media_type', 'video')  # Get media_type from entry, default to 'video'
                worked = self.play_file(entry.path, file_duration=entry.duration, offset_seconds=total_skip, is_stream=is_stream, title=title, content_type=content_type, media_type=media_type)
                # the logo bug is up for the show itself, not bumps and breaks
                if worked and content_type == "feature":
                    self.bug.show(self.station_config)
                else:
                    self.bug.hide()
                if self._banner_request:
                    # wait until the picture is up so the banner isn't spent on a black screen
                    banner_conf, banner_block = self._banner_request
                    self._banner_request = None
                    self.banner.show(banner_conf, banner_block)
                if self._pending_response:
                    response = self._pending_response
                    self._pending_response = None
                    return response
                stream_is_down = False
                last_osd_refresh = 0.0
                if not worked:
                    if is_stream:
                        self._l.warning(f"Stream unavailable, activating fallback: {entry.path}")
                        stream_is_down = True
                        last_osd_refresh = time.time()
                        self._show_stream_down()
                    else:
                        return PlayerOutcome(PlayerState.FAILED)
                # Seek now happens inside play_file() before overlay is shown

                # Detect if this video is being clipped (stopping before natural end)
                is_clipped = False
                try:
                    actual_file_duration = self.mpv.duration
                    stop_position = total_skip + (entry.duration - initial_skip)
                    # If stopping before end (with tolerance), we're clipping
                    is_clipped = stop_position < (actual_file_duration - 0.5)
                    self._l.info(f"File duration: {actual_file_duration:.2f}s, stop at: {stop_position:.2f}s, clipped: {is_clipped}")
                except Exception as e:
                    self._l.info(f"Could not determine if clipped: {e}")
                    is_clipped = False

                if entry.duration:
                    self._l.info(f"Monitoring for: {entry.duration - initial_skip}")

                    # Calculate target end time using wall clock
                    target_end_time = datetime.datetime.now() + datetime.timedelta(seconds=(entry.duration - initial_skip))
                    self._l.info(f"Target end time: {target_end_time.strftime('%H:%M:%S.%f')[:-3]}")
                    stream_down_message = (self.station_config.get("stream_down_message", "TECHNICAL DIFFICULTIES") if self.station_config else "TECHNICAL DIFFICULTIES")

                    # this is our main event loop
                    keep_waiting = True
                    while keep_waiting:
                        if not self.skip_reception_check:
                            self.update_reception()
                        else:
                            if self.scrambler:
                                try:
                                    self.mpv.vf = self.scrambler.update_filter()
                                except TimeoutError:
                                    self._l.warning("mpv did not respond to scrambler filter update")

                        # Calculate time remaining based on wall clock
                        time_remaining = (target_end_time - datetime.datetime.now()).total_seconds()

                        # Initiate fade-to-black effect when entering fade window (only if clipped)
                        if 0 < time_remaining <= FADE_DURATION and not fade_active and is_clipped:
                            self._l.info(f"Starting fade with {time_remaining:.2f}s remaining")

                            # Use MPV's built-in fade filter with duration
                            # Fade video to black (only if not using scramble effects)
                            if not self.skip_reception_check:
                                try:
                                    # Use fade filter: fade out to black over remaining time
                                    self.mpv.vf = f"fade=t=out:st=0:d={time_remaining}"
                                except Exception as e:
                                    self._l.debug(f"Could not set video fade filter: {e}")

                            fade_active = True

                        # Detect stream drop mid-playback and show fallback
                        if is_stream and not stream_is_down:
                            try:
                                if self.mpv.time_pos is None:
                                    self._l.warning(f"Stream dropped mid-playback: {entry.path}")
                                    stream_is_down = True
                                    last_osd_refresh = 0.0
                                    self._show_stream_down()
                            except Exception:
                                pass
                        elif is_stream and stream_is_down:
                            _now = time.time()
                            if _now - last_osd_refresh >= 8.0:
                                try:
                                    self.mpv.command("show-text", stream_down_message, 10000)
                                except Exception:
                                    pass
                                last_osd_refresh = _now

                        if time_remaining <= 0:
                            if self.web_process:
                                try:
                                    self.web_queue.put("hide_window")
                                    self.web_process.join(timeout=3)
                                    if self.web_process.is_alive():
                                        self._l.warning("Web process did not terminate gracefully, forcing termination")
                                        self.web_process.terminate()
                                        self.web_process.join(timeout=1)
                                except Exception as e:
                                    self._l.error(f"Error shutting down web process: {e}")
                                finally:
                                    self.web_process = None
                                    self.web_queue = None
                            keep_waiting = False
                        else:
                            # debounce time
                            time.sleep(0.05)
                            response = self.input_check_fn()
                            if response:
                                if self.handle_runtime_command_outcome(response):
                                    continue
                                if self.is_non_interrupting(response):
                                    self._l.debug(f"Ignoring non-interrupting command during slot: {response.payload}")
                                    continue
                                if response.status == PlayerState.CHANNEL_CHANGE:
                                    if stream_is_down:
                                        try:
                                            self.mpv.command("show-text", "", 1)
                                        except Exception:
                                            pass
                                    if self.web_process:
                                        try:
                                            self.web_queue.put("hide_window")
                                            self.web_process.join(timeout=2)
                                            if self.web_process.is_alive():
                                                self._l.warning("Web process did not terminate gracefully on channel change, forcing termination")
                                                self.web_process.terminate()
                                                self.web_process.join(timeout=1)
                                        except Exception as e:
                                            self._l.error(f"Error shutting down web process on channel change: {e}")
                                        finally:
                                            self.web_process = None
                                            self.web_queue = None
                                return response
                else:
                    return PlayerOutcome(PlayerState.FAILED)

                # Log timing for debugging inter-entry delays
                self._l.info(f"Segment ended at {datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]}")

                # Reset fade state for next segment
                fade_active = False

                initial_skip = 0

            self._l.info("Done playing block")
            return PlayerOutcome(PlayerState.SUCCESS)
        else:
            self.current_playing_file_path = None
            return PlayerOutcome(PlayerState.FAILED, "Failure getting index...")

    def get_current_path(self):
        if self.current_playing_file_path:
            basename = os.path.basename(self.current_playing_file_path)
            title, _ = os.path.splitext(basename)
            return title
        return None
