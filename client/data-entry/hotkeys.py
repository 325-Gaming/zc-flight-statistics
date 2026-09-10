"""Register global hotkeys with native operating-system APIs."""

import ctypes
import ctypes.util
import re
import sys
import threading
from collections import deque


_MODIFIER_ALIASES = {
    "alt": "alt", "cmd": "command", "command": "command",
    "control": "ctrl", "ctrl": "ctrl", "option": "alt",
    "shift": "shift", "super": "command", "win": "command",
    "windows": "command",
}
_MODIFIER_ORDER = ("ctrl", "alt", "shift", "command")


def _parse_hotkey(hotkey):
    """Return a normalized ``(modifiers, key)`` tuple."""
    if not isinstance(hotkey, str) or not hotkey.strip():
        raise ValueError("快捷键不能为空")
    parts = [part.strip().lower() for part in hotkey.split("+")]
    if any(not part for part in parts):
        raise ValueError(f"快捷键格式无效: {hotkey}")
    modifiers = []
    keys = []
    for part in parts:
        modifier = _MODIFIER_ALIASES.get(part)
        if modifier is None:
            keys.append(part)
        elif modifier in modifiers:
            raise ValueError(f"快捷键包含重复修饰键: {hotkey}")
        else:
            modifiers.append(modifier)
    if len(keys) != 1:
        raise ValueError(f"快捷键必须包含一个普通按键: {hotkey}")
    return tuple(item for item in _MODIFIER_ORDER if item in modifiers), keys[0]


def _normalized_callbacks(callbacks):
    normalized = {}
    for hotkey, callback in callbacks.items():
        parsed = _parse_hotkey(hotkey)
        if parsed in normalized:
            raise ValueError(f"快捷键重复: {hotkey}")
        normalized[parsed] = callback
    return normalized


def register_hotkeys(
    callbacks,
    dispatch=lambda callback: callback(),
    schedule=None,
):
    """Register hotkeys and return an object whose ``stop`` method removes them."""
    normalized = _normalized_callbacks(callbacks)
    if sys.platform == "win32":
        return _register_windows_hotkeys(normalized, dispatch)
    if sys.platform == "darwin":
        return _register_macos_hotkeys(normalized, dispatch, schedule)
    if sys.platform.startswith("linux"):
        return _register_x11_hotkeys(normalized, dispatch)
    raise RuntimeError(f"当前系统不支持全局快捷键注册: {sys.platform}")


class _ThreadedHotkeyRegistration:
    def __init__(self, stop_event, thread):
        self.stop_event = stop_event
        self.thread = thread

    def stop(self):
        self.stop_event.set()
        if self.thread is not threading.current_thread():
            self.thread.join(timeout=2)


def _start_registration(register):
    ready = threading.Event()
    stop_event = threading.Event()
    state = {}

    def run():
        try:
            register(stop_event, ready)
        except Exception as error:
            state["error"] = error
            ready.set()

    thread = threading.Thread(target=run, name="global-hotkeys", daemon=True)
    thread.start()
    ready.wait(timeout=3)
    if not ready.is_set():
        stop_event.set()
        raise RuntimeError("全局快捷键注册超时")
    if "error" in state:
        stop_event.set()
        thread.join(timeout=2)
        raise state["error"]
    return _ThreadedHotkeyRegistration(stop_event, thread)


def _windows_virtual_key(key):
    named = {"backspace": 0x08, "tab": 0x09, "enter": 0x0D,
             "escape": 0x1B, "space": 0x20}
    if len(key) == 1 and key.isascii() and key.isalnum():
        return ord(key.upper())
    if re.fullmatch(r"f(?:[1-9]|1[0-9]|2[0-4])", key):
        return 0x70 + int(key[1:]) - 1
    if key in named:
        return named[key]
    raise ValueError(f"Windows 不支持此快捷键按键: {key}")


def _register_windows_hotkeys(callbacks, dispatch):
    import ctypes.wintypes

    user32 = ctypes.windll.user32
    modifier_values = {"alt": 1, "ctrl": 2, "shift": 4, "command": 8}

    def register(stop_event, ready):
        registered_ids = []
        callbacks_by_id = {}
        try:
            for hotkey_id, ((modifiers, key), callback) in enumerate(
                callbacks.items(), start=1
            ):
                modifier_mask = 0x4000
                for modifier in modifiers:
                    modifier_mask |= modifier_values[modifier]
                if not user32.RegisterHotKey(
                    None, hotkey_id, modifier_mask, _windows_virtual_key(key)
                ):
                    raise RuntimeError(f"快捷键已被占用或无法注册: {key}")
                registered_ids.append(hotkey_id)
                callbacks_by_id[hotkey_id] = callback
            ready.set()
            message = ctypes.wintypes.MSG()
            while not stop_event.is_set():
                while user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 1):
                    if message.message == 0x0312:
                        callback = callbacks_by_id.get(message.wParam)
                        if callback is not None:
                            dispatch(callback)
                stop_event.wait(0.05)
        finally:
            for hotkey_id in registered_ids:
                user32.UnregisterHotKey(None, hotkey_id)

    return _start_registration(register)


