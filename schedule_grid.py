"""Native schedule table with spreadsheet-style cell and column selection."""
import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace


class ScheduleGrid(ttk.Treeview):
    def __init__(self, master, **kwargs):
        super().__init__(master, style='Schedule.Treeview', **kwargs)
        self.anchor_cell = self.end_cell = None
        self.column_selection = None
        self._paint_job = None
        self._highlights = []
        self._last_click = (None, 0)
        self.bind('<Button-1>', self._click)
        self.bind('<B1-Motion>', self._drag)
        self.bind('<<TreeviewSelect>>', self._queue_paint)
        self.bind('<Configure>', self._queue_paint, add=True)
        for key in ('Up', 'Down', 'Left', 'Right'):
            self.bind(f'<{key}>', self._arrow)
            self.bind(f'<Shift-{key}>', self._arrow)

    def _cell(self, event):
        row = self.identify_row(event.y)
        col = self.identify_column(event.x)
        if row and col and col != '#0':
            index = int(col[1:]) - 1
            if 0 <= index < len(self['columns']):
                return row, index
        return None

    def _click(self, event):
        cell = self._cell(event)
        if cell is None:
            return
        self.focus_set()
        self.select_cell(*cell, extend=bool(event.state & 1))
        when = getattr(event, 'time', 0)
        previous, previous_time = self._last_click
        self._last_click = (cell, when)
        # Selection highlights are child windows; keep double-clicks working
        # when the second press lands on the newly highlighted cell.
        if when and previous == cell and 0 < when - previous_time <= 500 and not event.state & 1:
            self.winfo_toplevel()._edit_schedule_cell(SimpleNamespace(keysym='', x=event.x, y=event.y))
        return 'break'

    def _drag(self, event):
        self._queue_paint()
        cell = self._cell(event)
        if cell is not None and self.anchor_cell is not None:
            self.select_cell(*cell, extend=True)
            return 'break'

    def select_cell(self, row, column, extend=False):
        if not self.exists(row):
            return
        if isinstance(column, str):
            column = list(self['columns']).index(column)
        self.column_selection = None
        if not extend or self.anchor_cell is None or not self.exists(self.anchor_cell[0]):
            self.anchor_cell = (row, column)
        self.end_cell = (row, column)
        rows, _ = self.selected_cells()
        self.selection_set(rows)
        self.focus(row)
        self._queue_paint()

    def select_column(self, column):
        self.focus_set()
        self.anchor_cell = self.end_cell = None
        self.column_selection = column
        self.selection_set(self.get_children())
        if self.get_children():
            self.focus(self.get_children()[0])
        self._queue_paint()

    def selected_cells(self):
        rows = list(self.get_children())
        columns = list(self['columns'])
        if self.column_selection in columns:
            return rows, [columns.index(self.column_selection)]
        if self.anchor_cell and self.end_cell and self.anchor_cell[0] in rows and self.end_cell[0] in rows:
            first, last = sorted((rows.index(self.anchor_cell[0]), rows.index(self.end_cell[0])))
            left, right = sorted((self.anchor_cell[1], self.end_cell[1]))
            return rows[first:last + 1], list(range(left, right + 1))
        return [], []

    def selection_text(self):
        rows, columns = self.selected_cells()
        if not rows or not columns:
            return None
        return '\n'.join('\t'.join(str(self.item(row, 'values')[col]) for col in columns) for row in rows)

    def clear_cells(self):
        self.anchor_cell = self.end_cell = self.column_selection = None
        for label in self._highlights:
            label.place_forget()

    def delete(self, *items):
        self.clear_cells()
        return super().delete(*items)

    def xview(self, *args):
        result = super().xview(*args)
        if args:
            self._queue_paint()
        return result

    def yview(self, *args):
        result = super().yview(*args)
        if args:
            self._queue_paint()
        return result

    def xview_moveto(self, fraction):
        super().xview_moveto(fraction)
        self._queue_paint()

    def yview_moveto(self, fraction):
        super().yview_moveto(fraction)
        self._queue_paint()

    def xview_scroll(self, *args):
        super().xview_scroll(*args)
        self._queue_paint()

    def yview_scroll(self, *args):
        super().yview_scroll(*args)
        self._queue_paint()

    def _arrow(self, event):
        rows = list(self.get_children())
        if not rows:
            return 'break'
        row, col = self.end_cell or (self.focus() or rows[0], 0)
        index = rows.index(row) if row in rows else 0
        index += (event.keysym == 'Down') - (event.keysym == 'Up')
        col += (event.keysym == 'Right') - (event.keysym == 'Left')
        row = rows[max(0, min(len(rows) - 1, index))]
        self.select_cell(row, max(0, min(len(self['columns']) - 1, col)), extend=bool(event.state & 1))
        self.see(row)
        return 'break'

    def _queue_paint(self, event=None):
        if self._paint_job is None:
            self._paint_job = self.after_idle(self._paint)

    def _forward(self, event, sequence):
        self.event_generate(sequence, x=event.x_root - self.winfo_rootx(),
                            y=event.y_root - self.winfo_rooty(), state=event.state, time=event.time)
        return 'break'

    def _paint(self):
        self._paint_job = None
        for label in self._highlights:
            label.place_forget()
        selected, columns = self.selected_cells()
        if not selected:
            return
        selected = set(selected)
        palette = self.winfo_toplevel()._appearance_palette
        step = int(ttk.Style(self).lookup('Treeview', 'rowheight') or 30)
        visible = dict.fromkeys(self.identify_row(y) for y in [*range(0, self.winfo_height(), step), self.winfo_height()-1])
        used = 0
        for row in visible:
            if not row or row not in selected:
                continue
            for column in columns:
                box = self.bbox(row, self['columns'][column])
                if not box:
                    continue
                x, y, width, height = box
                if x + width <= 0 or x >= self.winfo_width():
                    continue
                if used == len(self._highlights):
                    label = tk.Label(self, anchor='w', padx=6, borderwidth=1, relief='solid')
                    for sequence in ('<Button-1>', '<B1-Motion>', '<Button-3>', '<Button-2>', '<Control-Button-1>'):
                        label.bind(sequence, lambda event, sequence=sequence: self._forward(event, sequence))
                    label.bind('<Double-1>', lambda event: self.winfo_toplevel()._edit_schedule_cell(
                        SimpleNamespace(keysym='', x=event.x_root-self.winfo_rootx(), y=event.y_root-self.winfo_rooty())))
                    self.winfo_toplevel()._bind_scrolling(label)
                    self._highlights.append(label)
                label = self._highlights[used]
                label.configure(text=self.item(row, 'values')[column], background=palette['selection'],
                                foreground=palette['ink'], highlightthickness=0, font='TkDefaultFont')
                label.place(x=max(0, x), y=y, width=min(x + width, self.winfo_width()) - max(0, x), height=height)
                used += 1
        edit = self.winfo_toplevel()._schedule_edit
        if edit is not None and edit[0].master is self:
            edit[0].lift()

    def destroy(self):
        if self._paint_job is not None:
            self.after_cancel(self._paint_job)
        super().destroy()
