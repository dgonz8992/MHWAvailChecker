"""Venue dates and shared/per-venue performer availability editors."""
import re
import tkinter as tk
from tkinter import ttk, simpledialog, messagebox
from tkinter.scrolledtext import ScrolledText
import uuid

from inline_availability import performer_key, format_inline, performer_value
from venue_support import schedule_venues, venue_rule, combined_dates, date_text, format_venue_availability
from scheduler import parse_open_dates
from resizable_notes import ResizableNotes


class VenueDatesEditor(ttk.Frame):
    """Inline venue cards; incomplete date edits remain saved as drafts."""
    def __init__(self, master, data, changed, commit, width=14):
        super().__init__(master)
        self.changed, self.commit = changed, commit
        self.date_width = width
        self.cards = []
        self.people_panel = None
        self._card_layout = None
        self._people_layout = None
        self.context_menu = tk.Menu(self, tearoff=False)
        self.loading = False
        self.explicit = bool(data.get('venues'))
        self.body = ttk.Frame(self)
        self.body.pack(fill='x')
        self.body.bind('<Configure>', self._layout_cards)
        ttk.Button(self, text='+ Add venue', style='Quiet.TButton', command=self.add_venue).pack(anchor='w', pady=(4, 8))
        self.load(data)

    @property
    def texts(self):
        return [card['text'] for card in self.cards]

    def load(self, data):
        self.loading = True
        self._card_layout = None
        self.explicit = bool(data.get('venues'))
        for card in self.cards:
            card['text'].destroy()
            card['frame'].destroy()
        self.cards = []
        for venue in schedule_venues(data):
            self._card(venue)
        self.loading = False
        self._sync_layout()

    def set_people_panel(self, panel):
        self.people_panel = panel
        self._sync_layout()

    def _sync_layout(self):
        multi = len(self.cards) > 1
        for card in self.cards:
            if multi or self.explicit:
                card["entry"].pack(fill="x", pady=(0, 6), before=card["text"].frame)
            else:
                card["entry"].pack_forget()
        people_layout = (multi, self.people_panel)
        if self.people_panel is not None and people_layout != self._people_layout:
            self._people_layout = people_layout
            self.master.columnconfigure(0, weight=1 if multi else 0)
            self.master.columnconfigure(1, weight=0 if multi else 1)
            self.master.rowconfigure(0, weight=0 if multi else 1)
            self.master.rowconfigure(1, weight=1 if multi else 0)
            self.grid_configure(row=0, column=0, columnspan=2 if multi else 1, sticky="new", padx=(0, 0 if multi else 12))
            self.people_panel.grid_configure(row=1 if multi else 0, column=0 if multi else 1,
                                             columnspan=2 if multi else 1, sticky="nsew")
        self._layout_cards()

    def _card(self, venue):
        index = len(self.cards)
        frame = ttk.LabelFrame(self.body, text='Open dates', padding=8)
        frame.grid(row=index // 3, column=index % 3, sticky='new', padx=(0, 8), pady=(0, 6))
        self.body.columnconfigure(index % 3, weight=1, uniform='venues')
        name = tk.StringVar(value=venue['name'])
        entry = ttk.Entry(frame, textvariable=name, width=18)
        entry.pack(fill='x', pady=(0, 6))
        text = ResizableNotes(frame, height=12, expanded_height=18, width=self.date_width, wrap='word', undo=True)
        text.pack(fill='x')
        text.insert('1.0', venue.get('open_dates', ''))
        text.edit_modified(False)
        card = dict(id=venue['id'], frame=frame, name=name, entry=entry, text=text)
        self.cards.append(card)
        name.trace_add('write', lambda *args: self._name_changed())
        text.bind('<<Modified>>', self._modified)
        for field in (entry, text):
            field.bind('<FocusOut>', self.commit, add=True)
            field.bind('<Command-Return>', self.commit)
            field.bind('<Control-Return>', self.commit)
        self._bind_venue_menu(frame, card)
        bind_scrolling = getattr(self.winfo_toplevel(), '_bind_scrolling', None)
        if bind_scrolling is not None:
            bind_scrolling(frame)
        return card

    def _bind_venue_menu(self, widget, card):
        for sequence in ('<Button-3>', '<Button-2>', '<Control-Button-1>'):
            widget.bind(sequence, lambda event, card=card: self._venue_menu(event, card))
        for child in widget.winfo_children():
            self._bind_venue_menu(child, card)

    def _venue_menu(self, event, card):
        menu = self.context_menu
        menu.delete(0, 'end')
        field = event.widget
        if isinstance(field, (tk.Text, tk.Entry, ttk.Entry)):
            for label, action in (('Cut', '<<Cut>>'), ('Copy', '<<Copy>>'), ('Paste', '<<Paste>>')):
                menu.add_command(label=label, command=lambda action=action: field.event_generate(action))
            menu.add_separator()
        menu.add_command(label='Delete venue', command=lambda: self.delete_venue(card),
                         state='normal' if len(self.cards) > 1 else 'disabled')
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return 'break'

    def delete_venue(self, card):
        if len(self.cards) <= 1 or card not in self.cards:
            return
        self.cards.remove(card)
        card['text'].destroy()
        card['frame'].destroy()
        self._sync_layout()
        self.changed()
        self.commit()

    def _layout_cards(self, event=None):
        # Empty weighted columns keep their old width when returning to one venue.
        columns = max(1, min(len(self.cards), 3, self.body.winfo_width() // 230))
        layout = (columns, tuple(card['id'] for card in self.cards))
        if layout == self._card_layout:
            return
        self._card_layout = layout
        for index in range(3):
            self.body.columnconfigure(index, weight=1 if index < columns else 0,
                                      uniform='venues' if index < columns else '')
        for index, card in enumerate(self.cards):
            card['frame'].grid_configure(row=index // columns, column=index % columns)

    def _name_changed(self):
        if not self.loading:
            self.explicit = True
            self.changed()

    def _modified(self, event):
        if event.widget.edit_modified():
            event.widget.edit_modified(False)
            if not self.loading:
                self.changed()

    def add_venue(self):
        self.explicit = True
        names = {card['name'].get().strip().casefold() for card in self.cards}
        number = len(self.cards) + 1
        while f'venue {number}' in names:
            number += 1
        card = self._card(dict(id=str(uuid.uuid4()), name=f'Venue {number}', open_dates=''))
        self._sync_layout()
        self.changed()
        self.commit()
        card['entry'].focus_set()
        card['entry'].selection_range(0, 'end')

    def snapshot(self):
        return [dict(id=card['id'], name=card['name'].get(),
                     open_dates=card['text'].get('1.0', 'end-1c')) for card in self.cards]

    def combined_text(self):
        venues = self.snapshot()
        if len(venues) == 1:
            return venues[0]['open_dates']
        try:
            return date_text(combined_dates(venues))
        except ValueError:
            return ', '.join(venue['open_dates'] for venue in venues if venue['open_dates'].strip())


class PerformerVenuesDialog(simpledialog.Dialog):
    def __init__(self, app, data, name):
        self.app, self.data, self.performer = app, data, name
        self.venues = schedule_venues(data)
        self.rule = venue_rule(data, name)
        self.detected_raw = None
        super().__init__(app, f'{name} · Venues and availability')

    def body(self, master):
        self.mode = tk.StringVar(value=self.rule['mode'])
        modes = ttk.Frame(master); modes.pack(fill='x', pady=(0, 10))
        ttk.Radiobutton(modes, text='Shared dates', value='shared', variable=self.mode, command=self._layout).pack(side='left')
        ttk.Radiobutton(modes, text='By venue', value='by_venue', variable=self.mode, command=self._layout).pack(side='left', padx=16)
        ttk.Label(master, text='Choose eligible venues. Shared dates apply to each checked venue.\n'
                  'Paste “Lobby: only Fridays” / “Pool: only Saturdays” to detect venues automatically.',
                  style='Muted.TLabel', wraplength=530).pack(anchor='w', pady=(0, 10))
        draft = next((d for d in self.data.get('availability_drafts', [])
                      if performer_key(d['name']) == performer_key(self.performer)), {})
        shared = draft.get('availability', performer_value(self.data, self.performer) or '')
        if self.rule['mode'] == 'by_venue':
            shared = performer_value(self.data, self.performer) or ''
        self.shared_panel = ttk.Frame(master)
        self.shared_panel.pack(fill='x')
        ttk.Label(self.shared_panel, text='Shared availability', style='Caption.TLabel').pack(anchor='w')
        self.shared = ScrolledText(self.shared_panel, height=4, width=58, wrap='word', undo=True)
        self.shared.pack(fill='x', pady=(4, 10)); self.shared.insert('1.0', shared)
        self.shared.bind('<FocusOut>', self._detect)
        self.controls = {}
        separate_seed = shared
        if self.rule['mode'] == 'shared' and any(re.search(re.escape(v['name']), shared, re.I) for v in self.venues):
            separate_seed = performer_value(self.data, self.performer) or ''
        for venue in self.venues:
            frame = ttk.Frame(master); frame.pack(fill='x', pady=3)
            selected = tk.BooleanVar(value=venue['id'] in self.rule['venues'])
            ttk.Checkbutton(frame, text=venue['name'], variable=selected, command=self._layout).pack(anchor='w')
            field = ScrolledText(frame, height=2, width=58, wrap='word', undo=True)
            field.insert('1.0', self.rule.get('raw_availability', {}).get(venue['id'], separate_seed))
            self.controls[venue['id']] = (selected, field)
        self._layout()
        self.app._bind_scrolling(master)
        return self.shared if self.mode.get() == 'shared' else next(iter(self.controls.values()))[1]

    def _layout(self):
        if self.mode.get() == 'shared':
            self.shared_panel.pack(fill='x', before=next(iter(self.controls.values()))[1].frame.master)
        else:
            self.shared_panel.pack_forget()
        for selected, field in self.controls.values():
            if self.mode.get() == 'by_venue':
                field.configure(state='normal' if selected.get() else 'disabled')
                field.pack(fill='x', pady=(4, 4))
            else:
                field.pack_forget()

    def _detect(self, event=None):
        if self.mode.get() != 'shared':
            return
        raw = self.shared.get('1.0', 'end-1c')
        if raw == self.detected_raw or not any(re.search(re.escape(v['name']), raw, re.I) for v in self.venues):
            return
        try:
            _, rule = format_venue_availability(self.performer, raw, self.venues, self.rule)
        except ValueError:
            return
        self.detected_raw = raw
        for vid, (selected, field) in self.controls.items():
            selected.set(vid in rule['venues'])
            if rule['mode'] == 'by_venue':
                field.configure(state='normal')
                field.delete('1.0', 'end'); field.insert('1.0', rule.get('raw_availability', {}).get(vid, ''))
        self.mode.set(rule['mode']); self._layout()

    def buttonbox(self):
        box = ttk.Frame(self, padding=12); box.pack(fill='x')
        ttk.Button(box, text='Save availability', style='Primary.TButton', command=self.ok).pack(side='right')
        ttk.Button(box, text='Cancel', command=self.cancel).pack(side='right', padx=8)
        self.bind('<Escape>', self.cancel)

    def validate(self):
        try:
            if self.mode.get() == 'shared':
                self._detect()
            selected = [vid for vid, (flag, _) in self.controls.items() if flag.get()]
            if self.mode.get() == 'shared':
                raw = self.shared.get('1.0', 'end-1c')
                if raw.strip():
                    result, _ = format_venue_availability(self.performer, raw, self.venues, dict(venues=selected))
                    dates = result.availability[self.performer]
                else:
                    dates = []
                rule = dict(mode='shared', venues=selected, availability={}, raw_availability={})
            else:
                formatted, originals, dates = {}, {}, []
                for venue in self.venues:
                    vid = venue['id']
                    if vid not in selected:
                        continue
                    text = self.controls[vid][1].get('1.0', 'end-1c')
                    available = parse_open_dates(venue['open_dates'])
                    if text.strip() and available:
                        result = format_inline(self.performer, text, available)
                        if self.performer not in result.availability:
                            raise ValueError(venue['name'] + ': ' + ' '.join(result.notes))
                        values = result.availability[self.performer]
                    else:
                        values = []
                    dates.extend(values); formatted[vid] = date_text(values); originals[vid] = text
                rule = dict(mode='by_venue', venues=selected, availability=formatted, raw_availability=originals)
                raw = '\n'.join(f'{v["name"]}: {originals[v["id"]]}' for v in self.venues if v['id'] in selected)
            self.result = dict(rule=rule, raw=raw, dates=sorted(set(dates)))
            return True
        except ValueError as error:
            messagebox.showerror('Check availability', str(error), parent=self)
            return False
