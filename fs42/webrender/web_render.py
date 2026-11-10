import json
import sys
import signal
from PySide6.QtCore import QUrl, QTimer, Qt
from PySide6.QtWidgets import QApplication, QMainWindow
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEngineSettings, QWebEnginePage, QWebEngineUrlRequestInterceptor
from PySide6.QtQuick import QQuickWindow, QSGRendererInterface
from fs42.x11_focus import activate_window

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


class ApiKeyInterceptor(QWebEngineUrlRequestInterceptor):
    # only our own server gets the key - web channels can point at any third party site
    def __init__(self, api_key, server_port):
        super().__init__()
        self.api_key = api_key.encode()
        self.server_port = server_port

    def interceptRequest(self, info):
        url = info.requestUrl()
        if url.host() in LOCAL_HOSTS and url.port() == self.server_port:
            info.setHttpHeader(b"X-API-Key", self.api_key)


class WebRender(QMainWindow):
    def __init__(self):
        super().__init__()
        self.browser = QWebEngineView()

        # Configure QWebEngineSettings to enable autoplay
        settings = self.browser.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.AutoLoadImages, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.AllowRunningInsecureContent, True)

        # Set custom user agent for identification
        self.browser.page().profile().setHttpUserAgent("FieldStation42-WebRender/1.0")

        from fs42.station_manager import StationManager
        api_key = StationManager().api_key()
        self.interceptor = None
        if api_key:
            port = int(StationManager().server_conf.get("server_port", 4242))
            self.interceptor = ApiKeyInterceptor(api_key, port)
            self.browser.page().profile().setUrlRequestInterceptor(self.interceptor)

        # Set black background color
        self.browser.page().setBackgroundColor(Qt.black)

        self.setCentralWidget(self.browser)

        # Hide cursor
        self.setCursor(Qt.BlankCursor)

        # Retry logic for handling web server startup races
        self.current_url = None
        self.retry_count = 0
        self.max_retries = 3
        self.retry_delay = 2000  # 2 seconds in milliseconds

        # a channel banner asked for before the page has loaded waits for it
        self.loaded = False
        self.pending_banner = None

        # Chromium's page process can die on its own (after many hours open, say),
        # which leaves the window up but blank - load the page again when it does
        self.browser.page().renderProcessTerminated.connect(self._on_render_process_terminated)

    def _on_render_process_terminated(self, status, exit_code):
        if status == QWebEnginePage.RenderProcessTerminationStatus.NormalTerminationStatus:
            return
        print(f"WebRender page process ended ({status}, exit code {exit_code}) - reloading {self.current_url}")
        if self.current_url:
            QTimer.singleShot(1000, lambda: self.browser.setUrl(QUrl(self.current_url)))

    def navigate(self, URL: str):
        # Initialize retry tracking for new URL
        self.current_url = URL
        self.retry_count = 0
        print(f"WebRender navigating to: {URL}")

        self.browser.setUrl(QUrl(URL))
        # Connect to loadFinished to simulate user interaction after page loads
        self.browser.loadFinished.connect(self._on_load_finished)

    def _retry_load(self):
        """Retry loading the current URL"""
        print(f"WebRender retrying URL: {self.current_url} (attempt {self.retry_count + 1}/{self.max_retries})")
        self.browser.setUrl(QUrl(self.current_url))

    def _on_load_finished(self, success):
        if success:
            print(f"WebRender successfully loaded: {self.current_url}")
            self.loaded = True
            # a full-screen page has to hold focus, or the window manager stacks the
            # taskbar over it (the player does the same for mpv on each tune)
            if self.isFullScreen():
                QTimer.singleShot(300, lambda: activate_window(int(self.winId())))
            if self.pending_banner:
                info, self.pending_banner = self.pending_banner, None
                QTimer.singleShot(500, lambda: self.show_banner(info))
            # Reset retry count on success
            self.retry_count = 0

            # Inject JavaScript to simulate user interaction and enable autoplay
            js_code = """
            // Simulate user interaction to enable autoplay
            document.body.click();

            // Try to enable wake lock and autoplay for media elements
            if ('wakeLock' in navigator) {
                navigator.wakeLock.request('screen').catch(e => console.log('Wake lock failed:', e));
            }

            // Find and try to play any media elements
            const mediaElements = document.querySelectorAll('video, audio');
            mediaElements.forEach(element => {
                if (element.paused) {
                    element.play().catch(e => console.log('Autoplay failed:', e));
                }
            });
            """
            self.browser.page().runJavaScript(js_code)
        else:
            # Load failed - hide any error content and show black screen
            hide_error_code = """
            document.body.style.backgroundColor = 'black';
            document.body.innerHTML = '';
            """
            self.browser.page().runJavaScript(hide_error_code)

            # Check if we should retry
            if self.retry_count < self.max_retries:
                self.retry_count += 1
                print(f"WebRender load failed for: {self.current_url}, will retry in {self.retry_delay/1000}s...")
                # Schedule retry after delay
                QTimer.singleShot(self.retry_delay, self._retry_load)
            else:
                print(f"WebRender load failed for: {self.current_url} after {self.max_retries} retries, giving up.")

    def show_entry(self, info):
        """Draw the channel number being typed over the page."""
        if self.loaded:
            self.browser.page().runJavaScript(TOP_LAYER_JS + ENTRY_JS.replace("__INFO__", json.dumps(info)))

    def show_notice(self, info):
        """Draw a notice (ACTION NOT VALID) over the page."""
        if self.loaded:
            self.browser.page().runJavaScript(TOP_LAYER_JS + NOTICE_JS.replace("__INFO__", json.dumps(info)))

    def show_volume(self, info):
        """Draw the volume read-out over the page (mpv's own is hidden under it)."""
        if self.loaded:
            self.browser.page().runJavaScript(TOP_LAYER_JS + VOLUME_JS.replace("__INFO__", json.dumps(info)))

    def show_banner(self, info):
        """Draw the channel banner over the page - or take it down if it's up. The
        player's own banner is drawn by mpv, which is hidden under a web channel."""
        if not self.loaded:
            self.pending_banner = info
            return
        self.browser.page().runJavaScript(TOP_LAYER_JS + BANNER_JS.replace("__INFO__", json.dumps(info)))


