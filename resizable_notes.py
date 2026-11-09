"""Notes that expand for editing and return to a compact height on blur."""
import tkinter as tk
from tkinter import font, ttk
from tkinter.scrolledtext import ScrolledText


class ResizableNotes(ScrolledText):
    def __init__(self, master, **kwargs):
        self.compact_height = kwargs.get('height', 3)
        self._blur_job = None
        self._dragging = False
        self._menu_open = False
        super().__init__(master, **kwargs)
        self.tools = ttk.Frame(self.frame)
        self.tools.pack(side='top', fill='x', before=self.vbar)
        self.resize_handle = ttk.Label(self.frame, text='Drag to resize  ↕', cursor='sb_v_double_arrow',
                                       style='InlineStatus.TLabel', padding=(6, 2), anchor='e')
        self.resize_handle.pack(side='bottom', fill='x', before=self.vbar)
        self.resize_handle.bind('<ButtonPress-1>', self._start_resize)
        self.resize_handle.bind('<B1-Motion>', self._resize)
        self.resize_handle.bind('<ButtonRelease-1>', self._end_resize)
        self.bind('<FocusIn>', self._expand, add=True)
        self.bind('<FocusOut>', self._blurred, add=True)

    def _expand(self, event=None):
        if int(self.cget('height')) == self.compact_height:
            self.configure(height=max(8, self.compact_height))

    def _start_resize(self, event):
        self._dragging = True
        self.focus_set()
        self._drag_y = event.y_root
        self._drag_height = int(self.cget('height'))
        return 'break'

    def _resize(self, event):
        if self._dragging:
            line = max(1, font.Font(root=self, font=self.cget('font')).metrics('linespace'))
            height = self._drag_height + round((event.y_root - self._drag_y) / line)
            self.configure(height=max(2, min(40, height)))
        return 'break'

    def _end_resize(self, event):
        self._resize(event)
        self._dragging = False
        self._blurred()
        return 'break'

    def _blurred(self, event=None):
        if self._blur_job is not None:
            self.after_cancel(self._blur_job)
        self._blur_job = self.after_idle(self._collapse_on_blur)

    def _collapse_on_blur(self):
        self._blur_job = None
        if self._dragging or self._menu_open:
            return
        focused = self.focus_get()
        while focused is not None:
            if focused is self.frame:
                return
            focused = focused.master
        self.configure(height=self.compact_height)

    def collapse(self):
        self._dragging = False
        self.configure(height=self.compact_height)

    def destroy(self):
        if self._blur_job is not None:
            self.after_cancel(self._blur_job)
            self._blur_job = None
        super().destroy()
