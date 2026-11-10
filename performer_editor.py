"""Expandable, autosaved performer name/availability table."""
import tkinter as tk
from tkinter import ttk, messagebox
from tkinter.scrolledtext import ScrolledText
import uuid

from inline_availability import performer_key, editor_drafts
from scheduler import parse_open_dates
from venue_support import schedule_venues, venue_rule
from venue_widgets import VenueDatesEditor


class PerformerEditor(ttk.Frame):
    def __init__(self, master, app, schedule_id):
        super().__init__(master, padding=(30, 8, 12, 10))
        self.app, self.schedule_id = app, schedule_id
        self.rows = []
        self.performer_query = app.schedule_search.get().strip().casefold()
        self.dirty = False
        self._save_job = None
        self._loading = True
        self._closing = False
        self._dates_dirty = False
        data = app.store.load(schedule_id)['data']
        self.venue_data = data
        inputs = ttk.Frame(self)
        inputs.pack(fill='x')
        inputs.columnconfigure(0, weight=1)
        self.date_status = tk.StringVar()
        self.venue_dates = VenueDatesEditor(inputs, data, self._venue_dates_changed, self.commit_dates)
        self.venue_dates.grid(row=0, column=0, sticky='ew')
        self._last_dates_committed = repr(self.venue_dates.snapshot())
        self.open_dates_text = self.venue_dates.texts[0]
        ttk.Label(self.venue_dates, textvariable=self.date_status, style='InlineStatus.TLabel').pack(anchor='w')
        people_panel = ttk.Frame(inputs)
        people_panel.grid(row=1, column=0, sticky='new', pady=(8, 0))
        self.venue_dates.set_people_panel(people_panel)
        tools = ttk.Frame(people_panel)
        tools.pack(fill='x', pady=(0, 6))
        ttk.Label(tools, text='PERFORMERS', style='Accent.TLabel').pack(side='left')
        ttk.Button(tools, text='Paste names', command=self.paste_clipboard,
                   state='disabled' if self.performer_query else 'normal').pack(side='right')
        venues = schedule_venues(data)
        self.multi_venue = len(venues) > 1
        self.has_venue_rules = bool(data.get('venues'))
        self._date_saved_status()
        helper = ttk.Label(people_panel, text='Dates and drafts save automatically. Leave a cell to format availability.',
                           style='Muted.TLabel', wraplength=300)
        helper.pack(fill='x', pady=(0, 6))
        people_panel.bind('<Configure>', lambda event: helper.configure(wraplength=max(100, event.width)))
        headings = ttk.Frame(people_panel)
        headings.pack(fill='x')
        headings.columnconfigure(0, weight=2, uniform='fields')
        headings.columnconfigure(1, weight=3, uniform='fields')
        headings.columnconfigure(2, minsize=120)
        ttk.Label(headings, text='NAME', style='Caption.TLabel', width=1).grid(row=0, column=0, sticky='ew', padx=(0, 8))
        ttk.Label(headings, text='AVAILABILITY', style='Caption.TLabel', width=1).grid(row=0, column=1, sticky='ew')
        self.table = ttk.Frame(people_panel)
        self.table.pack(fill='x')
        self.empty_results = ttk.Label(self.table, text='No performer names match. Clear Search to see everyone.',
                                       style='Muted.TLabel', wraplength=300)
        drafts = editor_drafts(data)
        interrupted = False
        for draft in drafts:
            if draft.get('status') == 'Formatting with AI…' or 'API key' in draft.get('status', ''):
                draft = dict(draft, status='Draft · Retry to format locally')
                interrupted = True
            self.add_row(draft)
        if not self.rows:
            self.add_row()
        ttk.Button(people_panel, text='+ Add performer', style='Quiet.TButton', command=self.add_row,
                   state='disabled' if self.performer_query else 'normal').pack(anchor='w', pady=(8, 0))
        self._loading = False
        self.apply_filter()
        if drafts != data.get('availability_drafts') or interrupted:
            self._changed()
        app._bind_scrolling(self)

    def apply_filter(self):
        """Hide nonmatching widgets while retaining every draft for saving."""
        self.empty_results.pack_forget()
        visible = 0
        for row in self.rows:
            row['frame'].pack_forget()
            if not self.performer_query or self.performer_query in row['name'].get().casefold():
                row['frame'].pack(fill='x')
                visible += 1
        if not visible:
            self.empty_results.pack(fill='x', pady=8)

    def add_row(self, draft=None):
        draft = dict(draft or dict(id=str(uuid.uuid4()), name='', availability='', status='Add a name and availability'))
        row = dict(data=draft, name=tk.StringVar(value=draft['name']), status=tk.StringVar(value=draft.get('status', '')), edited=False)
        frame = ttk.Frame(self.table, padding=(0, 3))
        frame.pack(fill='x')
        frame.columnconfigure(0, weight=2, uniform='fields')
        frame.columnconfigure(1, weight=3, uniform='fields')
        frame.columnconfigure(2, minsize=120)
        row['frame'] = frame
        row['entry'] = ttk.Entry(frame, textvariable=row['name'], width=1)
        row['entry'].grid(row=0, column=0, sticky='new', padx=(0, 8))
        row['text'] = ScrolledText(frame, height=1, width=1, wrap='word', undo=True, padx=8, pady=4)
        row['text'].grid(row=0, column=1, sticky='ew')
        row['text'].insert('1.0', draft['availability'])
        row['text'].configure(height=max(1, min(4, len(draft['availability'].splitlines()))))
        row['text'].edit_modified(False)
        row['summary'] = tk.StringVar()
        def summarize(*args):
            text = ' '.join(row['status'].get().split())
            row['summary'].set(text if len(text) <= 100 else text[:97] + '…')
        row['status'].trace_add('write', summarize)
        summarize()
        status = ttk.Label(frame, textvariable=row['summary'], style='InlineStatus.TLabel', width=1)
        status.grid(row=1, column=0, columnspan=3, sticky='ew', pady=(1, 0))
        actions = ttk.Frame(frame)
        actions.grid(row=0, column=2, sticky='n', padx=(8, 0))
        ttk.Button(actions, text='Retry', width=4, style='Quiet.TButton', command=lambda: self.commit(row, retry=True)).pack(side='left')
        ttk.Button(actions, text='Remove', width=6, style='Quiet.TButton', command=lambda: self.remove_row(row)).pack(side='left', padx=(4, 0))
        self._venue_button(row)
        self.rows.append(row)
        row['name'].trace_add('write', lambda *args: self._edited(row))
        row['text'].bind('<<Modified>>', lambda event: self._text_changed(row))
        row['entry'].bind('<<Paste>>', lambda event: self._paste_event(row))
        for field in (row['entry'], row['text']):
            field.bind('<FocusOut>', lambda event: self.commit(row))
        row['entry'].bind('<Return>', lambda event: self.commit(row))
        row['text'].bind('<Control-Return>', lambda event: self.commit(row))
        row['text'].bind('<Command-Return>', lambda event: self.commit(row))
        if not self._loading:
            self._changed()
            self.app._bind_scrolling(frame)
        return row

    def _venue_button(self, row):
        if not self.has_venue_rules:
            return
        rule = venue_rule(self.venue_data, row['name'].get())
        label = ('By venue' if rule['mode'] == 'by_venue' else 'Shared dates') + f' · {len(rule["venues"])} venues…'
        if 'venue_button' not in row:
            row['venue_button'] = ttk.Button(row['frame'], style='Quiet.TButton',
                command=lambda: self.app._edit_performer_venues(self.schedule_id, row['name'].get().strip()))
            row['venue_button'].grid(row=2, column=0, columnspan=3, sticky='w')
        row['venue_button'].configure(text=label)

    def snapshot(self):
        return [dict(row['data'], name=row['name'].get(), availability=row['text'].get('1.0', 'end-1c'),
                     status=row['status'].get()) for row in self.rows]

    def _changed(self):
        if self._loading:
            return
        self.dirty = True
        if self._save_job is not None:
            self.after_cancel(self._save_job)
        self._save_job = self.after(400, self.flush)

    def _edited(self, row):
        row['edited'] = True
        row['status'].set('Draft · finish the availability cell to convert')
        self._changed()

    def _text_changed(self, row):
        if row['text'].edit_modified():
            row['text'].edit_modified(False)
            lines = int(row['text'].index('end-1c').split('.')[0])
            row['text'].configure(height=max(1, min(4, lines)))
            self._edited(row)

    def flush(self):
        if self._save_job is not None:
            self.after_cancel(self._save_job)
            self._save_job = None
        # Modified events can still be queued when navigation starts.
        if any(field.edit_modified() for field in self.venue_dates.texts):
            for field in self.venue_dates.texts:
                field.edit_modified(False)
            self._dates_dirty = self.dirty = True
        for row in self.rows:
            if row['text'].edit_modified():
                row['text'].edit_modified(False)
                row['edited'] = True
                row['status'].set('Draft · finish the availability cell to convert')
                self.dirty = True
        if not self.dirty:
            return True
        try:
            self.app.store.save_inline_editor(self.schedule_id, self.snapshot(),
                                              self.venue_dates.combined_text() if self._dates_dirty else None)
            if self._dates_dirty and self.venue_dates.explicit:
                self.app.store.save_venues(self.schedule_id, self.venue_dates.snapshot(), validate=False)
                self.venue_data = self.app.store.load(self.schedule_id)['data']
                self.has_venue_rules = True
                self.multi_venue = len(self.venue_dates.cards) > 1
                saved = {d['id']: d for d in self.venue_data.get('availability_drafts', [])}
                for row in self.rows:
                    draft = saved.get(row['data']['id'])
                    if draft and draft['availability'] != row['text'].get('1.0', 'end-1c'):
                        row['text'].delete('1.0', 'end')
                        row['text'].insert('1.0', draft['availability'])
                        row['text'].edit_modified(False)
                    self._venue_button(row)
        except Exception as error:
            messagebox.showerror('Performer drafts could not be saved', str(error), parent=self)
            return False
        if self._dates_dirty:
            self._date_saved_status()
        self.dirty = False
        self._dates_dirty = False
        return True

    def _date_saved_status(self):
        try:
            dates = parse_open_dates(self.venue_dates.combined_text())
        except ValueError:
            self.date_status.set('Draft saved · use M/D/YYYY')
        else:
            self.date_status.set(f'{len(dates)} open dates · saved' if dates else 'Add open dates')

    def _venue_dates_changed(self):
        self.open_dates_text = self.venue_dates.texts[0]
        if not self._loading:
            self._dates_dirty = True
            self.date_status.set('Saving…')
            self._changed()

    def commit_dates(self, event=None):
        if self._closing or not self.flush():
            return 'break'
        text = self.venue_dates.combined_text()
        signature = repr(self.venue_dates.snapshot())
        try:
            dates = parse_open_dates(text)
        except ValueError:
            self.date_status.set('Draft saved · use M/D/YYYY')
            return 'break'
        self.date_status.set(f'{len(dates)} open dates · saved')
        if signature != self._last_dates_committed:
            self._last_dates_committed = signature
            for row in self.rows:
                if row['name'].get().strip() and row['text'].get('1.0', 'end-1c').strip():
                    row['edited'] = False
                    self.app._convert_inline(self.schedule_id, row['data']['id'])
        return 'break'

    def commit(self, row, retry=False):
        if self._closing or row not in self.rows or not self.flush():
            return 'break'
        if not retry and not row['edited']:
            return 'break'
        if row['name'].get().strip() and row['text'].get('1.0', 'end-1c').strip():
            row['edited'] = False
            self.app._convert_inline(self.schedule_id, row['data']['id'], retry=retry)
        return 'break'

    def paste_clipboard(self):
        try:
            self.paste_names(self.clipboard_get())
        except tk.TclError:
            return

    def _paste_event(self, row):
        try:
            text = self.clipboard_get()
        except tk.TclError:
            return 'break'
        if len(text.splitlines()) > 1:
            self.paste_names(text, row)
            return 'break'
        # Single-name pastes used to fall through to Entry's default insertion,
        # appending a second copy when the same name was pasted again. Match
        # the duplicate-name handling used by multiline paste and Paste names.
        key = performer_key(text)
        if key and any(performer_key(item['name'].get()) == key for item in self.rows):
            return 'break'

    def paste_names(self, text, target=None):
        names = list(dict.fromkeys(name.strip() for name in text.splitlines() if name.strip()))
        existing = {performer_key(row['name'].get()): row for row in self.rows if row['name'].get().strip()}
        for name in names:
            key = performer_key(name)
            if key in existing:
                continue
            row = target if target is not None and not target['name'].get().strip() else next(
                (row for row in self.rows if not row['name'].get().strip() and not row['text'].get('1.0', 'end-1c').strip()), None)
            if row is None:
                row = self.add_row()
            row['name'].set(name)
            existing[key] = row
            target = None
        self._changed()

        self.apply_filter()

    def remove_row(self, row):
        self.rows.remove(row)
        row['frame'].destroy()
        self._changed()
        self.apply_filter()

    def refresh_row(self, row_id):
        try:
            drafts = self.app.store.load(self.schedule_id)['data'].get('availability_drafts', [])
        except ValueError:
            return
        draft = next((draft for draft in drafts if draft['id'] == row_id), None)
        row = next((row for row in self.rows if row['data']['id'] == row_id), None)
        if draft and row and (row['name'].get(), row['text'].get('1.0', 'end-1c')) == (draft['name'], draft['availability']):
            row['data'] = dict(draft)
            row['status'].set(draft.get('status', ''))
            if 'venue_button' in row:
                rule = venue_rule(self.app.store.load(self.schedule_id)['data'], draft['name'])
                row['venue_button'].configure(text=('By venue' if rule['mode'] == 'by_venue' else 'Shared dates')
                                              + f' · {len(rule["venues"])} venues…')

    def destroy(self):
        self._closing = True
        if self._save_job is not None:
            self.after_cancel(self._save_job)
            self._save_job = None
        super().destroy()
