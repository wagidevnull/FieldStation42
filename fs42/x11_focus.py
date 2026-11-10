import ctypes
import logging
import os

# Asks the window manager to focus a window, the way clicking it in the taskbar
# would. A fullscreen window only stays above the taskbar while it has focus, so
# the TV takes focus back on each tune - otherwise a click on the desktop (or an
# app opened on it) leaves the taskbar showing across the bottom of the picture.

_l = logging.getLogger("X11Focus")


class _ClientMessage(ctypes.Structure):
    _fields_ = [("type", ctypes.c_int), ("serial", ctypes.c_ulong), ("send_event", ctypes.c_int),
                ("display", ctypes.c_void_p), ("window", ctypes.c_ulong), ("message_type", ctypes.c_ulong),
                ("format", ctypes.c_int), ("data", ctypes.c_long * 5)]


class _Event(ctypes.Union):
    _fields_ = [("xclient", _ClientMessage), ("pad", ctypes.c_long * 24)]


def activate_window(window_id):
    """Ask the window manager to focus an X11 window. Returns whether the request went out."""
    try:
        x = ctypes.cdll.LoadLibrary("libX11.so.6")
        x.XOpenDisplay.restype = ctypes.c_void_p
        x.XInternAtom.restype = ctypes.c_ulong
        x.XDefaultRootWindow.restype = ctypes.c_ulong
        display = x.XOpenDisplay(os.environ.get("DISPLAY", ":0").encode())
        if not display:
            return False
        d = ctypes.c_void_p(display)
        ev = _Event()
        ev.xclient.type = 33  # ClientMessage
        ev.xclient.window = window_id
        ev.xclient.message_type = x.XInternAtom(d, b"_NET_ACTIVE_WINDOW", False)
        ev.xclient.format = 32
        ev.xclient.data[0] = 2  # from a pager/taskbar, which window managers always honour
        root = x.XDefaultRootWindow(d)
        # SubstructureRedirect | SubstructureNotify, as the spec asks
        x.XSendEvent(d, ctypes.c_ulong(root), False, ctypes.c_long((1 << 19) | (1 << 20)), ctypes.byref(ev))
        x.XFlush(d)
        x.XCloseDisplay(d)
        return True
    except Exception as e:
        _l.debug(f"Could not activate window {window_id}: {e}")
        return False
