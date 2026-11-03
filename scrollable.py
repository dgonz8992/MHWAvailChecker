"""A content frame that remains reachable in both directions in small windows."""
import tkinter as tk
from tkinter import ttk


class ScrollableFrame(ttk.Frame):
    def __init__(self, master, padding=16):
        super().__init__(master)
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, highlightthickness=0, xscrollincrement=20, yscrollincrement=20)
        vertical = ttk.Scrollbar(self, orient='vertical', command=self.canvas.yview)
        horizontal = ttk.Scrollbar(self, orient='horizontal', command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.canvas.grid(row=0, column=0, sticky='nsew')
        vertical.grid(row=0, column=1, sticky='ns')
        horizontal.grid(row=1, column=0, sticky='ew')
        self.content = ttk.Frame(self.canvas, padding=padding)
        self.window = self.canvas.create_window((0, 0), window=self.content, anchor='nw')
        self._pending_fit = None
        self.content.bind('<Configure>', self._schedule_fit)
        self.canvas.bind('<Configure>', self._schedule_fit)

    def _schedule_fit(self, event=None):
        if self._pending_fit is None:
            self._pending_fit = self.after_idle(self._fit)

    def _fit(self):
        self._pending_fit = None
        if not self.winfo_exists():
            return
        width = max(self.content.winfo_reqwidth(), self.canvas.winfo_width())
        height = max(self.content.winfo_reqheight(), self.canvas.winfo_height())
        self.canvas.itemconfigure(self.window, width=width, height=height)
        self.canvas.configure(scrollregion=self.canvas.bbox('all'))

    def destroy(self):
        if self._pending_fit is not None:
            self.after_cancel(self._pending_fit)
            self._pending_fit = None
        super().destroy()
