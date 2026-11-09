"""Compact schedule rows with native controls and a divider under every row."""
import tkinter as tk
from tkinter import ttk
from scrollable import ScrollableFrame


class ScheduleList(ScrollableFrame):
    def __init__(self, master, on_context=None, on_expand=None, on_edit_notes=None, expansion_height=None):
        super().__init__(master, padding=0)
        self._items = {}
        self._selected = []
        self._empty = None
        self._on_context = on_context
        self._on_edit_notes = on_edit_notes
        self._on_expand = on_expand
        self._expansion_height = expansion_height
        self._viewport_job = None
        self._batch_allowance = None
        self.canvas.configure(yscrollcommand=self._viewport_changed)
        self._expanded = set()
        self.bind('<Return>', lambda event: self.event_generate('<<OpenSchedule>>'))

    def _fit(self):
        # Expanded editors follow the viewport instead of widening the canvas.
        self._pending_fit = None
        if not self.winfo_exists():
            return
        # Let Tk track the content's requested height. Fixing this height keeps
        # Configure from firing when an editor expands or adds performer rows.
        width = max(1, self.canvas.winfo_width())
        if float(self.canvas.itemcget(self.window, 'width')) != width:
            self.canvas.itemconfigure(self.window, width=width, height=0)
        region = (0, 0, width, self.content.winfo_reqheight())
        current = tuple(int(float(value)) for value in str(self.canvas.cget('scrollregion')).split())
        if current != region:
            at_bottom = bool(current and current[3] > self.canvas.winfo_height() and self.canvas.yview()[1] >= .999999)
            self.canvas.configure(scrollregion=region)
            if at_bottom:
                self.canvas.yview_moveto(1)
        self._schedule_viewport()

    def _body_allowance(self, count):
        # macOS native child coordinates stop behaving correctly beyond 32767
        # pixels. Keep offscreen editors compact and reserve room for live ones.
        headers = sum(max(41, item['name'].master.winfo_reqheight() + 1) for item in self._items.values())
        budget = max(0, 22000 - headers)
        return max(1, budget // max(1, count))

    def _spacer_height(self, data, allowance=None):
        if allowance is None:
            allowance = self._batch_allowance or self._body_allowance(len(self._expanded))
        return min(data['estimated_height'], 320, allowance)

    def _resize_spacers(self):
        allowance = self._body_allowance(len(self._expanded))
        for item, data in self._items.items():
            if item in self._expanded and data['spacer'] is not None:
                height = self._spacer_height(data, allowance)
                if data['spacer'].winfo_reqheight() != height:
                    data['spacer'].configure(height=height)

    def _viewport_changed(self, first, last):
        self.vertical_scrollbar.set(first, last)
        self._schedule_viewport()

    def _schedule_viewport(self):
        if self._viewport_job is None:
            self._viewport_job = self.after_idle(self._realize_visible_expansions)

    def _realize_visible_expansions(self):
        self._viewport_job = None
        height = max(1, self.canvas.winfo_height())
        top = self.canvas.canvasy(0)
        realized = 0
        for item, data in self._items.items():
            if item not in self._expanded:
                continue
            frame = data['frame']
            spacer = data['spacer']
            if frame.winfo_width() <= 1 or (spacer.winfo_manager() and frame.winfo_height() < spacer.winfo_reqheight()):
                continue  # Placeholder geometry has not propagated yet.
            near = frame.winfo_y() + frame.winfo_height() >= top - height and frame.winfo_y() <= top + 2 * height
            if near:
                needs_layout = data['editor'] is None or not data['editor'].winfo_manager()
                self.ensure_editor(item)
                realized += needs_layout
                if realized >= 2:
                    break  # Let geometry settle before deciding who is near next.
            elif data['editor'] is not None and data['editor'].winfo_manager():
                editor = data['editor']
                focused = self.focus_get()
                while focused is not None and focused is not editor:
                    focused = focused.master
                if focused is editor or not editor.flush():
                    continue
                data['estimated_height'] = max(1, editor.winfo_reqheight())
                data['spacer'].configure(height=self._spacer_height(data))
                editor.pack_forget()
                data['spacer'].pack(fill='x', before=data['separator'])
                self._schedule_fit()

    def ensure_editor(self, item):
        data = self._items[item]
        if data['editor'] is None:
            data['editor'] = self._on_expand(item, data['frame'])
        if item in self._expanded and not data['editor'].winfo_manager():
            data['spacer'].pack_forget()
            data['editor'].pack(fill='x', before=data['separator'])
            self._schedule_fit()
        return data['editor']

    def _schedule_fit(self, event=None):
        if self._pending_fit is None:
            self._pending_fit = self.after_idle(self._settle_fit)

    def _settle_fit(self):
        # Let pack/grid propagate requests before measuring, without forcing a
        # complete native layout for every individual schedule in Expand all.
        self._pending_fit = self.after_idle(self._fit)

    def get_children(self):
        return tuple(self._items)

    def exists(self, item):
        return item in self._items

    def selection(self):
        return tuple(item for item in self._items if item in self._selected)

    def see(self, item):
        if item not in self._items:
            return
        self.update_idletasks()
        row = self._items[item]['frame']
        top = row.winfo_y()
        height = max(1, self.content.winfo_reqheight())
        viewport_top = self.canvas.canvasy(0)
        if top < viewport_top or top + row.winfo_height() > viewport_top + self.canvas.winfo_height():
            self.canvas.yview_moveto(top / height)

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
        separator = ttk.Separator(frame, orient='horizontal')
        separator.pack(fill='x')
        self._items[iid] = {'frame': frame, 'checked': checked, 'values': tuple(values),
                            'name': name, 'notes': notes, 'updated': updated, 'expand': expand, 'editor': None,
                            'separator': separator, 'spacer': None, 'estimated_height': 320}
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
            self.toggle_expanded(iid, defer=True)

    def toggle_expanded(self, item, defer=False):
        data = self._items[item]
        if item in self._expanded:
            if data['editor'] is not None and not data['editor'].flush():
                return
            self._expanded.discard(item)
            data['expand'].configure(text='▸')
            if data['editor'] is not None:
                data['editor'].pack_forget()
            if data['spacer'] is not None:
                data['spacer'].pack_forget()
            self._schedule_fit()
            return
        if self._on_expand is None:
            return
        data['expand'].configure(text='▾')
        self._expanded.add(item)
        if data['spacer'] is None:
            estimate = self._expansion_height(item) if self._expansion_height else 320
            data['estimated_height'] = estimate
            data['spacer'] = ttk.Frame(data['frame'], height=self._spacer_height(data))
        if self._batch_allowance is None:
            self._resize_spacers()
        if defer:
            data['spacer'].pack(fill='x', before=data['separator'])
        else:
            self.ensure_editor(item)
        self._schedule_fit()

    def flush_editors(self):
        return all(data['editor'] is None or data['editor'].flush() for data in self._items.values())

    def set_all_expanded(self, expanded):
        if not expanded and not self.flush_editors():
            return False
        self._batch_allowance = self._body_allowance(len(self._items))
        try:
            for item in self.get_children():
                if (item in self._expanded) != expanded:
                    self.toggle_expanded(item, defer=expanded)
        finally:
            self._batch_allowance = None
            self._resize_spacers()
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

    def destroy(self):
        if self._viewport_job is not None:
            self.after_cancel(self._viewport_job)
            self._viewport_job = None
        super().destroy()

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
