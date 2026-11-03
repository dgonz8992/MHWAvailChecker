"""Compact schedule rows with native controls and a divider under every row."""
import tkinter as tk
from tkinter import ttk
from scrollable import ScrollableFrame


class ScheduleList(ScrollableFrame):
    def __init__(self, master, on_context=None, on_expand=None, on_edit_notes=None):
        super().__init__(master, padding=0)
        self._items = {}
        self._selected = []
        self._empty = None
        self._on_context = on_context
        self._on_edit_notes = on_edit_notes
        self._on_expand = on_expand
        self._expanded = set()
        self.bind('<Return>', lambda event: self.event_generate('<<OpenSchedule>>'))

    def _fit(self):
        # Expanded editors follow the viewport instead of widening the canvas.
        self._pending_fit = None
        if not self.winfo_exists():
            return
        # Let Tk track the content's requested height. Fixing this height keeps
        # Configure from firing when an editor expands or adds performer rows.
        self.canvas.itemconfigure(self.window, width=max(1, self.canvas.winfo_width()), height=0)
        self.canvas.configure(scrollregion=(0, 0, max(1, self.canvas.winfo_width()),
                                            self.content.winfo_reqheight()))

    def get_children(self):
        return tuple(self._items)

    def exists(self, item):
        return item in self._items

    def selection(self):
        return tuple(item for item in self._items if item in self._selected)

    def selection_set(self, items):
        if isinstance(items, str):
            items = [items]
        self._selected = [item for item in items if item in self._items]
        for item, data in self._items.items():
            data['checked'].set(item in self._selected)
        self.event_generate('<<ScheduleSelected>>')

    def insert(self, parent, position, iid, values):
        if self._empty is not None:
            self._empty.destroy()
            self._empty = None
        frame = ttk.Frame(self.content)
        frame.pack(fill='x')
        row = ttk.Frame(frame, padding=(4, 3))
        row.pack(fill='x')
        row.columnconfigure(2, weight=2, minsize=170)
        row.columnconfigure(3, weight=3, minsize=150)
        checked = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, variable=checked, command=lambda: self._toggle(iid)).grid(row=0, column=0, padx=(0, 4))
        expand = ttk.Button(row, text='▸', style='Quiet.TButton', width=2, command=lambda: self.toggle_expanded(iid))
        expand.grid(row=0, column=1, padx=(0, 4))
        name = ttk.Label(row, text=values[0], width=1, style='RowName.TLabel')
        name.grid(row=0, column=2, sticky='ew', padx=(0, 12))
        notes = ttk.Label(row, text=values[1] or 'Add notes…', width=1, anchor='w',
                          padding=(6, 0), style='RowMeta.TLabel')
        notes.grid(row=0, column=3, sticky='nsew')
        updated = ttk.Label(row, text=values[2], width=19, style='RowMeta.TLabel')
        updated.grid(row=0, column=4, sticky='e')
        ttk.Separator(frame, orient='horizontal').pack(fill='x')
        self._items[iid] = {'frame': frame, 'checked': checked, 'values': tuple(values),
                            'name': name, 'notes': notes, 'updated': updated, 'expand': expand, 'editor': None}
        for widget in (row, name, notes, updated):
            widget.bind('<Button-1>', lambda event, item=iid: self._select_row(item))
            widget.bind('<Double-1>', lambda event, item=iid: self._open(item))
        if self._on_edit_notes is not None:
            notes.configure(cursor='xterm')
            notes.bind('<Button-1>', lambda event: self._on_edit_notes(iid))
            notes.bind('<Double-1>', lambda event: self._on_edit_notes(iid))
        sequences = ['<Button-3>']
        if self.tk.call('tk', 'windowingsystem') == 'aqua':
            sequences.extend(('<Button-2>', '<Control-Button-1>'))
        for widget in (frame, row, *row.winfo_children(), frame.winfo_children()[-1]):
            for sequence in sequences:
                widget.bind(sequence, lambda event, item=iid: self._context_menu(item, event))
        if iid in self._expanded:
            self._expanded.discard(iid)
            self.toggle_expanded(iid)

    def toggle_expanded(self, item):
        data = self._items[item]
        if item in self._expanded:
            if data['editor'] is not None and not data['editor'].flush():
                return
            self._expanded.discard(item)
            data['expand'].configure(text='▸')
            if data['editor'] is not None:
                data['editor'].pack_forget()
            # Offscreen canvas windows do not always emit Configure on shrink.
            # Settle pack geometry before refreshing the visible scroll range.
            self.update_idletasks()
            self._schedule_fit()
            return
        if self._on_expand is None:
            return
        if data['editor'] is None:
            data['editor'] = self._on_expand(item, data['frame'])
        data['editor'].pack(fill='x', before=data['frame'].winfo_children()[1])
        data['expand'].configure(text='▾')
        self._expanded.add(item)
        self.update_idletasks()
        self._schedule_fit()

    def flush_editors(self):
        return all(data['editor'] is None or data['editor'].flush() for data in self._items.values())

    def set_all_expanded(self, expanded):
        if not expanded and not self.flush_editors():
            return False
        for item in self.get_children():
            if (item in self._expanded) != expanded:
                self.toggle_expanded(item)
        return True

    def _context_menu(self, item, event):
        if self._on_context is not None:
            self._on_context(item, event)
        return 'break'

    def _toggle(self, item):
        self._selected = [key for key, data in self._items.items() if data['checked'].get()]
        self.event_generate('<<ScheduleSelected>>')

    def show_empty(self, title, message):
        if self._items:
            if self._empty is not None:
                self._empty.destroy()
                self._empty = None
            return
        if self._empty is None:
            self._empty = ttk.Frame(self.content, padding=(24, 48))
            self._empty_title = ttk.Label(self._empty, style='RowName.TLabel')
            self._empty_title.pack(pady=(0, 8))
            self._empty_message = ttk.Label(self._empty, style='Muted.TLabel')
            self._empty_message.pack()
        self._empty_title.configure(text=title)
        self._empty_message.configure(text=message)
        self._empty.pack(fill='x')

    def _select_row(self, item):
        self.focus_set()
        self.selection_set(item)

    def _open(self, item):
        self.selection_set(item)
        self.event_generate('<<OpenSchedule>>')

    def delete(self, *items):
        for item in items:
            self._items.pop(item)['frame'].destroy()
        self._selected = [item for item in self._selected if item in self._items]

    def item(self, item, option=None, **options):
        data = self._items[item]
        if 'values' in options:
            data['values'] = tuple(options['values'])
            data['name'].configure(text=options['values'][0])
            data['notes'].configure(text=options['values'][1] or 'Add notes…')
            data['updated'].configure(text=options['values'][2])
        if option == 'values':
            return data['values']
        return {'values': data['values']}