# Every overlay goes in the browser's top layer (a manual popover). A page can put one
# of its own elements in full-screen mode - the weather kiosk does - and then only that
# element shows, scaled however the page likes; the top layer sits above it, at the
# screen's own size, whatever the page does underneath.
TOP_LAYER_JS = r"""
window.__fs42Show = window.__fs42Show || (el => {
  if (!el.hasAttribute('popover')) el.setAttribute('popover', 'manual');
  if (!el.isConnected) document.documentElement.appendChild(el);
  el.style.display = el.dataset.display || 'flex';
  try {
    // shown again so it's the newest thing in the top layer, above a full-screen page
    if (el.matches(':popover-open')) el.hidePopover();
    el.showPopover();
  } catch (e) {}
});
window.__fs42Hide = window.__fs42Hide || (el => {
  try { if (el.matches(':popover-open')) el.hidePopover(); } catch (e) {}
  el.style.display = 'none';
});
"""
# a popover comes with the browser's own margin, border, padding and background
TOP_RESET = "inset:auto;margin:0;border:0;padding:0;overflow:visible;background:transparent;"


# The volume read-out for a web channel - the same as the mpv one
# (fs42/volume_osd.py): "VOLUME", 50 green bars and the number in VT323, low on the
# screen, sized in vh like its 1080-high canvas, gone 3 seconds after the last press.
VOLUME_JS = r"""
(() => {
  const info = __INFO__;
  const SEGMENTS = 50;
  let box = document.getElementById('fs42-volume');
  if (!box) {
    box = document.createElement('div');
    box.id = 'fs42-volume';
    box.style.cssText = 'position:fixed;__TOP_RESET__left:0;width:100vw;top:calc(100vh * 890 / 1080);z-index:2147483647;' +
      'display:flex;align-items:center;justify-content:center;gap:calc(100vh * 28 / 1080);pointer-events:none;' +
      "font-family:'VT323',monospace;font-size:calc(100vh * 68 / 1080);line-height:1;color:#40ff40;" +
      'text-shadow:0 0 3px #000,0 0 3px #000,0 0 3px #000';
    box.innerHTML = '<span>VOLUME</span><span class="bars" style="display:flex;gap:calc(100vh * 4 / 1080)"></span>' +
      '<span class="num" style="min-width:3ch"></span>';
    const bars = box.querySelector('.bars');
    for (let i = 0; i < SEGMENTS; i++) {
      const seg = document.createElement('i');
      seg.style.cssText = 'display:block;width:calc(100vh * 9 / 1080);height:calc(100vh * 46 / 1080);' +
        'outline:calc(100vh * 2 / 1080) solid #000';
      bars.appendChild(seg);
    }
  }
  const lit = info.muted ? 0 : Math.round(info.level / 100 * SEGMENTS);
  box.querySelectorAll('.bars i').forEach((seg, i) => { seg.style.background = i < lit ? '#40ff40' : '#123a12'; });
  box.querySelector('.num').textContent = info.muted ? 'MUTE' : String(info.level);
  const notice = document.getElementById('fs42-notice');
  if (notice) __fs42Hide(notice);
  __fs42Show(box);
  clearTimeout(window.__fs42VolumeTimer);
  window.__fs42VolumeTimer = setTimeout(() => __fs42Hide(box), 3000);
})();
"""


