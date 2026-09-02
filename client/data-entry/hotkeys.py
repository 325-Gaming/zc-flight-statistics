"""Cross-platform global hotkey registration.

The ``keyboard`` package crashes while importing its macOS backend on recent
macOS/PyObjC versions, so macOS uses Quartz directly.
"""

import sys
import threading


_MAC_KEY_CODES = {
    "0": 29,
    "1": 18,
    "2": 19,
    "3": 20,
    "4": 21,
    "5": 23,
    "6": 22,
    "7": 26,
    "8": 28,
    "9": 25,
}


def register_hotkeys(callbacks, dispatch=lambda callback: callback()):
    """Register global hotkeys and return an object that keeps them alive."""
    if sys.platform == "darwin":
        return _register_macos_hotkeys(callbacks, dispatch)

    import keyboard

    handles = []
    for hotkey, callback in callbacks.items():
        handles.append(
            keyboard.add_hotkey(hotkey, lambda cb=callback: dispatch(cb))
        )
    return _KeyboardListener(keyboard, handles)


class _KeyboardListener:
    def __init__(self, keyboard, handles):
        self.keyboard = keyboard
        self.handles = handles

    def stop(self):
        for handle in self.handles:
            self.keyboard.remove_hotkey(handle)
        self.handles.clear()


class _MacHotkeyListener:
    def __init__(self, state, thread):
        self.state = state
        self.thread = thread

    def stop(self):
        from Quartz import CFMachPortInvalidate, CFRunLoopStop

        run_loop = self.state.get("run_loop")
        tap = self.state.get("tap")
        if tap is not None:
            CFMachPortInvalidate(tap)
        if run_loop is not None:
            CFRunLoopStop(run_loop)
        if self.thread is not threading.current_thread():
            self.thread.join(timeout=2)
        self.state.clear()


def _register_macos_hotkeys(callbacks, dispatch):
    from Quartz import (
        CFMachPortCreateRunLoopSource,
        CFRunLoopAddSource,
        CFRunLoopGetCurrent,
        CFRunLoopRun,
        CGEventGetIntegerValueField,
        CGEventMaskBit,
        CGEventTapCreate,
        CGEventTapEnable,
        kCFRunLoopCommonModes,
        kCGEventKeyDown,
        kCGHeadInsertEventTap,
        kCGKeyboardEventKeycode,
        kCGSessionEventTap,
    )

    unsupported = [key for key in callbacks if key.lower() not in _MAC_KEY_CODES]
    if unsupported:
        raise ValueError(
            "macOS 当前仅支持单个数字快捷键，不支持: " + ", ".join(unsupported)
        )

    callbacks_by_code = {
        _MAC_KEY_CODES[hotkey.lower()]: callback
        for hotkey, callback in callbacks.items()
    }
    ready = threading.Event()
    state = {}

    def listen():
        def handle_event(proxy, event_type, event, refcon):
            if event_type == kCGEventKeyDown:
                key_code = CGEventGetIntegerValueField(
                    event, kCGKeyboardEventKeycode
                )
                callback = callbacks_by_code.get(key_code)
                if callback is not None:
                    dispatch(callback)
            return event

        tap = CGEventTapCreate(
            kCGSessionEventTap,
            kCGHeadInsertEventTap,
            0,
            CGEventMaskBit(kCGEventKeyDown),
            handle_event,
            None,
        )
        state["tap"] = tap
        if tap is None:
            state["error"] = RuntimeError(
                "无法监听全局快捷键，请在系统设置的“隐私与安全性 > 辅助功能”中允许终端访问"
            )
            ready.set()
            return

        run_loop = CFRunLoopGetCurrent()
        state["run_loop"] = run_loop
        source = CFMachPortCreateRunLoopSource(None, tap, 0)
        state["source"] = source
        CFRunLoopAddSource(run_loop, source, kCFRunLoopCommonModes)
        CGEventTapEnable(tap, True)
        ready.set()
        CFRunLoopRun()

    thread = threading.Thread(target=listen, name="global-hotkeys", daemon=True)
    thread.start()
    ready.wait(timeout=3)
    if "error" in state:
        raise state["error"]
    if not ready.is_set():
        raise RuntimeError("全局快捷键监听启动超时")
    return _MacHotkeyListener(state, thread)