def _four_char_code(value):
    return int.from_bytes(value.encode("ascii"), "big")


def _mac_virtual_key(key):
    key_codes = {
        "0": 29, "1": 18, "2": 19, "3": 20, "4": 21,
        "5": 23, "6": 22, "7": 26, "8": 28, "9": 25,
        "a": 0, "b": 11, "c": 8, "d": 2, "e": 14, "f": 3,
        "g": 5, "h": 4, "i": 34, "j": 38, "k": 40, "l": 37,
        "m": 46, "n": 45, "o": 31, "p": 35, "q": 12, "r": 15,
        "s": 1, "t": 17, "u": 32, "v": 9, "w": 13, "x": 7,
        "y": 16, "z": 6, "enter": 36, "escape": 53, "space": 49,
        "tab": 48,
    }
    if re.fullmatch(r"f(?:[1-9]|1[0-9]|20)", key):
        function_codes = (122, 120, 99, 118, 96, 97, 98, 100, 101, 109,
                          103, 111, 105, 107, 113, 106, 64, 79, 80, 90)
        return function_codes[int(key[1:]) - 1]
    try:
        return key_codes[key]
    except KeyError as error:
        raise ValueError(f"macOS 不支持此快捷键按键: {key}") from error


def _register_macos_hotkeys(callbacks, dispatch, schedule):
    if schedule is None:
        raise ValueError("macOS 快捷键注册需要主线程调度器")
    # PyDLL keeps the GIL held when the Carbon handler queries the event. This
    # avoids re-entering Python's thread-state restoration from Tk's event loop.
    carbon = ctypes.PyDLL(
        "/System/Library/Frameworks/Carbon.framework/Carbon"
    )

    class EventTypeSpec(ctypes.Structure):
        _fields_ = [("event_class", ctypes.c_uint32),
                    ("event_kind", ctypes.c_uint32)]

    class EventHotKeyID(ctypes.Structure):
        _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]

    carbon.GetApplicationEventTarget.restype = ctypes.c_void_p
    carbon.RegisterEventHotKey.argtypes = (
        ctypes.c_uint32, ctypes.c_uint32, EventHotKeyID, ctypes.c_void_p,
        ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p),
    )
    carbon.GetEventParameter.argtypes = (
        ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
        ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p,
    )
    handler_type = ctypes.CFUNCTYPE(
        ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p
    )
    carbon.InstallEventHandler.argtypes = (
        ctypes.c_void_p, handler_type, ctypes.c_uint32,
        ctypes.POINTER(EventTypeSpec), ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    )
    carbon.RemoveEventHandler.argtypes = (ctypes.c_void_p,)
    carbon.UnregisterEventHotKey.argtypes = (ctypes.c_void_p,)
    modifier_values = {
        "command": 1 << 8, "shift": 1 << 9,
        "alt": 1 << 11, "ctrl": 1 << 12,
    }
    event_type = EventTypeSpec(_four_char_code("keyb"), 6)

    callbacks_by_id = {}
    pending_callbacks = deque()

    @handler_type
    def handle_hotkey(_next_handler, event, _user_data):
        hotkey_id = EventHotKeyID()
        status = carbon.GetEventParameter(
            event, _four_char_code("----"), _four_char_code("hkid"), None,
            ctypes.sizeof(hotkey_id), None, ctypes.byref(hotkey_id),
        )
        callback = callbacks_by_id.get(hotkey_id.id)
        if status == 0 and callback is not None:
            pending_callbacks.append(callback)
        return 0

    handler = ctypes.c_void_p()
    target = carbon.GetApplicationEventTarget()
    status = carbon.InstallEventHandler(
        target, handle_hotkey, 1, ctypes.byref(event_type), None,
        ctypes.byref(handler),
    )
    if status != 0:
        raise RuntimeError(f"无法安装系统快捷键处理器 (OSStatus {status})")

    registrations = []
    try:
        for hotkey_id, ((modifiers, key), callback) in enumerate(
            callbacks.items(), start=1
        ):
            reference = ctypes.c_void_p()
            status = carbon.RegisterEventHotKey(
                _mac_virtual_key(key),
                sum(modifier_values[item] for item in modifiers),
                EventHotKeyID(_four_char_code("ZCFS"), hotkey_id), target,
                0, ctypes.byref(reference),
            )
            if status != 0:
                raise RuntimeError(
                    f"快捷键已被占用或无法注册: {key} (OSStatus {status})"
                )
            registrations.append(reference)
            callbacks_by_id[hotkey_id] = callback
    except Exception:
        for reference in registrations:
            carbon.UnregisterEventHotKey(reference)
        carbon.RemoveEventHandler(handler)
        raise

    class MacHotkeyRegistration:
        stopped = False

        def pump(self):
            if self.stopped:
                return
            while pending_callbacks:
                dispatch(pending_callbacks.popleft())
            schedule(self.pump, 10)

        def stop(self):
            if self.stopped:
                return
            self.stopped = True
            for reference in registrations:
                carbon.UnregisterEventHotKey(reference)
            registrations.clear()
            carbon.RemoveEventHandler(handler)
            callbacks_by_id.clear()
            self._handler_callback = None

    registration = MacHotkeyRegistration()
    registration._handler_callback = handle_hotkey
    schedule(registration.pump, 10)
    return registration