# The channel number being typed, for a web channel - the same as the mpv one
# (fs42/channel_entry_osd.py): green VT323 digits in a see-through black box, bottom
# left, with a blinking underscore waiting for the next digit.
ENTRY_JS = r"""
(() => {
  const info = __INFO__;
  const u = v => `calc(100vh * ${v} / 1080)`;
  let box = document.getElementById('fs42-entry');
  if (!box) {
    box = document.createElement('div');
    box.id = 'fs42-entry';
    box.style.cssText = `position:fixed;__TOP_RESET__left:${u(80)};bottom:${u(60)};height:${u(130)};` +
      `width:calc(${u(68)} + 3ch);padding:0 ${u(34)};box-sizing:content-box;z-index:2147483647;` +
      `display:flex;align-items:center;background:rgba(0,0,0,0.69);pointer-events:none;` +
      `font-family:'VT323',monospace;font-size:${u(94)};line-height:1;color:#40ff40;white-space:pre`;
    box.innerHTML = '<span class="d"></span><span class="c">_</span>';
    const style = document.createElement('style');
    style.textContent = '@keyframes fs42blink{0%,49%{opacity:1}50%,100%{opacity:0}}' +
      '#fs42-entry .c{animation:fs42blink 1s steps(1) infinite}';
    box.appendChild(style);
  }
  const digits = String(info.digits || '');
  clearTimeout(window.__fs42EntryTimer);
  if (!digits) { __fs42Hide(box); return; }
  box.querySelector('.d').textContent = digits;
  box.querySelector('.c').style.display = digits.length < 3 ? 'inline' : 'none';
  box.style.width = '3ch';
  __fs42Show(box);
  window.__fs42EntryTimer = setTimeout(() => __fs42Hide(box), 4000);
})();
"""


# A notice for a web channel - the same as the mpv one (fs42/notice_osd.py): a red X
# and the words in VT323 on a dark box, centred just above the bottom, gone in 2.5s.
NOTICE_JS = r"""
(() => {
  const info = __INFO__;
  const u = v => `calc(100vh * ${v} / 1080)`;
  let box = document.getElementById('fs42-notice');
  if (!box) {
    box = document.createElement('div');
    box.id = 'fs42-notice';
    box.style.cssText = `position:fixed;__TOP_RESET__left:50%;transform:translateX(-50%);bottom:${u(150)};height:${u(104)};` +
      `z-index:2147483647;display:flex;align-items:center;gap:${u(26)};padding:0 ${u(36)};box-sizing:border-box;` +
      `background:rgba(10,10,20,0.88);outline:${u(3)} solid #000;pointer-events:none;white-space:nowrap;` +
      `font-family:'VT323',monospace;font-size:${u(63)};line-height:1;color:#fff`;
    box.innerHTML = `<svg viewBox="0 0 56 56" style="width:${u(56)};height:${u(56)};flex:none">` +
      '<path d="M11 0 L28 17 L45 0 L56 11 L39 28 L56 45 L45 56 L28 39 L11 56 L0 45 L17 28 L0 11 Z" ' +
      'fill="#f02020" stroke="#000" stroke-width="2"/></svg><span></span>';
  }
  box.querySelector('span').textContent = info.text;
  const vol = document.getElementById('fs42-volume');
  if (vol) __fs42Hide(vol);  // they share the bottom of the screen - the newest wins
  __fs42Show(box);
  clearTimeout(window.__fs42NoticeTimer);
  window.__fs42NoticeTimer = setTimeout(() => __fs42Hide(box), 2500);
})();
"""


