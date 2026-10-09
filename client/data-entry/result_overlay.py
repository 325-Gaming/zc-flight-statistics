"""Windows result strip; all window operations belong to its own UI thread."""

import ctypes
import queue
import sys
import threading
from contextlib import contextmanager
from ctypes import wintypes

from utils import gacha10_horizontal_bounds


def overlay_geometry(monitor):
    """Place the strip below the entire ten-pull region in the centered crop."""
    width, height = monitor['width'], monitor['height']
    crop_height = min(height, int(width * 9 / 16))
    top = (height - crop_height) // 2 + int(crop_height * 0.8) + 31
    return monitor['left'], monitor['top'] + top, width, max(1, height - top)


def overlay_cells(monitor):
    """Divide the recognition area's shared left/right limits into ten cells."""
    width, height = monitor['width'], monitor['height']
    crop_width = min(width, int(height * 16 / 9))
    crop_left = (width - crop_width) // 2
    left, right = gacha10_horizontal_bounds(crop_width)
    edges = [crop_left + left + round((right - left) * i / 10) for i in range(11)]
    return [(edges[i], edges[i + 1] - edges[i]) for i in range(10)]



class ResultOverlay:
    def __init__(self):
        self.commands = queue.Queue()
        self.thread = None
        self.lock = threading.Lock()
        self.results = None
        self.enabled = False
        self.monitor = None
        self.closed = False

    def configure(self, enabled, monitor):
        if enabled and sys.platform != 'win32':
            raise ValueError('识别结果悬浮窗口目前仅支持 Windows')
        with self.lock:
            if self.closed:
                return
            self.enabled = enabled
            self.monitor = dict(monitor)
            if enabled and self.thread is None:
                self.thread = threading.Thread(target=self._run, daemon=True, name='result-overlay')
                self.thread.start()
            if self.thread is not None:
                self.commands.put(('refresh', None))

    def show_result(self, results):
        with self.lock:
            self.results = tuple(results)
            if self.thread is not None and not self.closed:
                self.commands.put(('refresh', None))

    @contextmanager
    def hidden_for_capture(self):
        # Hide even on Windows versions without WDA_EXCLUDEFROMCAPTURE.
        ready = threading.Event()
        with self.lock:
            active = self.thread is not None and self.thread.is_alive() and not self.closed
            if active:
                self.commands.put(('hide', ready))
        if active and not ready.wait(2):
            raise RuntimeError('悬浮窗口未能及时隐藏，请重试截图')
        try:
            yield
        finally:
            if active:
                self.commands.put(('resume', None))

    def close(self):
        with self.lock:
            self.closed = True
            if self.thread is not None:
                self.commands.put(('close', None))

    def _run(self):
        import tkinter as tk
        from tkinter import font as tkfont

        user32 = ctypes.WinDLL('user32', use_last_error=True)
        if hasattr(user32, 'SetThreadDpiAwarenessContext'):
            user32.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
            user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
            user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
        root = tk.Tk()
        root.withdraw()
        root.overrideredirect(True)
        root.configure(bg='#152030')
        label_options = dict(bg='#152030', fg='white', padx=4, pady=6,
                             font=('Microsoft YaHei UI', 32), anchor='center', justify='center')
        waiting_label = tk.Label(root, text='等待十连识别结果', **label_options)
        waiting_label.place(x=0, y=0, relwidth=1, relheight=1)
        fonts = [tkfont.Font(root=root, family='Microsoft YaHei UI', size=32) for _ in range(10)]
        labels = [tk.Label(root, **{**label_options, 'font': font},
                           borderwidth=0, highlightthickness=1,
                           highlightbackground='#b8d4f0', highlightcolor='#b8d4f0')
                  for font in fonts]
        root.update_idletasks()
        user32.GetParent.argtypes = [wintypes.HWND]
        user32.GetParent.restype = wintypes.HWND
        user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                      ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        user32.SetWindowPos.restype = wintypes.BOOL
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.ShowWindow.restype = wintypes.BOOL
        get_style = user32.GetWindowLongPtrW if ctypes.sizeof(ctypes.c_void_p) == 8 else user32.GetWindowLongW
        set_style = user32.SetWindowLongPtrW if ctypes.sizeof(ctypes.c_void_p) == 8 else user32.SetWindowLongW
        get_style.argtypes = [wintypes.HWND, ctypes.c_int]
        get_style.restype = ctypes.c_ssize_t
        set_style.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        set_style.restype = ctypes.c_ssize_t
        user32.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.DWORD, wintypes.BYTE, wintypes.DWORD]
        user32.SetLayeredWindowAttributes.restype = wintypes.BOOL
        hwnd = user32.GetParent(root.winfo_id()) or root.winfo_id()
        # Layered + transparent forwards clicks to other applications; noactivate
        # prevents stealing focus, toolwindow keeps the strip out of Alt+Tab.
        set_style(hwnd, -20, get_style(hwnd, -20) | 0x80000 | 0x20 | 0x8000000 | 0x80)
        user32.SetLayeredWindowAttributes(hwnd, 0, 180, 2)
        hidden = 0

        def refresh():
            with self.lock:
                enabled, monitor, results = self.enabled, self.monitor, self.results
            if not enabled or hidden or not monitor:
                user32.ShowWindow(hwnd, 0)
                return
            x, y, width, available = overlay_geometry(monitor)
            if results is None:
                requested_height = waiting_label.winfo_reqheight()
            else:
                waiting_label.place_forget()
                for label, font, text, (left, cell_width) in zip(labels, fonts, results, overlay_cells(monitor)):
                    # Measure the actual font at this display's scale; each result
                    # starts at 32 pt again so a previous long name cannot shrink it.
                    font.configure(size=32)
                    text_width = max(1, cell_width - 2 * (4 + label.winfo_pixels(label.cget('highlightthickness'))))
                    while font.measure(text) > text_width and font.cget('size') > 1:
                        font.configure(size=font.cget('size') - 1)
                    label.configure(text=text, wraplength=0)
                    label.place(x=left, y=0, width=cell_width, relheight=1)
                root.update_idletasks()
                requested_height = max(label.winfo_reqheight() for label in labels)
            height = min(available, requested_height)
            # Absolute coordinates handle monitors to the left/above the primary.
            user32.SetWindowPos(hwnd, wintypes.HWND(-1), x, y, width, height, 0x10 | 0x40)

        def poll():
            nonlocal hidden
            while True:
                try:
                    command, ready = self.commands.get_nowait()
                except queue.Empty:
                    break
                if command == 'close':
                    root.destroy()
                    return
                if command == 'hide':
                    hidden += 1
                    user32.ShowWindow(hwnd, 0)
                    ctypes.WinDLL('dwmapi').DwmFlush()
                    ready.set()
                elif command == 'resume':
                    hidden = max(0, hidden - 1)
                refresh()
            root.after(30, poll)

        poll()
        root.mainloop()


result_overlay = ResultOverlay()