def _register_x11_hotkeys(callbacks, dispatch):
    library_path = ctypes.util.find_library("X11")
    if library_path is None:
        raise RuntimeError("无法加载 X11，当前桌面环境不支持全局快捷键注册")
    x11 = ctypes.CDLL(library_path)
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XDefaultRootWindow.argtypes = (ctypes.c_void_p,)
    x11.XDefaultRootWindow.restype = ctypes.c_ulong
    x11.XStringToKeysym.argtypes = (ctypes.c_char_p,)
    x11.XStringToKeysym.restype = ctypes.c_ulong
    x11.XKeysymToKeycode.argtypes = (ctypes.c_void_p, ctypes.c_ulong)
    x11.XKeysymToKeycode.restype = ctypes.c_uint
    x11.XPending.argtypes = (ctypes.c_void_p,)
    x11.XNextEvent.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
    x11.XSync.argtypes = (ctypes.c_void_p, ctypes.c_int)
    x11.XCloseDisplay.argtypes = (ctypes.c_void_p,)
    display = x11.XOpenDisplay(None)
    if not display:
        raise RuntimeError("无法连接 X11；Wayland 环境需要通过桌面环境注册快捷键")
    root = x11.XDefaultRootWindow(display)
    modifier_values = {"shift": 1, "ctrl": 4, "alt": 8, "command": 64}

    class XKeyEvent(ctypes.Structure):
        _fields_ = [
            ("type", ctypes.c_int), ("serial", ctypes.c_ulong),
            ("send_event", ctypes.c_int), ("display", ctypes.c_void_p),
            ("window", ctypes.c_ulong), ("root", ctypes.c_ulong),
            ("subwindow", ctypes.c_ulong), ("time", ctypes.c_ulong),
            ("x", ctypes.c_int), ("y", ctypes.c_int),
            ("x_root", ctypes.c_int), ("y_root", ctypes.c_int),
            ("state", ctypes.c_uint), ("keycode", ctypes.c_uint),
            ("same_screen", ctypes.c_int),
        ]

    class XEvent(ctypes.Union):
        _fields_ = [("type", ctypes.c_int), ("xkey", XKeyEvent),
                    ("pad", ctypes.c_long * 24)]

    def register(stop_event, ready):
        grabs = []
        callbacks_by_key = {}
        try:
            for (modifiers, key), callback in callbacks.items():
                keysym = x11.XStringToKeysym(key.encode())
                keycode = x11.XKeysymToKeycode(display, keysym)
                if not keysym or not keycode:
                    raise ValueError(f"X11 不支持此快捷键按键: {key}")
                modifier_mask = sum(modifier_values[item] for item in modifiers)
                for ignored_mask in (0, 2, 16, 18):
                    mask = modifier_mask | ignored_mask
                    x11.XGrabKey(display, keycode, mask, root, True, 1, 1)
                    grabs.append((keycode, mask))
                callbacks_by_key[(keycode, modifier_mask)] = callback
            x11.XSync(display, False)
            ready.set()
            event = XEvent()
            while not stop_event.is_set():
                while x11.XPending(display):
                    x11.XNextEvent(display, ctypes.byref(event))
                    if event.type != 2:
                        continue
                    callback = callbacks_by_key.get(
                        (event.xkey.keycode, event.xkey.state & ~18)
                    )
                    if callback is not None:
                        dispatch(callback)
                stop_event.wait(0.05)
        finally:
            for keycode, mask in grabs:
                x11.XUngrabKey(display, keycode, mask, root)
            x11.XCloseDisplay(display)

    return _start_registration(register)