# The channel banner for a web channel, laid over whatever page it shows - the same
# layout and colours as the mpv banner (fs42/channel_banner.py), sized in vh like its
# 1080-high canvas. INFO again takes it down; it goes by itself after 6 seconds.
BANNER_JS = """
(() => {
  const info = __INFO__;
  const old = document.getElementById('fs42-banner');
  if (old) {
    clearTimeout(window.__fs42BannerTimer);
    old.remove();
    return;
  }
  const navy = '#0a1e50', orange = '#ffaa00', muted = '#b9c8ea';
  const outline = `0 0 0.3vh ${navy}, 0 0 0.3vh ${navy}, 0 0 0.3vh ${navy}`;
  const el = (tag, css, text) => {
    const e = document.createElement(tag);
    e.style.cssText = css;
    if (text !== undefined) e.textContent = text;
    return e;
  };
  const band = el('div', `position:fixed;__TOP_RESET__left:0;top:0;width:100vw;height:19.9vh;z-index:2147483647;
    background:rgba(10,30,80,0.81);border-bottom:0.46vh solid ${orange};
    font-family:Arial,Helvetica,sans-serif;color:#fff;text-shadow:${outline};pointer-events:none;`);
  band.id = 'fs42-banner';
  if (info.logo) {
    const img = el('img', 'position:absolute;left:3.7vh;top:3vh;width:21.3vh;height:13.9vh;object-fit:contain;');
    img.src = info.logo;
    band.appendChild(img);
  }
  const number = el('div', 'position:absolute;left:27.8vh;top:1.8vh;font-size:8.9vh;font-weight:bold;line-height:1;', String(info.number));
  const name = el('div', `position:absolute;left:27.8vh;top:11.8vh;font-size:3.7vh;font-weight:bold;color:${muted};white-space:nowrap;`, info.name);
  band.append(number, name);
  const mid = el('div', 'position:absolute;left:50%;top:2.2vh;transform:translateX(-50%);text-align:center;white-space:nowrap;');
  // the title gets the room between the channel name and the right edge, centred like
  // the rest - a longer one scrolls inside it, the same as the mpv banner
  const titleBox = el('div', `font-size:5.9vh;font-weight:bold;color:${orange};line-height:1.1;overflow:hidden;margin:0 auto;`);
  const titleText = el('span', 'display:inline-block;', info.title);
  titleBox.appendChild(titleText);
  mid.appendChild(titleBox);
  if (info.subtitle) mid.appendChild(el('div', `font-size:3.2vh;color:${muted};margin-top:0.5vh;`, info.subtitle));
  mid.appendChild(el('div', 'font-size:3.7vh;margin-top:0.6vh;white-space:pre;', info.slot ? `${info.when}   \u2022   ${info.slot}` : info.when));
  band.appendChild(mid);
  band.dataset.display = 'block';
  __fs42Show(band);
  const gap = innerHeight * 40 / 1080;
  const left = Math.max(number.getBoundingClientRect().right, name.getBoundingClientRect().right) + gap;
  const half = Math.max(innerHeight * 0.1, Math.min(innerWidth / 2 - left, innerWidth / 2 - gap));
  titleBox.style.maxWidth = `${2 * half}px`;
  let over = titleText.scrollWidth - titleBox.clientWidth;
  if (over > 2) {
    // too long to stay centred: take all the room from the channel name to the right edge
    mid.style.left = `${left}px`;
    mid.style.transform = 'none';
    mid.style.textAlign = 'left';
    titleBox.style.maxWidth = `${innerWidth - gap - left}px`;
    titleBox.style.margin = '0';
    over = titleText.scrollWidth - titleBox.clientWidth;
  }
  if (over > 2) {
    titleBox.style.textAlign = 'left';
    const speed = innerHeight * 90 / 1080, hold = 1200, travel = over / speed * 1000, total = travel + 2 * hold;
    titleText.animate([
      { transform: 'translateX(0)', offset: 0 },
      { transform: 'translateX(0)', offset: hold / total },
      { transform: `translateX(${-over}px)`, offset: (hold + travel) / total },
      { transform: `translateX(${-over}px)`, offset: 1 },
    ], { duration: total, iterations: Infinity });
  }
  window.__fs42BannerTimer = setTimeout(() => band.remove(), 6000);
})();
"""


VOLUME_JS, NOTICE_JS, BANNER_JS, ENTRY_JS = (js.replace("__TOP_RESET__", TOP_RESET)
                                              for js in (VOLUME_JS, NOTICE_JS, BANNER_JS, ENTRY_JS))


class WebRenderApp(QApplication):
    def __init__(self, user_conf, queue=None):
        super().__init__([])

        self.queue = queue

        self.window = WebRender()

        # fit_screen sizes a frameless window to whatever resolution the screen runs at
        if user_conf.get("fit_screen"):
            screen = self.primaryScreen().geometry()
            user_conf = {**user_conf, "width": screen.width(), "height": screen.height(), "x": screen.x(), "y": screen.y()}

        # Set window properties
        if "width" in user_conf and "height" in user_conf:
            # Use specified dimensions
            width = user_conf["width"]
            height = user_conf["height"]

            # Always use frameless window (no decorations)
            flags = Qt.FramelessWindowHint
            if not user_conf.get("guide_preview"):
                # Keep the window manager out of it, so this always sits above mpv - even
                # when mpv has just gone back to fullscreen and taken focus (leaving the
                # guide's preview), which would otherwise stack its black window on top.
                # Keys reach the page through the player, not window focus, so nothing is lost.
                # A guide that is previewing stays managed: mpv's ontop window has to sit
                # above it. The player clears guide_preview when there's nothing to preview.
                flags |= Qt.X11BypassWindowManagerHint
            else:
                # and it never takes focus: the window manager lifts a focused, screen-sized
                # window above even an ontop one, which buries the preview (a black panel).
                # Keys reach the page through the player, so it doesn't need focus.
                flags |= Qt.WindowDoesNotAcceptFocus
                self.window.setAttribute(Qt.WA_ShowWithoutActivating)
            self.window.setWindowFlags(flags)
            self.window.resize(width, height)

            # Calculate position
            if "x" in user_conf and "y" in user_conf:
                # Use specified position
                x = user_conf["x"]
                y = user_conf["y"]
            else:
                # Center on screen
                screen = self.primaryScreen().availableGeometry()
                x = screen.center().x() - width // 2
                y = screen.center().y() - height // 2

            # Show window and position it (delay needed for X11 window managers)
            self.window.show()

            # where "fullscreen" puts the window back to after a "geometry" move
            self.home_geometry = (x, y, width, height)

            # Store position for delayed move
            def delayed_move():
                if self.window and not self.window.isHidden():
                    self.window.move(x, y)

            QTimer.singleShot(100, delayed_move)
        else:
            # Go fullscreen by default (no decorations)
            self.window.showFullScreen()

        # raise once the window is up, in case anything was stacked over it while it opened -
        # except a guide with a preview, which must stay under it: the preview (mpv, or
        # a web channel) sits on top in the panel, and a late raise here covers it
        if not (user_conf.get("guide_preview") or user_conf.get("web_preview")):
            for delay in (400, 1500):
                QTimer.singleShot(delay, self.bring_to_front)

        # Set up timer for queue processing
        self.timer = QTimer()
        self.timer.timeout.connect(self.tick)
        self.timer.start(250)  # Check every 250ms

        # Set up page refresh timer if configured
        if user_conf.get("refresh_interval", 0) > 0:
            self.refresh_timer = QTimer()
            self.refresh_timer.timeout.connect(self.window.browser.reload)
            self.refresh_timer.start(int(user_conf["refresh_interval"] * 1000))

    def bring_to_front(self):
        if self.window and not self.window.isHidden():
            self.window.raise_()
            self.window.activateWindow()
            # only a full-screen page takes focus - a preview panel taking it would
            # leave the full-screen guide behind it under the taskbar
            if self.window.isFullScreen():
                activate_window(int(self.window.winId()))

    def place_window(self, x, y, width, height):
        # the player shrinks a web channel into the guide's preview panel and back
        if self.window.isFullScreen():
            self.window.showNormal()
        self.window.setGeometry(x, y, width, height)
        # raise now and again once the guide window has finished stacking itself
        for delay in (0, 300, 1000, 2000):
            QTimer.singleShot(delay, self.bring_to_front)

    def tick(self):
        if self.queue and self.queue.qsize() > 0:
            msg = self.queue.get_nowait()
            if msg == "raise":
                # sent every couple of seconds while this is the channel on screen - not logged
                self.bring_to_front()
                return
            # a banner message carries a whole logo - only the start of a message is worth logging
            print(f"WebRender received message: {str(msg)[:120]}")
            # Handle queue messages similar to GuideApp
            if hasattr(msg, 'hide_window') or msg == "hide_window":
                print("WebRender window is shutting down now.")
                print("Stopping timer...")
                self.timer.stop()
                if hasattr(self, 'refresh_timer'):
                    self.refresh_timer.stop()
                print("Closing window...")
                self.window.close()
                print("Quitting application...")
                self.quit()
                print("WebRender shutdown complete")
                return
            if isinstance(msg, str) and msg.startswith("entry:"):
                try:
                    self.window.show_entry(json.loads(msg[len("entry:"):]))
                except ValueError:
                    print("WebRender: bad entry message")
                return
            if isinstance(msg, str) and msg.startswith("notice:"):
                try:
                    self.window.show_notice(json.loads(msg[len("notice:"):]))
                except ValueError:
                    print("WebRender: bad notice message")
                return
            if isinstance(msg, str) and msg.startswith("volume:"):
                try:
                    self.window.show_volume(json.loads(msg[len("volume:"):]))
                except ValueError:
                    print("WebRender: bad volume message")
                return
            if isinstance(msg, str) and msg.startswith("banner:"):
                try:
                    self.window.show_banner(json.loads(msg[len("banner:"):]))
                except ValueError:
                    print("WebRender: bad banner message")
                return
            if isinstance(msg, str) and msg.startswith("geometry:"):
                try:
                    x, y, w, h = (int(v) for v in msg[len("geometry:"):].split(","))
                except ValueError:
                    print(f"WebRender: bad geometry '{msg}'")
                    return
                self.place_window(x, y, w, h)
                return
            if msg == "fullscreen":
                home = getattr(self, "home_geometry", None)
                if home:
                    self.place_window(*home)
                else:
                    self.window.showFullScreen()
                    self.bring_to_front()
                return
            # Handle key injection commands
            if isinstance(msg, str) and msg.startswith("key:"):
                key_name = msg[4:]
                # upstream sends NavLeft/NavRight; this setup's pages listen for the arrow keys
                key_name = {"NavLeft": "ArrowLeft", "NavRight": "ArrowRight"}.get(key_name, key_name)
                if key_name not in {"PageUp", "PageDown", "Enter", "ArrowLeft", "ArrowRight", *"0123456789"}:
                    print(f"WebRender: rejected disallowed key '{key_name}'")
                    return
                js = f"""
                document.dispatchEvent(new KeyboardEvent('keydown', {{
                    key: '{key_name}',
                    code: '{key_name}',
                    bubbles: true,
                    cancelable: true
                }}));
                """
                self.window.browser.page().runJavaScript(js)
                return

def web_render_runner(user_conf, queue):
    # log as it happens, not all at once when the page closes
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
    # Set up signal handler for web process - just exit cleanly
    def web_sigint_handler(sig, frame):
        print("WebRender process received SIGINT, exiting...")
        import sys
        sys.exit(0)

    signal.signal(signal.SIGINT, web_sigint_handler)

    # Set environment variables to enable autoplay
    import os
    flags = '--autoplay-policy=no-user-gesture-required --disable-web-security --allow-running-insecure-content'
    if user_conf.get("gpu_rendering"):
        # full-screen video (a YouTube channel) is too much to composite in software -
        # let Chromium use the GPU, and decode on it where the driver allows
        flags += ' --ignore-gpu-blocklist --enable-gpu-rasterization --enable-features=VaapiVideoDecoder,VaapiIgnoreDriverChecks'
    else:
        flags += ' --disable-features=VizDisplayCompositor'
    os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = flags

    # Set graphics API before creating QApplication
    if not user_conf.get("gpu_rendering"):
        QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.Software)

    app = WebRenderApp(user_conf, queue)

    # Navigate to URL after a short delay to ensure Qt is fully initialized
    def delayed_navigate():
        from fs42.station_manager import StationManager
        url = user_conf.get("web_url") or f"{StationManager().local_server_url()}/static/diagnostics.html"
        if "url" in user_conf:
            app.window.navigate(user_conf["url"])
        else:
            app.window.navigate(url)

    QTimer.singleShot(100, delayed_navigate)

    app.exec()

if __name__ == "__main__":
    import sys
    import os
    sys.path.append(os.getcwd())
    from fs42.station_manager import StationManager

    # Simple test config - customize as needed
    test_conf = {
        "url": f"{StationManager().local_server_url()}/static/diagnostics.html",
        "width": 800,
        "height": 600,
        # Uncomment to test specific positioning:
        # "x": 100,
        # "y": 100,
    }

    # Or load a station config by name
    # Uncomment and modify to use a station config:
    # from fs42.station_manager import StationManager
    # test_conf = StationManager().station_by_name("diagnostic")

    web_render_runner(test_conf, None)
