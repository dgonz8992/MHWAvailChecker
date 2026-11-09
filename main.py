"""Run this file to open the MHW scheduling application."""
import queue
import threading
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from tkinter.scrolledtext import ScrolledText
from scheduler import generate_schedule, alternate_schedule, parse_dates, parse_open_dates, infer_date_context
from availability_import import parse_import
from ai_availability import AIAvailabilityError, configured_model, convert_with_ai
from scrollable import ScrollableFrame
from campaigns import CampaignStore
from schedule_list import ScheduleList
from performer_editor import PerformerEditor
from inline_availability import (performer_key, performer_value, request_signature, format_inline,
                                 schedule_performers, sync_schedule_performers, editor_drafts)
from appearance import PALETTES, configure_appearance, normalize_mode
from resizable_notes import ResizableNotes
from confirmation_templates import DEFAULT_TEMPLATE, TEMPLATE_FIELDS, render_confirmation, render_schedule_template
from template_library import TemplateDialog


class AvailabilityApp(tk.Tk):
    def __init__(self, store=None):
        super().__init__()
        try:
            self.store = store if store is not None else CampaignStore()
            mode = normalize_mode(self.store.get_setting('appearance', 'Default'))
        except Exception as error:
            messagebox.showerror('Schedules could not be opened', str(error), parent=self)
            self.destroy()
            raise
        configure_appearance(self, mode)
        self.appearance_mode = tk.StringVar(value=mode)
        self.campaign_id = None
        self._loading = True
        self._dirty = False
        self._save_job = None
        self._template_job = None
        self.confirmation_overrides = {}
        self.confirmation_editors = {}
        self.title('MHW Scheduler')
        self.geometry('1180x820')
        self.minsize(520, 400)
        self.performers = []
        self.rows = []
        self._schedule_edit = None
        self.gap = tk.StringVar(value='7')
        self.ai_api_key = tk.StringVar(value='')
        self.ai_model = tk.StringVar(value=configured_model())
        self.status = tk.StringVar()
        self.totals = tk.StringVar()
        self.campaign_name = tk.StringVar()
        self.save_status = tk.StringVar()
        self._wheel_remainders = {}
        self._build_app_header()
        self._build_app_footer()
        self._build_ui()
        self._load_defaults()
        self._build_home()
        self._build_templates_page()
        self._loading = False
        self._show_home()
        self.gap.trace_add('write', self._invalidate)
        self.ai_model.trace_add('write', self._queue_save)
        self.protocol('WM_DELETE_WINDOW', self._close)
        self.bind_all('<Button-3>', self._copy_menu)
        if self.tk.call('tk', 'windowingsystem') == 'aqua':
            self.createcommand('tk::mac::Quit', self._close)
            self.bind_all('<Button-2>', self._copy_menu)
            self.bind_all('<Control-Button-1>', self._copy_menu)
        for modifier in self._copy_modifiers():
            self.bind_all(f'<{modifier}-a>', self._select_all)
        for sequence in ('<MouseWheel>', '<Shift-MouseWheel>', '<Button-4>', '<Button-5>'):
            self.bind_class('MHWScroll', sequence, self._scroll_wheel)
        self.bind_class('MHWScroll', '<Button-1>', self._click_outside_field)
        try:
            # Tk 9 emits these for precise trackpad movement separately from wheels.
            self.bind_class('MHWScroll', '<TouchpadScroll>', self._scroll_touchpad)
        except tk.TclError:
            pass  # Older Tk versions use MouseWheel for trackpads as well.
        self._bind_scrolling(self)

    def _build_app_header(self):
        header = ttk.Frame(self, padding=(20, 6))
        header.pack(fill='x')
        mark = Path(__file__).resolve().parent / 'logo' / 'MHW-mark.png'
        if mark.exists():
            self._brand_mark = tk.PhotoImage(file=str(mark)).subsample(3)
            ttk.Label(header, image=self._brand_mark).pack(side='left', padx=(0, 12))
        brand = ttk.Frame(header)
        brand.pack(side='left')
        ttk.Label(brand, text='MHW Scheduler', style='Brand.TLabel').pack(anchor='w')
        ttk.Separator(self, style='Accent.TSeparator').pack(fill='x')

    def _build_app_footer(self):
        self.appearance_footer = ttk.Frame(self)
        self.appearance_footer.pack(side='bottom', fill='x')
        ttk.Separator(self.appearance_footer).pack(fill='x')
        switch = ttk.Frame(self.appearance_footer, padding=(24, 10))
        switch.pack(fill='x')
        self.appearance_label = tk.StringVar(value=f'☀\ufe0e Appearance · {self.appearance_mode.get()} ▾')
        self.appearance_button = ttk.Menubutton(switch, textvariable=self.appearance_label,
                                               direction='above', style='Appearance.TMenubutton')
        self.appearance_button.pack(side='left')
        self.appearance_menu = tk.Menu(self.appearance_button, tearoff=False)
        self.appearance_button.configure(menu=self.appearance_menu)
        for mode in PALETTES:
            self.appearance_menu.add_radiobutton(label=mode, value=mode, variable=self.appearance_mode,
                                                command=lambda value=mode: self._change_appearance(value))

    def _change_appearance(self, mode):
        mode = normalize_mode(mode)
        try:
            self.store.set_setting('appearance', mode)
        except Exception as error:
            self.appearance_mode.set(self._appearance_name)
            messagebox.showerror('Appearance could not be saved', str(error), parent=self)
            return
        configure_appearance(self, mode)
        self.appearance_mode.set(mode)
        self.appearance_label.set(f'☀\ufe0e Appearance · {mode} ▾')

    def _build_ui(self):
        self.page = ScrollableFrame(self)
        self.page.pack(fill='both', expand=True)
        self.page_canvas = self.page.canvas
        outer = self.page.content
        navigation = ttk.Frame(outer)
        navigation.pack(fill='x', pady=(0, 12))
        ttk.Button(navigation, text='← All schedules', style='Quiet.TButton', command=self._show_home).pack(side='left')
        ttk.Button(navigation, text='Rename schedule…', style='Quiet.TButton', command=self._rename_active).pack(side='left', padx=8)
        ttk.Button(navigation, text='Save now', style='Success.TButton', command=self._save_campaign).pack(side='left')
        ttk.Label(navigation, textvariable=self.save_status, style='Muted.TLabel').pack(side='right')
        ttk.Label(outer, textvariable=self.campaign_name, style='Title.TLabel').pack(anchor='w')
        ttk.Label(outer, text='Dates, availability, and bookings in one place.', style='Muted.TLabel').pack(anchor='w', pady=(4, 12))
        organization = ttk.LabelFrame(outer, text='Schedule notes', padding=16)
        organization.pack(fill='x', pady=(0, 12))
        self.notes_text = ResizableNotes(organization, height=4, width=60, wrap='word', undo=True)
        self.notes_text.pack(fill='x', pady=(4, 0))
        self.notes_text.bind('<<Modified>>', self._notes_changed)
        self.notes_import = self._template_import_button(self.notes_text.tools,
                           lambda body: self._import_notes_template(self.notes_text, body), self.notes_text)
        self.notes_import.pack(side='right', pady=(0, 4))
        ttk.Label(outer, text='Use M/D/YYYY for open dates. Paste availability with the importer or enter dates below.', style='Muted.TLabel').pack(anchor='w', pady=(0, 8))
        inputs = ttk.Frame(outer)
        inputs.pack(fill='both', expand=True)
        inputs.columnconfigure(1, weight=1)
        inputs.rowconfigure(0, weight=1)
        dates_frame = ttk.LabelFrame(inputs, text='Open dates', padding=16)
        dates_frame.grid(row=0, column=0, sticky='nsew', padx=(0, 10))
        self.dates_text = ScrolledText(dates_frame, width=16, height=12, wrap='word', undo=True)
        self.dates_text.pack(fill='both', expand=True)
        self.dates_text.bind('<<Modified>>', self._text_changed)
        ttk.Button(dates_frame, text='Copy dates', command=lambda: self._copy_text(self.dates_text.get('1.0', 'end-1c'))).pack(anchor='w', pady=(6, 0))
        people_frame = ttk.LabelFrame(inputs, text='Performer availability', padding=16)
        people_frame.grid(row=0, column=1, sticky='nsew')
        people_toolbar = ttk.Frame(people_frame)
        people_toolbar.pack(fill='x', pady=(0, 6))
        ttk.Button(people_toolbar, text='Add performer…', command=self._add_performer).pack(side='left')
        ttk.Button(people_toolbar, text='Import availability…', command=self._import_availability).pack(side='left', padx=8)
        ttk.Button(people_toolbar, text='Copy availability', command=self._copy_availability).pack(side='left')
        canvas_frame = ttk.Frame(people_frame)
        canvas_frame.pack(fill='both', expand=True)
        self.canvas = tk.Canvas(canvas_frame, highlightthickness=0, height=180, yscrollincrement=20)
        scroll = ttk.Scrollbar(canvas_frame, orient='vertical', command=self.canvas.yview)
        scroll.pack(side='right', fill='y')
        self.canvas.pack(side='left', fill='both', expand=True)
        self.canvas.configure(yscrollcommand=scroll.set)
        self.people = ttk.Frame(self.canvas)
        window = self.canvas.create_window((0, 0), window=self.people, anchor='nw')
        self.people.bind('<Configure>', lambda event: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>', lambda event: self.canvas.itemconfigure(window, width=event.width))
        results = ttk.LabelFrame(outer, text='Generated schedule', padding=16)
        results.pack(fill='both', expand=True, pady=(12, 0))
        toolbar = ttk.Frame(results)
        toolbar.pack(fill='x', pady=(0, 8))
        ttk.Button(toolbar, text='Generate schedule', style='Success.TButton', command=self._generate).pack(side='left', padx=(0, 8))
        self.alternate_button = ttk.Button(toolbar, text='Try another arrangement',
                                          command=self._try_another_arrangement, state='disabled')
        self.alternate_button.pack(side='left', padx=(0, 18))
        ttk.Label(toolbar, text='Minimum days between gigs').pack(side='left', padx=(0, 5))
        ttk.Entry(toolbar, textvariable=self.gap, width=4).pack(side='left')
        copybar = ttk.Frame(results)
        copybar.pack(fill='x', pady=(0, 8))
        ttk.Button(copybar, text='Copy schedule', style='Quiet.TButton', command=self._copy_schedule).pack(side='left', padx=(0, 6))
        ttk.Button(copybar, text='Copy selected', style='Quiet.TButton', command=lambda: self._copy_schedule(selected_only=True)).pack(side='left')
        ttk.Button(copybar, text='Copy totals', style='Quiet.TButton', command=lambda: self._copy_text(self.totals.get())).pack(side='left', padx=6)
        self.arrangement_status = tk.StringVar()
        ttk.Label(copybar, textvariable=self.arrangement_status, style='Muted.TLabel',
                  wraplength=360).pack(side='left', padx=(12, 0))
        table_frame = ttk.Frame(results)
        table_frame.pack(fill='both', expand=True)
        self.table = ttk.Treeview(table_frame, columns=('date', 'performer', 'day'), show='headings', height=8)
        for key, title, width in [('date', 'Date', 120), ('performer', 'Performer', 350), ('day', 'Day', 120)]:
            self.table.heading(key, text=title)
            self.table.column(key, width=width)
        scroll = ttk.Scrollbar(table_frame, orient='vertical', command=lambda *args: self._scroll_schedule_table('y', *args))
        self.table.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        table_horizontal = ttk.Scrollbar(table_frame, orient='horizontal', command=lambda *args: self._scroll_schedule_table('x', *args))
        self.table.configure(xscrollcommand=table_horizontal.set)
        table_horizontal.pack(side='bottom', fill='x')
        self.table.pack(fill='both', expand=True)
        self.table.bind('<Double-1>', self._edit_schedule_cell)
        self.table.bind('<Return>', self._edit_schedule_cell)
        self.table.bind('<Configure>', lambda event: self._finish_schedule_edit())
        ttk.Label(results, text='Double-click a performer to change the booking, or select a row and press Enter. '
                  'Type any name; leave blank to clear. Manual edits override scheduling rules.',
                  style='Muted.TLabel', wraplength=950).pack(anchor='w', pady=(6, 0))
        for modifier in self._copy_modifiers():
            self.table.bind(f'<{modifier}-c>', lambda event: self._copy_schedule(selected_only=bool(self.table.selection())))
        ttk.Label(results, textvariable=self.totals, wraplength=950).pack(anchor='w', pady=(8, 0))
        names = ttk.LabelFrame(outer, text='Names in schedule order', padding=16)
        names.pack(fill='both', expand=True, pady=(12, 0))
        names_toolbar = ttk.Frame(names)
        names_toolbar.pack(fill='x', pady=(0, 8))
        ttk.Button(names_toolbar, text='Copy names', style='Quiet.TButton', command=self._copy_names).pack(side='left')
        ttk.Button(names_toolbar, text='Copy selected names', style='Quiet.TButton', command=lambda: self._copy_names(True)).pack(side='left', padx=8)
        ttk.Label(names_toolbar, text='One name per date · Blank rows are unfilled.', style='Muted.TLabel').pack(side='left')
        names_frame = ttk.Frame(names)
        names_frame.pack(fill='both', expand=True)
        self.names_table = ttk.Treeview(names_frame, columns=('performer',), show='headings', height=6)
        self.names_table.heading('performer', text='Performer')
        self.names_table.column('performer', width=500)
        names_scroll = ttk.Scrollbar(names_frame, orient='vertical', command=self.names_table.yview)
        self.names_table.configure(yscrollcommand=names_scroll.set)
        names_scroll.pack(side='right', fill='y')
        names_horizontal = ttk.Scrollbar(names_frame, orient='horizontal', command=self.names_table.xview)
        self.names_table.configure(xscrollcommand=names_horizontal.set)
        names_horizontal.pack(side='bottom', fill='x')
        self.names_table.pack(fill='both', expand=True)
        for modifier in self._copy_modifiers():
            self.names_table.bind(f'<{modifier}-c>', lambda event: self._copy_names(bool(self.names_table.selection())))
        template_panel = ttk.LabelFrame(outer, text='Confirmation template', padding=16)
        template_panel.pack(fill='x', pady=(12, 0))
        template_tools = ttk.Frame(template_panel)
        template_tools.pack(fill='x', pady=(0, 8))
        ttk.Label(template_tools, text='Saved with this schedule · Scripts update as you type',
                  style='Muted.TLabel').pack(side='left')
        self.template_insert = ttk.Menubutton(template_tools, text='Insert field ▾')
        self.template_insert.pack(side='right')
        self.confirmation_import = self._template_import_button(template_tools, self._import_confirmation_template)
        self.confirmation_import.pack(side='right', padx=(0, 8))
        field_menu = tk.Menu(self.template_insert, tearoff=False)
        self.template_insert.configure(menu=field_menu)
        for token, description in TEMPLATE_FIELDS:
            field_menu.add_command(label=f'{token} — {description}', command=lambda value=token: self._insert_template_field(value))
        self.template_text = ScrolledText(template_panel, height=4, width=60, wrap='word', undo=True)
        self.template_text.pack(fill='x')
        self.template_text.insert('1.0', DEFAULT_TEMPLATE)
        self.template_text.edit_modified(False)
        self.template_text.bind('<<Modified>>', self._template_changed)
        ttk.Label(template_panel, text='@performer  Name     @pdates  Confirmed dates     @dates  Open dates\n'
                  '@count  Gig count     @schedule  Schedule name     @notes  Notes',
                  style='Muted.TLabel', wraplength=850).pack(anchor='w', pady=(8, 0))
        ttk.Button(template_panel, text='Restore default template', style='Quiet.TButton',
                   command=self._reset_template).pack(anchor='w', pady=(6, 0))
        ttk.Label(template_panel, text='Each script below is editable and saves automatically. '
                  'Edited scripts stay as written; Use template restores automatic wording and dates.',
                  style='Muted.TLabel', wraplength=850).pack(anchor='w', pady=(8, 0))
        self.confirmations = ttk.LabelFrame(outer, text='Confirmation scripts', padding=16)
        self.confirmations.pack(fill='both', expand=True, pady=(12, 0))
        ttk.Label(outer, textvariable=self.status, wraplength=1000, style='Muted.TLabel').pack(anchor='w', pady=(8, 0))

    def _build_home(self):
        self.active_folder = None
        saved_sort = self.store.get_setting('schedule_sort', 'None')
        self.schedule_sort = tk.StringVar(value=saved_sort if saved_sort in ('None', 'Name', 'Date added', 'Last updated') else 'None')
        self.sort_reverse = tk.BooleanVar(value=self.store.get_setting('schedule_sort_reverse', '0') == '1')
        self.sort_label = tk.StringVar(value=f'Sort: {self.schedule_sort.get()} ▾')
        self.home_notes = None
        self.home_notes_status = tk.StringVar()
        self._home_notes_id = None
        self._home_notes_dirty = False
        self._home_notes_job = None
        self._home_notes_loading = False
        self._selecting_notes = False
        self._folder_drag = None
        self.home = ttk.Frame(self, padding=(16, 8), style='Workspace.TFrame')
        body = ttk.Panedwindow(self.home, orient='horizontal')
        body.pack(fill='both', expand=True)
        sidebar = ttk.Frame(body, padding=(14, 12, 14, 12), style='Sidebar.TFrame')
        body.add(sidebar, weight=0)
        self.templates_button = ttk.Button(sidebar, text='Templates →', style='Sidebar.TButton', command=self._show_templates)
        self.templates_button.pack(fill='x', pady=(0, 12))
        ttk.Separator(sidebar).pack(fill='x', pady=(0, 12))
        ttk.Label(sidebar, text='YOUR LIBRARY', style='Sidebar.TLabel').pack(anchor='w', pady=(0, 8))
        ttk.Label(sidebar, text='Drag folders to reorder', style='SidebarHint.TLabel').pack(anchor='w', pady=(0, 8))
        self.folder_list = ttk.Treeview(sidebar, show='tree', selectmode='browse', height=10, style='Folders.Treeview')
        self.folder_list.column('#0', width=160, minwidth=130)
        self.folder_list.pack(fill='both', expand=True)
        self.folder_list.bind('<<TreeviewSelect>>', self._folder_selected)
        self.folder_list.bind('<ButtonPress-1>', self._folder_drag_start)
        self.folder_list.bind('<B1-Motion>', self._folder_drag_motion)
        self.folder_list.bind('<ButtonRelease-1>', self._folder_drag_end)
        self.folder_list.bind('<Escape>', self._folder_drag_cancel)
        self.folder_list.bind('<Button-3>', self._folder_context_menu)
        if self.tk.call('tk', 'windowingsystem') == 'aqua':
            self.folder_list.bind('<Button-2>', self._folder_context_menu)
            self.folder_list.bind('<Control-Button-1>', self._folder_context_menu)
        ttk.Button(sidebar, text='+ New folder', style='Sidebar.TButton', command=self._new_folder).pack(fill='x', pady=(8, 4))
        ttk.Button(sidebar, text='Rename folder…', style='Sidebar.TButton', command=self._rename_folder).pack(fill='x')
        content = ttk.Frame(body, padding=(18, 8, 16, 8))
        body.add(content, weight=1)
        self.folder_title = tk.StringVar(value='All schedules')
        toolbar = ttk.Frame(content)
        toolbar.pack(fill='x', pady=(0, 8))
        ttk.Label(toolbar, textvariable=self.folder_title, width=14,
                  style='LibraryTitle.TLabel').pack(side='left', padx=(0, 14))
        self.schedule_search = tk.StringVar()
        ttk.Label(toolbar, text='Search', style='Muted.TLabel').pack(side='left', padx=(0, 6))
        self.search_entry = ttk.Entry(toolbar, textvariable=self.schedule_search, width=12,
                                      style='Compact.TEntry')
        self.search_entry.pack(side='left', fill='x', expand=True, padx=(0, 4))
        ttk.Button(toolbar, text='Clear', style='Quiet.TButton', command=self._clear_filters).pack(side='left', padx=(0, 8))
        ttk.Button(toolbar, text='+ New schedule', style='Compact.Primary.TButton',
                   command=self._new_campaign).pack(side='right')
        self.sort_button = ttk.Menubutton(toolbar, textvariable=self.sort_label, style='Appearance.TMenubutton')
        self.sort_button.pack(side='right', padx=(0, 8))
        self.sort_menu = tk.Menu(self.sort_button, tearoff=False)
        self.sort_button.configure(menu=self.sort_menu)
        for option in ('None', 'Name', 'Date added', 'Last updated'):
            self.sort_menu.add_radiobutton(label=option, variable=self.schedule_sort, value=option, command=self._sort_changed)
        self.sort_menu.add_separator()
        self.sort_menu.add_checkbutton(label='Reverse order', variable=self.sort_reverse, command=self._sort_changed)
        self.sort_menu.entryconfigure(5, state='disabled' if self.schedule_sort.get() == 'None' else 'normal')
        self.schedule_search.trace_add('write', self._filter_changed)
        headings = ttk.Frame(content, padding=(60, 2, 4, 2))
        headings.pack(fill='x')
        headings.columnconfigure(0, weight=2, minsize=170)
        headings.columnconfigure(1, weight=3, minsize=150)
        ttk.Label(headings, text='SCHEDULE', width=25, style='Caption.TLabel').grid(row=0, column=0, sticky='w')
        ttk.Label(headings, text='NOTES', width=30, style='Caption.TLabel').grid(row=0, column=1, sticky='w')
        ttk.Label(headings, text='LAST SAVED', width=19, style='Caption.TLabel').grid(row=0, column=2, sticky='e')
        ttk.Separator(content, orient='horizontal').pack(fill='x')
        self.campaign_list = ScheduleList(content, on_context=self._schedule_context_menu, on_expand=self._expand_performers,
                                          on_edit_notes=self._edit_inline_notes, expansion_height=self._expansion_height)
        self.campaign_list.pack(fill='both', expand=True)
        self.campaign_list.bind('<<OpenSchedule>>', self._open_selected)
        self.campaign_list.bind('<<ScheduleSelected>>', self._home_selection_changed)
        self.home_hint = tk.StringVar()
        ttk.Label(content, textvariable=self.home_hint, wraplength=650, style='Muted.TLabel').pack(anchor='w', pady=(6, 8))
    def _build_templates_page(self):
        self.templates_page = ttk.Frame(self, padding=24)
        ttk.Button(self.templates_page, text='← All schedules', style='Quiet.TButton',
                   command=self._show_home).pack(anchor='w', pady=(0, 16))
        ttk.Label(self.templates_page, text='Templates', style='Title.TLabel').pack(anchor='w')
        ttk.Label(self.templates_page, text='Reusable notes and confirmation scripts for all your schedules.',
                  style='Muted.TLabel', wraplength=450).pack(anchor='w', pady=(4, 18))
        actions = ttk.Frame(self.templates_page)
        actions.pack(fill='x', pady=(0, 12))
        ttk.Button(actions, text='+ New template', style='Primary.TButton', command=self._new_saved_template).pack(side='left')
        ttk.Button(actions, text='Edit', command=self._edit_saved_template).pack(side='left', padx=8)
        ttk.Button(actions, text='Delete', style='Quiet.TButton', command=self._delete_saved_template).pack(side='left')
        listing = ttk.Frame(self.templates_page)
        listing.pack(fill='both', expand=True)
        self.template_list = ttk.Treeview(listing, columns=('preview',), show='tree headings', selectmode='browse')
        self.template_list.heading('#0', text='NAME')
        self.template_list.heading('preview', text='TEMPLATE PREVIEW')
        self.template_list.column('#0', width=220, minwidth=120)
        self.template_list.column('preview', width=500, minwidth=200)
        vertical = ttk.Scrollbar(listing, orient='vertical', command=self.template_list.yview)
        vertical.pack(side='right', fill='y')
        horizontal = ttk.Scrollbar(listing, orient='horizontal', command=self.template_list.xview)
        horizontal.pack(side='bottom', fill='x')
        self.template_list.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.template_list.pack(fill='both', expand=True)
        self.template_list.bind('<Double-1>', lambda event: self._edit_saved_template())
        self.template_list.bind('<Return>', lambda event: self._edit_saved_template())
        self.templates_status = tk.StringVar()
        ttk.Label(self.templates_page, textvariable=self.templates_status, style='Muted.TLabel',
                  wraplength=450).pack(anchor='w', pady=(12, 0))
        self._refresh_templates()

    def _show_templates(self):
        if not self._flush_inline_editors() or not self._finish_inline_notes() or not self._save_campaign():
            return
        try:
            self._refresh_templates()
        except Exception as error:
            messagebox.showerror('Templates could not be loaded', str(error), parent=self)
            return
        self.campaign_id = None
        self.home.pack_forget()
        self.page.pack_forget()
        self.templates_page.pack(fill='both', expand=True)
        self.title('Templates — MHW Scheduler')

    def _refresh_templates(self, selected=None):
        selected = selected or next(iter(self.template_list.selection()), None)
        templates = self.store.list_templates()
        self.template_list.delete(*self.template_list.get_children())
        for template in templates:
            preview = ' '.join(template['body'].split())
            self.template_list.insert('', 'end', iid=template['id'], text=template['name'],
                                      values=(preview[:147] + '…' if len(preview) > 150 else preview,))
        if selected and self.template_list.exists(selected):
            self.template_list.selection_set(selected)
            self.template_list.see(selected)
        self.templates_status.set(f'{len(templates)} saved templates · Double-click to edit'
                                  if templates else 'Create your first template, then import it from notes or confirmations.')

    def _new_saved_template(self):
        dialog = TemplateDialog(self)
        if dialog.result:
            self._refresh_templates(dialog.result)

    def _edit_saved_template(self):
        selected = self.template_list.selection()
        if not selected:
            return
        try:
            dialog = TemplateDialog(self, self.store.load_template(selected[0]))
            if dialog.result:
                self._refresh_templates(dialog.result)
        except Exception as error:
            messagebox.showerror('Template could not be opened', str(error), parent=self)

    def _delete_saved_template(self):
        selected = self.template_list.selection()
        if not selected:
            return
        try:
            template = self.store.load_template(selected[0])
            if not messagebox.askyesno('Delete template?', f'Delete “{template["name"]}”?\n\n'
                                       'Text already imported into schedules will stay.', parent=self):
                return
            self.store.delete_template(template['id'])
            self._refresh_templates()
        except Exception as error:
            messagebox.showerror('Template could not be deleted', str(error), parent=self)

    def _template_import_button(self, parent, on_import, notes=None):
        button = ttk.Menubutton(parent, text='Import template ▾', style='Quiet.TMenubutton')
        menu = tk.Menu(button, tearoff=False)
        button.configure(menu=menu)
        button.template_menu = menu
        menu.configure(postcommand=lambda: self._populate_template_import(menu, on_import, notes))
        if notes is not None:
            menu.bind('<Unmap>', lambda event: self._notes_import_dismissed(notes))
        return button

    def _populate_template_import(self, menu, on_import, notes=None):
        menu.delete(0, 'end')
        try:
            templates = self.store.list_templates()
        except Exception as error:
            messagebox.showerror('Templates could not be loaded', str(error), parent=self)
            return
        if notes is not None:
            notes._menu_open = True
        for template in templates:
            menu.add_command(label=template['name'],
                             command=lambda tid=template['id']: self._load_template_for_import(tid, on_import))
        if not templates:
            menu.add_command(label='No saved templates yet', state='disabled')
        menu.add_separator()
        menu.add_command(label='+ New template…', command=self._new_saved_template)

    def _notes_import_dismissed(self, notes):
        if not notes.winfo_exists():
            return
        notes._menu_open = False
        notes._blurred()
        if self.home_notes is notes:
            self.after_idle(lambda: self._finish_notes_on_blur(notes))

    def _load_template_for_import(self, template_id, on_import):
        try:
            on_import(self.store.load_template(template_id)['body'])
        except Exception as error:
            messagebox.showerror('Template could not be imported', str(error), parent=self)

    def _import_notes_template(self, notes, body):
        if not notes.winfo_exists():
            return
        notes._menu_open = False
        existing = notes.get('1.0', 'end-1c')
        if notes is self.home_notes:
            if not self._flush_inline_editors():
                return
            campaign = self.store.load(self._home_notes_id)
            data = campaign['data']
            open_text = data.get('open_dates', '')
            schedule_name = campaign['name']
            booked_count = sum(row.get('performer') is not None for row in data.get('rows', []))
        else:
            self._flush_input_changes()
            open_text = self.dates_text.get('1.0', 'end-1c')
            schedule_name = self.campaign_name.get()
            booked_count = sum(name is not None for _, name in self.rows)
        # Resolve before editing so a malformed date cannot cause a partial import.
        try:
            open_dates = parse_open_dates(open_text)
        except ValueError:
            if '@dates' in body:
                raise
            open_dates = []
        body = render_schedule_template(body, open_dates=open_dates,
                                        schedule=schedule_name, notes=existing, booked_count=booked_count)
        notes.edit_separator()
        if existing and not existing.endswith('\n'):
            notes.insert('end-1c', '\n')
        notes.insert('end-1c', body)
        notes.edit_separator()
        notes.focus_set()
        notes._expand()
        if notes is self.home_notes:
            self._home_notes_changed(None)
            self._save_home_notes()
        else:
            self._notes_changed()
            self._save_campaign()

    def _import_confirmation_template(self, body):
        self.template_text.edit_separator()
        self.template_text.delete('1.0', 'end')
        self.template_text.insert('1.0', body)
        self.template_text.edit_separator()
        self._template_changed(None)
        self._cancel_template_refresh()
        self._show_confirmations()
        self._save_campaign()

    def _expand_performers(self, schedule_id, parent):
        return PerformerEditor(parent, self, schedule_id)

    def _expansion_height(self, schedule_id):
        query = self.schedule_search.get().strip().casefold()
        drafts = editor_drafts(self.store.load(schedule_id)['data'])
        count = sum(not query or query in row['name'].casefold() for row in drafts)
        return max(320, 150 + 70 * count)

    def _flush_inline_editors(self):
        return self.campaign_list.flush_editors()

    def _inline_editor(self, schedule_id):
        data = self.campaign_list._items.get(schedule_id)
        if data and data['editor'] is None and schedule_id in self.campaign_list._expanded:
            return self.campaign_list.ensure_editor(schedule_id)
        return data.get('editor') if data else None

    def _inline_status(self, schedule_id, row_id, status, signature=None):
        try:
            self.store.set_inline_status(schedule_id, row_id, status, signature)
            editor = self._inline_editor(schedule_id)
            if editor is not None:
                editor.refresh_row(row_id)
        except ValueError:
            pass  # The schedule or draft may have been deleted during conversion.
        except Exception as error:
            messagebox.showerror('Conversion status could not be saved', str(error), parent=self)

    def _convert_inline(self, schedule_id, row_id, retry=False):
        editor = self._inline_editor(schedule_id)
        if editor is not None and not editor.flush():
            return
        try:
            data = self.store.load(schedule_id)['data']
            draft = next((row for row in data.get('availability_drafts', []) if row['id'] == row_id), None)
            if draft is None or not draft['name'].strip() or not draft['availability'].strip():
                return
            signature = request_signature(draft, data)
            if not retry and draft.get('last_applied') == signature and performer_value(data, draft['name']) == draft.get('formatted'):
                self._inline_status(schedule_id, row_id, 'Updated · ' + (draft['formatted'] or 'No matching open dates'), signature)
                return
            dates = parse_open_dates(data.get('open_dates', ''))
            if not dates:
                self._inline_status(schedule_id, row_id, 'Set this schedule’s open dates first.')
                return
            snapshot = dict(name=draft['name'].strip(), availability=draft['availability'].strip(),
                            signature=signature, previous_availability=performer_value(data, draft['name']), dates=dates)
            result = format_inline(snapshot['name'], snapshot['availability'], dates)
            if snapshot['name'] not in result.availability:
                self._inline_status(schedule_id, row_id, 'Needs review · ' +
                                    (' '.join(result.notes) or 'Clarify the availability and retry.'), signature)
                return
            if self.campaign_id == schedule_id and not self._save_campaign():
                return
            confirmed = result.availability[snapshot['name']]
            applied = self.store.apply_inline_result(schedule_id, row_id, snapshot, confirmed, '\n'.join(result.notes))
            if applied and self.campaign_id == schedule_id:
                self._apply_availability_import({snapshot['name']: confirmed})
            if not applied:
                self._inline_status(schedule_id, row_id, 'Schedule changed. Retry formatting.')
            if editor is not None:
                editor.refresh_row(row_id)
        except Exception as error:
            self._inline_status(schedule_id, row_id, str(error) if isinstance(error, (ValueError, OSError))
                                else 'Could not format availability. Retry formatting.')

    def _refresh_folders(self):
        folders = self.store.list_folders()
        self.folder_list.delete(*self.folder_list.get_children())
        self.folder_list.insert('', 'end', iid='all', text='All schedules')
        for folder in folders:
            self.folder_list.insert('', 'end', iid=folder['id'], text='  ' + folder['name'])
        selected = self.active_folder or 'all'
        if not self.folder_list.exists(selected):
            self.active_folder = None
            selected = 'all'
        self.folder_list.selection_set(selected)
        self.folder_title.set(self.folder_list.item(selected, 'text').strip())

    def _refresh_campaigns(self):
        if not self._flush_inline_editors() or not self._finish_inline_notes():
            return False
        selected = self.campaign_list.selection()
        self._refresh_folders()
        campaigns = self.store.list_campaigns(self.schedule_search.get(), self.active_folder,
                                              self.schedule_sort.get(), self.sort_reverse.get())
        self.campaign_list.delete(*self.campaign_list.get_children())
        for campaign in campaigns:
            updated = datetime.fromisoformat(campaign['updated_at']).astimezone().strftime('%m/%d/%Y %I:%M %p')
            notes = ' '.join(campaign['notes'].split())
            if len(notes) > 90:
                notes = notes[:87] + '…'
            self.campaign_list.insert('', 'end', iid=campaign['id'], values=(campaign['name'], notes, updated))
        self.campaign_list.selection_set([item for item in selected if self.campaign_list.exists(item)])
        self._home_selection_changed(force=True)
        count = len(campaigns)
        noun = 'schedule' if count == 1 else 'schedules'
        self.home_hint.set(f'{count} {noun} · Double-click a name to open · Click notes to edit · Right-click for actions'
                           if campaigns else 'Create a schedule to get started, or move one into this folder.')
        self.campaign_list.show_empty('No schedules found' if self.schedule_search.get().strip() else 'A fresh start',
                                      'Try another search.' if self.schedule_search.get().strip() else 'Your schedules will appear here.')
        self._bind_scrolling(self.campaign_list)
        return True

    def _folder_drag_start(self, event):
        folder_id = self.folder_list.identify_row(event.y)
        self._folder_drag = dict(id=folder_id, y=event.y, moved=False) if folder_id and folder_id != 'all' else None

    def _folder_drag_motion(self, event):
        drag = self._folder_drag
        if drag is None or not self.folder_list.exists(drag['id']):
            return 'break'
        if not drag['moved'] and abs(event.y - drag['y']) < 5:
            return 'break'
        drag['moved'] = True
        if event.y < 18:
            self.folder_list.yview_scroll(-1, 'units')
        elif event.y > self.folder_list.winfo_height() - 18:
            self.folder_list.yview_scroll(1, 'units')
        target = self.folder_list.identify_row(event.y)
        if target == drag['id']:
            return 'break'
        siblings = [item for item in self.folder_list.get_children() if item != drag['id']]
        if target == 'all' or event.y < 0:
            position = 1
        elif target:
            _, y, _, height = self.folder_list.bbox(target)
            position = siblings.index(target) + (event.y >= y + height / 2)
        else:
            position = len(siblings)
        self.folder_list.move(drag['id'], '', max(1, position))
        return 'break'

    def _folder_drag_end(self, event):
        drag, self._folder_drag = self._folder_drag, None
        if drag is None or not drag['moved']:
            return
        try:
            self.store.reorder_folders([item for item in self.folder_list.get_children() if item != 'all'])
        except Exception as error:
            self._refresh_folders()
            messagebox.showerror('Folder order could not be saved', str(error), parent=self)
        return 'break'

    def _folder_drag_cancel(self, event=None):
        if self._folder_drag is not None:
            self._folder_drag = None
            self._refresh_folders()
            return 'break'

    def _folder_selected(self, event=None):
        selected = self.folder_list.selection()
        if not selected:
            return
        folder_id = None if selected[0] == 'all' else selected[0]
        if folder_id == self.active_folder:
            return
        if not self._save_home_notes():
            self._refresh_folders()
            return
        self.active_folder = folder_id
        self._filter_changed()

    def _new_folder(self):
        name = simpledialog.askstring('New folder', 'Folder name:', parent=self)
        if name is None or not self._save_home_notes():
            return
        try:
            self.active_folder = self.store.create_folder(name)
            self.schedule_search.set('')
        except Exception as error:
            messagebox.showerror('Could not create folder', str(error), parent=self)

    def _rename_folder(self, folder_id=None):
        folder_id = self.active_folder if folder_id is None else folder_id
        if not folder_id or folder_id == 'all':
            messagebox.showinfo('Choose a folder', 'Select a folder you created to rename it.', parent=self)
            return
        current = self.folder_list.item(folder_id, 'text').strip()
        name = simpledialog.askstring('Rename folder', 'Folder name:', initialvalue=current, parent=self)
        if name is None or not self._save_home_notes():
            return
        try:
            self.store.rename_folder(folder_id, name)
            self._refresh_campaigns()
        except Exception as error:
            messagebox.showerror('Could not rename folder', str(error), parent=self)

    def _folder_context_menu(self, event):
        folder_id = self.folder_list.identify_row(event.y)
        if not folder_id or not self._save_home_notes():
            return 'break'
        menu = getattr(self, '_active_copy_menu', None)
        if menu is not None and menu.winfo_exists():
            menu.destroy()
        menu = tk.Menu(self, tearoff=False)
        self._active_copy_menu = menu
        editable = 'disabled' if folder_id == 'all' else 'normal'
        menu.add_command(label='Open', command=lambda: self._open_folder(folder_id))
        menu.add_command(label='Rename…', state=editable, command=lambda: self._rename_folder(folder_id))
        menu.add_separator()
        menu.add_command(label='Delete folder…', state=editable, command=lambda: self._delete_folder(folder_id))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return 'break'

    def _open_folder(self, folder_id):
        self.folder_list.selection_set(folder_id)
        self._folder_selected()

    def _delete_folder(self, folder_id):
        if folder_id == 'all' or not folder_id or not self._save_home_notes():
            return
        name = self.folder_list.item(folder_id, 'text').strip()
        if not messagebox.askyesno('Delete folder?',
                                   f'Delete “{name}”? Its schedules will remain in All schedules.', parent=self):
            return
        try:
            self.store.delete_folder(folder_id)
            if self.active_folder == folder_id:
                self.active_folder = None
            self._refresh_campaigns()
        except Exception as error:
            messagebox.showerror('Could not delete folder', str(error), parent=self)

    def _move_selected(self, campaign_ids=None):
        selected = tuple(campaign_ids) if campaign_ids is not None else self.campaign_list.selection()
        if not selected or not self._save_home_notes():
            return
        folders = self.store.list_folders()
        dialog = tk.Toplevel(self)
        dialog.title('Move schedules to folder')
        dialog.transient(self)
        outer = ttk.Frame(dialog, padding=16)
        outer.pack(fill='both', expand=True)
        ttk.Label(outer, text=f'Move {len(selected)} schedule(s) to:').pack(anchor='w')
        chooser = ttk.Combobox(outer, state='readonly', values=['No folder'] + [folder['name'] for folder in folders], width=32)
        chooser.pack(fill='x', pady=10)
        chooser.current(0)
        def move():
            try:
                folder_id = None if chooser.current() == 0 else folders[chooser.current() - 1]['id']
                self.store.move_to_folder(selected, folder_id)
                dialog.destroy()
                self._refresh_campaigns()
            except Exception as error:
                messagebox.showerror('Could not move schedules', str(error), parent=dialog)
        buttons = ttk.Frame(outer)
        buttons.pack(fill='x')
        ttk.Button(buttons, text='Move', command=move).pack(side='right')
        ttk.Button(buttons, text='Cancel', command=dialog.destroy).pack(side='right', padx=6)
        dialog.grab_set()
        chooser.focus_set()

    def _sort_changed(self):
        previous = self.store.get_setting('schedule_sort', 'None')
        previous_reverse = self.store.get_setting('schedule_sort_reverse', '0')
        if not self._flush_inline_editors() or not self._finish_inline_notes():
            self.schedule_sort.set(previous)
            self.sort_reverse.set(previous_reverse == '1')
            return
        try:
            self.store.set_setting('schedule_sort', self.schedule_sort.get())
            self.store.set_setting('schedule_sort_reverse', '1' if self.sort_reverse.get() else '0')
            self.sort_label.set(f'Sort: {self.schedule_sort.get()} ▾')
            self.sort_menu.entryconfigure(5, state='disabled' if self.schedule_sort.get() == 'None' else 'normal')
            self._refresh_campaigns()
        except Exception as error:
            messagebox.showerror('Sort could not be saved', str(error), parent=self)

    def _filter_changed(self, *args):
        try:
            if not self._refresh_campaigns():
                return
        except Exception as error:
            messagebox.showerror('Could not load schedules', str(error), parent=self)

    def _clear_filters(self):
        self.schedule_search.set('')

    def _edit_inline_notes(self, schedule_id):
        if schedule_id == self._home_notes_id:
            return 'break'
        if not self._finish_inline_notes():
            return 'break'
        try:
            notes = self.store.load(schedule_id)['data'].get('notes', '')
        except Exception as error:
            messagebox.showerror('Could not load notes', str(error), parent=self)
            return 'break'
        self.campaign_list.selection_set(schedule_id)
        label = self.campaign_list._items[schedule_id]['notes']
        label.grid_remove()
        self.home_notes = ResizableNotes(label.master, height=3, width=1, wrap='word', undo=True,
                                       padx=6, pady=4)
        self.home_notes.grid(row=0, column=3, sticky='nsew')
        self.home_notes.insert('1.0', notes)
        self.home_notes.edit_modified(False)
        self.home_notes.import_button = self._template_import_button(self.home_notes.tools,
                         lambda body, field=self.home_notes: self._import_notes_template(field, body), self.home_notes)
        self.home_notes.import_button.pack(side='right', pady=(0, 4))
        self._home_notes_id = schedule_id
        self._home_notes_dirty = False
        self.home_notes.bind('<<Modified>>', self._home_notes_changed)
        field = self.home_notes
        self.home_notes.bind('<FocusOut>', lambda event: self.after_idle(lambda: self._finish_notes_on_blur(field)), add=True)
        self.home_notes.bind('<Control-Return>', lambda event: self._finish_inline_notes() and 'break')
        self.home_notes.bind('<Command-Return>', lambda event: self._finish_inline_notes() and 'break')
        self._bind_scrolling(self.home_notes.frame)
        self.home_notes.focus_set()
        return 'break'

    def _finish_notes_on_blur(self, field):
        # Ignore delayed blur events from an editor that was already replaced,
        # or a transient focus change that has returned to this text field.
        if self.home_notes is not field:
            return
        focused = self.focus_get()
        if field._dragging or field._menu_open:
            return
        while focused is not None:
            if focused is field.frame:
                return
            focused = focused.master
        self._finish_inline_notes()

    def _finish_inline_notes(self):
        if not self._save_home_notes():
            return False
        if self.home_notes is not None:
            field = self.home_notes
            schedule_id = self._home_notes_id
            self.home_notes = None
            self._home_notes_id = None
            # ScrolledText delegates geometry to a wrapper frame. Destroying
            # only the Text leaves that empty frame covering the notes preview.
            field.frame.destroy()
            if self.campaign_list.exists(schedule_id):
                self.campaign_list._items[schedule_id]['notes'].grid()
            self.campaign_list.update_idletasks()
            self.campaign_list._schedule_fit()
        return True

    def _home_selection_changed(self, event=None, force=False):
        if self._selecting_notes or self._home_notes_id is None:
            return
        if self.campaign_list.selection() == (self._home_notes_id,) and not force:
            return
        if not self._finish_inline_notes():
            self._selecting_notes = True
            try:
                self.campaign_list.selection_set(self._home_notes_id)
            finally:
                self._selecting_notes = False

    def _home_notes_changed(self, event):
        if self.home_notes is None or not self.home_notes.edit_modified():
            return
        self.home_notes.edit_modified(False)
        if self._home_notes_loading or self._home_notes_id is None:
            return
        self._home_notes_dirty = True
        self.home_notes_status.set('Saving…')
        if self._home_notes_job is not None:
            self.after_cancel(self._home_notes_job)
        self._home_notes_job = self.after(500, self._save_home_notes)

    def _save_home_notes(self):
        if self.home_notes is None:
            return True
        if self.home_notes.edit_modified() and self._home_notes_id is not None:
            self._home_notes_dirty = True
            self.home_notes.edit_modified(False)
        if self._home_notes_job is not None:
            self.after_cancel(self._home_notes_job)
            self._home_notes_job = None
        if not self._home_notes_dirty or self._home_notes_id is None:
            return True
        try:
            notes = self.home_notes.get('1.0', 'end-1c')
            self.store.set_notes(self._home_notes_id, notes)
        except Exception as error:
            self.home_notes_status.set('Not saved')
            messagebox.showerror('Notes could not be saved', f'Your notes are still open.\n\n{error}', parent=self)
            return False
        self._home_notes_dirty = False
        self.home_notes_status.set('All notes saved')
        if self.campaign_list.exists(self._home_notes_id):
            values = self.campaign_list.item(self._home_notes_id, 'values')
            preview = ' '.join(notes.split())
            preview = preview[:87] + '…' if len(preview) > 90 else preview
            self.campaign_list.item(self._home_notes_id, values=(values[0], preview, values[2]))
        return True

    def _show_home(self):
        if not self._save_campaign():
            return
        try:
            if not self._refresh_campaigns():
                return
        except Exception as error:
            messagebox.showerror('Could not load schedules', str(error), parent=self)
            return
        self.campaign_id = None
        self.page.pack_forget()
        self.templates_page.pack_forget()
        self.home.pack(fill='both', expand=True)
        self.title('MHW Scheduler')

    def _selected_campaign(self):
        selected = self.campaign_list.selection()
        return selected[0] if selected else None

    def _new_campaign(self):
        name = simpledialog.askstring('New schedule', 'Schedule name:', parent=self)
        if name is None:
            return
        try:
            if not self._flush_inline_editors() or not self._finish_inline_notes():
                return
            campaign_id = self.store.create(name, self.active_folder)
        except Exception as error:
            messagebox.showerror('Could not create schedule', str(error), parent=self)
            return
        if self.schedule_search.get():
            self.schedule_search.set('')
        self._show_home()
        self.campaign_list.selection_set(campaign_id)
        self.campaign_list.see(campaign_id)

    def _open_selected(self, event=None):
        campaign_id = self._selected_campaign()
        if campaign_id:
            self._open_campaign(campaign_id)

    def _schedule_context_menu(self, campaign_id, event):
        if not self._save_home_notes():
            return 'break'
        if campaign_id not in self.campaign_list.selection():
            self.campaign_list.selection_set(campaign_id)
        if campaign_id not in self.campaign_list.selection():
            return 'break'
        selected = self.campaign_list.selection()
        menu = getattr(self, '_active_copy_menu', None)
        if menu is not None and menu.winfo_exists():
            menu.destroy()
        menu = tk.Menu(self, tearoff=False)
        self._active_copy_menu = menu
        menu.add_command(label='Open', command=lambda: self._open_campaign(campaign_id))
        menu.add_command(label='Rename…', command=lambda: self._rename_campaign(campaign_id))
        move_label = 'Move to folder…' if len(selected) == 1 else f'Move {len(selected)} schedules to folder…'
        menu.add_command(label=move_label, command=lambda: self._move_selected(selected))
        menu.add_separator()
        menu.add_command(label='Delete…', command=lambda: self._delete_campaign(campaign_id))
        menu.add_separator()
        menu.add_command(label='Expand all', command=lambda: self._set_all_schedules_expanded(True))
        menu.add_command(label='Collapse all', command=lambda: self._set_all_schedules_expanded(False))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return 'break'

    def _set_all_schedules_expanded(self, expanded):
        if not self._flush_inline_editors() or not self._finish_inline_notes():
            return
        self.campaign_list.set_all_expanded(expanded)

    def _open_campaign(self, campaign_id):
        if not self._flush_inline_editors() or not self._save_home_notes() or not self._save_campaign():
            return
        try:
            campaign = self.store.load(campaign_id)
            data = campaign['data']
            rows = [(datetime.fromisoformat(row['date']), row['performer']) for row in data.get('rows', [])]
        except Exception as error:
            messagebox.showerror('Could not open schedule', str(error), parent=self)
            return
        self._loading = True
        try:
            self._cancel_template_refresh()
            self.notes_text.collapse()
            self.campaign_id = campaign_id
            self.campaign_name.set(campaign['name'])
            self.notes_text.delete('1.0', 'end')
            self.notes_text.insert('1.0', data.get('notes', ''))
            self.notes_text.edit_modified(False)
            self.notes_text.edit_reset()
            self.template_text.delete('1.0', 'end')
            self.template_text.insert('1.0', data.get('confirmation_template', DEFAULT_TEMPLATE))
            self.template_text.edit_modified(False)
            self.template_text.edit_reset()
            for _, _, frame in self.performers:
                frame.destroy()
            self.performers = []
            self._clear_results()
            saved_scripts = data.get('confirmation_scripts', {})
            self.confirmation_overrides = {name: text for name, text in saved_scripts.items()
                                           if isinstance(name, str) and isinstance(text, str)} if isinstance(saved_scripts, dict) else {}
            self.dates_text.delete('1.0', 'end')
            self.dates_text.insert('1.0', data.get('open_dates', ''))
            self.dates_text.edit_modified(False)
            self.dates_text.edit_reset()
            self.gap.set(data.get('minimum_gap', '7'))
            self.ai_model.set(data.get('ai_model', configured_model()))
            for performer in schedule_performers(data):
                self._performer_row(performer['name'], performer['availability'])
            self.rows = rows
            if rows:
                self._render_schedule()
            else:
                self.status.set('Enter dates and availability, then generate a schedule.')
            self._dirty = False
            self.save_status.set('All changes saved')
        finally:
            self._loading = False
        self.home.pack_forget()
        self.templates_page.pack_forget()
        self.page.pack(fill='both', expand=True)
        self.page_canvas.yview_moveto(0)
        self.title(f'{campaign["name"]} — MHW Scheduler')

    def _rename_campaign(self, campaign_id):
        if not self._save_home_notes() or not campaign_id:
            return
        try:
            campaign = self.store.load(campaign_id)
            name = simpledialog.askstring('Rename schedule', 'Schedule name:', initialvalue=campaign['name'], parent=self)
            if name is None:
                return
            self.store.rename(campaign_id, name)
            if campaign_id == self.campaign_id:
                self.campaign_name.set(name.strip())
                self.title(f'{name.strip()} — MHW Scheduler')
                self._queue_template_refresh()
            else:
                self._refresh_campaigns()
        except Exception as error:
            messagebox.showerror('Could not rename schedule', str(error), parent=self)

    def _rename_active(self):
        self._rename_campaign(self.campaign_id)

    def _rename_selected(self):
        self._rename_campaign(self._selected_campaign())

    def _delete_selected(self):
        self._delete_campaign(self._selected_campaign())

    def _delete_campaign(self, campaign_id):
        if not self._save_home_notes():
            return
        if not campaign_id:
            return
        try:
            name = self.store.load(campaign_id)['name']
        except Exception as error:
            messagebox.showerror('Could not delete schedule', str(error), parent=self)
            return
        if not messagebox.askyesno('Delete schedule?', f'Delete “{name}” and its saved schedule? This cannot be undone.', parent=self):
            return
        try:
            self.store.delete(campaign_id)
            self._refresh_campaigns()
            self._home_selection_changed()
        except Exception as error:
            messagebox.showerror('Could not delete schedule', str(error), parent=self)

    def _queue_save(self, *args):
        if self._loading or self.campaign_id is None:
            return
        self._dirty = True
        self.save_status.set('Saving…')
        if self._save_job is not None:
            self.after_cancel(self._save_job)
        self._save_job = self.after(500, self._save_campaign)

    def _flush_input_changes(self):
        # Capture edits even if their Tk Modified event is still queued.
        fields = [self.dates_text] + [entry for _, entry, _ in self.performers]
        if any(field.edit_modified() for field in fields):
            for field in fields:
                field.edit_modified(False)
            self._invalidate()

    def _save_campaign(self):
        self._capture_confirmation_edits()
        self._finish_schedule_edit()
        if self.campaign_id is not None:
            self._flush_input_changes()
            if self.notes_text.edit_modified():
                self.notes_text.edit_modified(False)
                self._queue_save()
            if self.template_text.edit_modified():
                self.template_text.edit_modified(False)
                self._queue_save()
        if self._save_job is not None:
            self.after_cancel(self._save_job)
            self._save_job = None
        if self.campaign_id is None or not self._dirty:
            return True
        fields = {
            'open_dates': self.dates_text.get('1.0', 'end-1c'),
            'minimum_gap': self.gap.get(),
            'ai_model': self.ai_model.get(),
            'notes': self.notes_text.get('1.0', 'end-1c'),
            'confirmation_template': self.template_text.get('1.0', 'end-1c'),
            'confirmation_scripts': dict(self.confirmation_overrides),
            'performers': [{'name': name, 'availability': entry.get('1.0', 'end-1c')}
                           for name, entry, _ in self.performers],
            'rows': [{'date': date.isoformat(), 'performer': name} for date, name in self.rows],
        }
        try:
            data = self.store.load(self.campaign_id)['data']
            sync_schedule_performers(data, fields['performers'])
            data.update(fields)
            self.store.save(self.campaign_id, data)
        except Exception as error:
            self.save_status.set('Not saved — please try again')
            messagebox.showerror('Schedule could not be saved', f'Your changes are still open.\n\n{error}', parent=self)
            return False
        self._dirty = False
        self.save_status.set('All changes saved')
        return True

    def _close(self):
        if self._flush_inline_editors() and self._save_home_notes() and self._save_campaign():
            self._cancel_template_refresh()
            self.destroy()

    def _notes_changed(self, event=None):
        if self.notes_text.edit_modified():
            self.notes_text.edit_modified(False)
            self._queue_save()
            self._queue_template_refresh()

    def _cancel_template_refresh(self):
        if self._template_job is not None:
            self.after_cancel(self._template_job)
            self._template_job = None

    def _queue_template_refresh(self):
        if self._loading:
            return
        self._cancel_template_refresh()
        self._template_job = self.after(180, self._refresh_template_preview)

    def _refresh_template_preview(self):
        self._template_job = None
        if self.campaign_id is not None:
            self._show_confirmations()

    def _template_changed(self, event):
        if self.template_text.edit_modified():
            self.template_text.edit_modified(False)
            if not self._loading:
                self._queue_save()
                self._queue_template_refresh()

    def _insert_template_field(self, token):
        try:
            self.template_text.delete('sel.first', 'sel.last')
        except tk.TclError:
            pass
        if self.template_text.get('insert-1c', 'insert') == '@':
            self.template_text.delete('insert-1c', 'insert')
        self.template_text.insert('insert', token)
        self.template_text.focus_set()

    def _reset_template(self):
        self.template_text.delete('1.0', 'end')
        self.template_text.insert('1.0', DEFAULT_TEMPLATE)
        self._template_changed(None)

    def _automatic_confirmation(self, name):
        # Read the live fields even if the short preview debounce is pending.
        dates = [date for date, performer in self.rows if performer == name]
        try:
            open_dates = parse_open_dates(self.dates_text.get('1.0', 'end-1c'))
        except ValueError:
            open_dates = []
        return render_confirmation(self.template_text.get('1.0', 'end-1c'),
                               performer=name, confirmed_dates=dates, open_dates=open_dates,
                               schedule=self.campaign_name.get(), notes=self.notes_text.get('1.0', 'end-1c'))

    def _capture_confirmation_edits(self):
        if self._loading:
            return
        changed = False
        for name, field in self.confirmation_editors.items():
            if field.winfo_exists() and field.edit_modified():
                text = field.get('1.0', 'end-1c')
                field.edit_modified(False)
                if text == self._automatic_confirmation(name):
                    self.confirmation_overrides.pop(name, None)
                else:
                    self.confirmation_overrides[name] = text
                changed = True
        if changed:
            self._queue_save()

    def _confirmation_edited(self, name, field):
        if self.confirmation_editors.get(name) is field:
            self._capture_confirmation_edits()

    def _commit_confirmation(self, name, field):
        if not self._loading and self.campaign_id is not None and self.confirmation_editors.get(name) is field:
            self._save_campaign()

    def _reset_confirmation(self, name):
        self._capture_confirmation_edits()
        self.confirmation_overrides.pop(name, None)
        self._queue_save()
        self._show_confirmations()

    def _copy_confirmation(self, name):
        self._capture_confirmation_edits()
        return self._copy_text(self.confirmation_overrides.get(name, self._automatic_confirmation(name)))

    def _show_confirmations(self):
        self._capture_confirmation_edits()
        dates_by_performer = {}
        for date, name in self.rows:
            if name is not None:
                dates_by_performer.setdefault(name, []).append(date)
        # Update automatic scripts in place, preserving the cursor and undo
        # history in any performer script the user is currently editing.
        if list(self.confirmation_editors) == list(dates_by_performer):
            for name, field in self.confirmation_editors.items():
                message = self.confirmation_overrides.get(name, self._automatic_confirmation(name))
                if field.get('1.0', 'end-1c') != message:
                    field.delete('1.0', 'end')
                    field.insert('1.0', message)
                    field.edit_modified(False)
                    field.edit_reset()
            return
        self.confirmation_editors = {}
        for child in self.confirmations.winfo_children():
            child.destroy()
        try:
            open_dates = parse_open_dates(self.dates_text.get('1.0', 'end-1c'))
        except ValueError:
            open_dates = []
        template = self.template_text.get('1.0', 'end-1c')
        for name, dates in dates_by_performer.items():
            message = render_confirmation(template, performer=name, confirmed_dates=dates,
                                          open_dates=open_dates, schedule=self.campaign_name.get(),
                                          notes=self.notes_text.get('1.0', 'end-1c'))
            message = self.confirmation_overrides.get(name, message)
            frame = ttk.Frame(self.confirmations)
            frame.pack(fill='x', pady=(0, 10))
            heading = ttk.Frame(frame)
            heading.pack(fill='x', pady=(0, 4))
            ttk.Label(heading, text=name).pack(side='left')
            ttk.Button(heading, text='Copy script', style='Quiet.TButton',
                       command=lambda performer=name: self._copy_confirmation(performer)).pack(side='right')
            ttk.Button(heading, text='Use template', style='Quiet.TButton',
                       command=lambda performer=name: self._reset_confirmation(performer)).pack(side='right', padx=(0, 8))
            text = ScrolledText(frame, height=3, width=80, wrap='word', undo=True)
            text.insert('1.0', message)
            text.edit_modified(False)
            self.confirmation_editors[name] = text
            text.bind('<<Modified>>', lambda event, performer=name, field=text: self._confirmation_edited(performer, field))
            text.bind('<FocusOut>', lambda event, performer=name, field=text: self._commit_confirmation(performer, field))
            text.pack(fill='x')
            self._bind_scrolling(frame)

    def _bind_scrolling(self, widget):
        # Run before native Text/Treeview bindings so each wheel event scrolls once.
        tags = widget.bindtags()
        if 'MHWScroll' not in tags:
            widget.bindtags(('MHWScroll',) + tags)
        for child in widget.winfo_children():
            self._bind_scrolling(child)

    def _click_outside_field(self, event):
        focused = self.focus_get()
        fields = (tk.Text, tk.Entry, ttk.Entry, tk.Spinbox, ttk.Spinbox, ttk.Combobox)
        if not isinstance(focused, fields) or event.widget is focused:
            return
        # The scrollbar belongs to its text field; using it is still editing.
        container = getattr(focused, 'frame', None)
        clicked = event.widget
        while clicked is not None:
            if container is not None and clicked is container:
                return
            clicked = clicked.master
        if isinstance(focused, ResizableNotes):
            focused._menu_open = False
        # Labels and blank space don't normally take focus in Tk. Give the
        # clicked widget focus so the field's normal FocusOut commit also runs.
        event.widget.focus_set()
        parent = focused.master
        while parent is not None:
            if parent is self.page:
                self._save_campaign()
                break
            parent = parent.master

    def _scroll_wheel(self, event):
        widget = self.winfo_containing(event.x_root, event.y_root) or event.widget
        axis = 'x' if getattr(event, 'state', 0) & 1 else 'y'
        number = getattr(event, 'num', None)
        if number in (4, 5):
            units = -1 if number == 4 else 1
        else:
            delta = -float(getattr(event, 'delta', 0))
            if self.tk.call('tk', 'windowingsystem') != 'aqua':
                delta /= 120
            elif tk.TkVersion >= 9:
                delta /= 40  # Tk 9 separates mouse-wheel ticks from precise trackpad events.
            key = (str(widget), axis)
            total = self._wheel_remainders.get(key, 0) + delta
            units = int(total)
            self._wheel_remainders[key] = total - units
        if not units:
            return 'break'
        return self._scroll_in_direction(widget, axis, units)

    def _scroll_touchpad(self, event):
        widget = self.winfo_containing(event.x_root, event.y_root) or event.widget
        # Tk packs signed horizontal and vertical pixel deltas into a single %D.
        packed = int(event.delta)
        dx = packed >> 16
        low = packed & 0xffff
        dy = low if low < 0x8000 else low - 0x10000
        for axis, delta in (('x', dx), ('y', dy)):
            key = (str(widget), 'touchpad-' + axis)
            total = self._wheel_remainders.get(key, 0) - delta / 20.0
            units = int(total)
            self._wheel_remainders[key] = total - units
            if units:
                self._scroll_in_direction(widget, axis, units)
        return 'break'

    def _scroll_in_direction(self, widget, axis, units):
        # Prefer the field/table under the pointer; continue into its containing
        # list/page at the edge. Labels, buttons, and empty space reach the page.
        while widget is not None:
            if isinstance(widget, (tk.Scrollbar, ttk.Scrollbar)):
                siblings = widget.master.winfo_children()
                widget = next((sibling for sibling in siblings if isinstance(sibling, (tk.Text, tk.Canvas, ttk.Treeview))), widget)
            scrollable = isinstance(widget, (tk.Text, tk.Canvas, ttk.Treeview))
            scrollable = scrollable or (axis == 'x' and isinstance(widget, (tk.Entry, ttk.Entry)))
            if scrollable:
                view = getattr(widget, axis + 'view')()
                if view and ((units < 0 and view[0] > 0.000001) or (units > 0 and view[1] < 0.999999)):
                    if widget is self.table:
                        self._finish_schedule_edit()
                    getattr(widget, axis + 'view_scroll')(units, 'units')
                    return 'break'
            widget = widget.master
        return 'break'

    def _copy_modifiers(self):
        return ('Control', 'Command') if self.tk.call('tk', 'windowingsystem') == 'aqua' else ('Control',)

    def _copy_text(self, value):
        if value:
            self.clipboard_clear()
            self.clipboard_append(value)
        return 'break'

    def _copy_schedule(self, selected_only=False):
        selected = set(self.table.selection())
        items = [item for item in self.table.get_children() if not selected_only or item in selected]
        if items:
            lines = ['Date\tPerformer\tDay']
            lines.extend('\t'.join(map(str, self.table.item(item, 'values'))) for item in items)
            self._copy_text('\n'.join(lines))
        return 'break'

    def _copy_availability(self):
        lines = [f'{name} - {entry.get("1.0", "end-1c").strip()}' for name, entry, _ in self.performers]
        return self._copy_text('\n'.join(lines))

    def _copy_names(self, selected_only=False):
        selected = set(self.names_table.selection())
        items = [item for item in self.names_table.get_children() if not selected_only or item in selected]
        if items:
            # No header, dates, or totals: paste directly into one table column.
            value = '\n'.join(str(self.names_table.item(item, 'values')[0]) for item in items)
            self._copy_text(value or '\n')
        return 'break'

    def _select_all(self, event):
        widget = event.widget
        if widget is self.folder_list:
            return 'break'
        if isinstance(widget, tk.Text):
            widget.tag_add('sel', '1.0', 'end-1c')
            return 'break'
        if isinstance(widget, (tk.Entry, ttk.Entry)):
            widget.selection_range(0, 'end')
            return 'break'
        if isinstance(widget, (ttk.Treeview, ScheduleList)):
            widget.selection_set(widget.get_children())
            return 'break'

    def _copy_menu(self, event):
        widget = event.widget
        if widget in (self.campaign_list, self.folder_list, self.template_list):
            return
        if not isinstance(widget, (tk.Text, tk.Entry, ttk.Entry, tk.Label, ttk.Label, ttk.Treeview)):
            return
        widget.focus_set()
        menu = getattr(self, '_active_copy_menu', None)
        if menu is not None and menu.winfo_exists():
            menu.destroy()
        menu = tk.Menu(widget.winfo_toplevel(), tearoff=False)
        self._active_copy_menu = menu
        if isinstance(widget, ttk.Treeview):
            copy_rows = self._copy_names if widget is self.names_table else self._copy_schedule
            item = widget.identify_row(event.y)
            if item and item not in widget.selection():
                widget.selection_set(item)
            menu.add_command(label='Copy selected rows', command=lambda: copy_rows(True),
                             state='normal' if widget.selection() else 'disabled')
            menu.add_command(label='Copy all names' if widget is self.names_table else 'Copy whole schedule', command=copy_rows)
            menu.add_command(label='Select all', command=lambda: self._select_all(event))
        elif isinstance(widget, (tk.Text, tk.Entry, ttk.Entry)):
            def copy_selection():
                try:
                    value = (widget.get('sel.first', 'sel.last') if isinstance(widget, tk.Text)
                             else widget.get()[widget.index('sel.first'):widget.index('sel.last')])
                except tk.TclError:
                    return
                self._copy_text(value)

            menu.add_command(label='Copy', command=copy_selection)
            menu.add_command(label='Copy all', command=lambda: self._copy_text(
                widget.get('1.0', 'end-1c') if isinstance(widget, tk.Text) else widget.get()))
            menu.add_command(label='Select all', command=lambda: self._select_all(event))
            if str(widget.cget('state')) == 'normal':
                menu.add_separator()
                menu.add_command(label='Cut', command=lambda: widget.event_generate('<<Cut>>'))
                menu.add_command(label='Paste', command=lambda: widget.event_generate('<<Paste>>'))
        else:
            variable = widget.cget('textvariable')
            menu.add_command(label='Copy', command=lambda: self._copy_text(
                str(widget.getvar(variable)) if variable else str(widget.cget('text'))))
        menu.tk_popup(event.x_root, event.y_root)
        return 'break'

    def _invalidate(self, *args):
        if self._loading:
            return
        self._clear_results()
        self.status.set('Inputs changed. Generate a schedule to see current results.')
        self._queue_save()

    def _clear_results(self):
        self._capture_confirmation_edits()
        self.confirmation_editors = {}
        self._finish_schedule_edit(cancel=True)
        self.alternate_button.configure(state='disabled')
        self.arrangement_status.set('')
        self.rows = []
        self.table.delete(*self.table.get_children())
        self.names_table.delete(*self.names_table.get_children())
        for child in self.confirmations.winfo_children():
            child.destroy()
        self.totals.set('')

    def _text_changed(self, event):
        if event.widget.edit_modified():
            event.widget.edit_modified(False)
            self._invalidate()

    def _add_performer(self):
        name = simpledialog.askstring('Add performer', 'Performer name:', parent=self)
        if name is None:
            return
        name = name.strip()
        if not name or performer_key(name) in [performer_key(item[0]) for item in self.performers]:
            messagebox.showerror('Invalid name', 'Enter a unique, nonempty performer name.', parent=self)
            return
        self._performer_row(name, '')
        self._invalidate()

    def _import_availability(self):
        dialog = tk.Toplevel(self)
        dialog.title('Import availability')
        dialog.geometry('800x800')
        dialog.minsize(520, 400)
        dialog.transient(self)
        import_page = ScrollableFrame(dialog)
        import_page.pack(fill='both', expand=True)
        content = import_page.content
        ttk.Label(content, text='Paste names and dates', font=('Helvetica', 16, 'bold')).pack(anchor='w')
        ttk.Label(content, text='Paste the original availability list, including names and notes. Script lines are ignored.\nSupports written months, numeric dates, ranges, shared days, All, and weekday rules.\nYou can review converted dates and skipped entries before importing.').pack(anchor='w', pady=(6, 10))
        text = ScrolledText(content, height=16, wrap='word', undo=True)
        text.pack(fill='both', expand=True)
        ttk.Label(content, text='DJ Mahealani - 12/11 & 12\nDJ BittyScorp - November 20, 27, 28\nDJ Bentley - 12/20-12/24').pack(anchor='w', pady=8)
        ttk.Label(content, text='Set your open dates first. Availability years and All rules use those dates.').pack(anchor='w')
        replace = tk.BooleanVar(dialog, value=False)
        use_dates = tk.BooleanVar(dialog, value=False)
        ttk.Label(content, text='Matching names get updated availability; new names are added.').pack(anchor='w')
        ttk.Checkbutton(content, text='Replace all performers with this import', variable=replace).pack(anchor='w')
        use_dates_check = ttk.Checkbutton(content, text='Also replace open dates with all dates from this import', variable=use_dates)
        use_dates_check.pack(anchor='w')
        ai_mode = tk.BooleanVar(dialog, value=False)

        def toggle_ai():
            if ai_mode.get():
                use_dates.set(False)
                use_dates_check.configure(state='disabled')
            else:
                use_dates_check.configure(state='normal')

        ai_check = ttk.Checkbutton(content, text='Use AI conversion (OpenAI API)', variable=ai_mode, command=toggle_ai)
        ai_check.pack(anchor='w', pady=(10, 0))
        ttk.Label(content, text='AI sends this text and open dates to OpenAI; API usage is billed. It returns only current open dates.').pack(anchor='w')
        credentials = ttk.Frame(content)
        credentials.pack(fill='x', pady=(6, 0))
        ttk.Label(credentials, text='API key').grid(row=0, column=0, sticky='w', padx=(0, 6))
        key_entry = ttk.Entry(credentials, textvariable=self.ai_api_key, show='•', width=42)
        key_entry.grid(row=0, column=1, sticky='ew')
        credentials.columnconfigure(1, weight=1)
        ttk.Label(credentials, text='Model').grid(row=0, column=2, padx=(12, 6))
        model_entry = ttk.Entry(credentials, textvariable=self.ai_model, width=20)
        model_entry.grid(row=0, column=3)
        ttk.Label(content, text='Key stays in memory. Leave blank to use OPENAI_API_KEY from your environment.').pack(anchor='w')
        progress = tk.StringVar(dialog, value='')
        ttk.Label(content, textvariable=progress).pack(anchor='w', pady=(4, 0))

        def load_text():
            path = filedialog.askopenfilename(parent=dialog, title='Load availability text', filetypes=[('Text files', '*.txt'), ('All files', '*')])
            if not path:
                return
            try:
                with open(path, encoding='utf-8-sig') as file:
                    value = file.read()
            except (OSError, UnicodeError) as error:
                messagebox.showerror('Cannot read text file', str(error), parent=dialog)
                return
            text.delete('1.0', 'end')
            text.insert('1.0', value)

        def show_preview(result):
            preview = tk.Toplevel(dialog)
            preview.title('Review converted availability')
            preview.geometry('800x640')
            preview.transient(dialog)
            preview.minsize(520, 400)
            preview_page = ScrollableFrame(preview)
            preview_page.pack(fill='both', expand=True)
            body = preview_page.content
            ttk.Label(body, text=f'{len(result.availability)} performers ready to import · {len(result.notes)} review notes', font=('Helvetica', 15, 'bold')).pack(anchor='w', pady=(0, 10))
            output = ScrolledText(body, wrap='word', height=24)
            output.pack(fill='both', expand=True)
            output.insert('1.0', result.preview())
            output.configure(state='disabled')
            ttk.Label(body, text='Names without dates and ambiguous entries are skipped. Confirm the converted dates.').pack(anchor='w', pady=8)
            actions = ttk.Frame(body)
            actions.pack(fill='x')

            def back():
                preview.destroy()
                dialog.grab_set()

            def apply_import():
                self._apply_availability_import(result.availability, replace.get(), use_dates.get())
                preview.destroy()
                dialog.destroy()
                self.status.set(f'Imported {len(result.availability)} performers. Generate a schedule to see results.')

            ttk.Button(actions, text='Back to text', command=back).pack(side='left')
            ttk.Button(actions, text='Copy preview', command=lambda: self._copy_text(output.get('1.0', 'end-1c'))).pack(side='left', padx=8)
            ttk.Button(actions, text='Import converted dates', command=apply_import,
                       state='normal' if result.availability else 'disabled').pack(side='right')
            preview.protocol('WM_DELETE_WINDOW', back)
            self._bind_scrolling(preview)
            preview.grab_set()

        def set_busy(busy):
            state = 'disabled' if busy else 'normal'
            for widget in (text, preview_button, load_button, ai_check, key_entry, model_entry):
                widget.configure(state=state)
            progress.set('AI is reading the availability… You can close this window to discard the result.' if busy else '')

        def preview_import():
            try:
                open_dates = parse_open_dates(self.dates_text.get('1.0', 'end'))
                year, month = infer_date_context(open_dates)
                source = text.get('1.0', 'end')
                if not ai_mode.get():
                    show_preview(parse_import(source, year, month, open_dates))
                    return
            except ValueError as error:
                messagebox.showerror('Check availability text', str(error), parent=dialog)
                return
            # Snapshot all Tk values on the main thread. The worker performs only
            # network/validation work; Tk polling and previews stay on this thread.
            api_key, model = self.ai_api_key.get(), self.ai_model.get()
            completed = queue.Queue()
            set_busy(True)

            def work():
                try:
                    completed.put((convert_with_ai(source, open_dates, api_key, model), None))
                except AIAvailabilityError as error:
                    completed.put((None, str(error)))
                except Exception:
                    completed.put((None, 'AI conversion failed. Check your settings or try the local parser.'))

            def poll():
                if not dialog.winfo_exists():
                    return
                try:
                    result, error = completed.get_nowait()
                except queue.Empty:
                    self.after(100, poll)
                    return
                set_busy(False)
                if error:
                    messagebox.showerror('AI conversion failed', error, parent=dialog)
                else:
                    show_preview(result)

            threading.Thread(target=work, daemon=True).start()
            self.after(100, poll)

        buttons = ttk.Frame(content)
        buttons.pack(fill='x', pady=(12, 0))
        load_button = ttk.Button(buttons, text='Load text file…', command=load_text)
        load_button.pack(side='left')
        preview_button = ttk.Button(buttons, text='Preview import', command=preview_import)
        preview_button.pack(side='right')
        ttk.Button(buttons, text='Cancel', command=dialog.destroy).pack(side='right', padx=8)
        self._bind_scrolling(dialog)
        dialog.grab_set()
        text.focus_set()

    def _apply_availability_import(self, people, replace=False, use_dates=False):
        if replace:
            for _, _, frame in self.performers:
                frame.destroy()
            self.performers = []
        existing = {performer_key(name): entry for name, entry, _ in self.performers}
        for name, dates in people.items():
            value = ', '.join(f'{date.month}/{date.day}/{date.year:04d}' for date in dates)
            entry = existing.get(performer_key(name))
            if entry is None:
                self._performer_row(name, value)
                existing[performer_key(name)] = self.performers[-1][1]
            else:
                entry.delete('1.0', 'end')
                entry.insert('1.0', value)
                entry.edit_modified(False)
                entry._last_committed_availability = value
        if use_dates:
            dates = sorted({date for values in people.values() for date in values})
            self.dates_text.delete('1.0', 'end')
            self.dates_text.insert('1.0', '\n'.join(f'{date.month}/{date.day}/{date.year:04d}' for date in dates))
            self.dates_text.edit_modified(False)
        self._invalidate()

    def _performer_row(self, name, dates):
        frame = ttk.Frame(self.people, padding=(0, 0, 6, 8))
        frame.pack(fill='x')
        header = ttk.Frame(frame)
        header.pack(fill='x')
        ttk.Label(header, text=name, font=('Helvetica', 12, 'bold')).pack(side='left')
        entry = ScrolledText(frame, height=3, wrap='word', undo=True)
        entry.pack(fill='x', pady=(4, 0))
        entry.insert('1.0', dates)
        entry.edit_modified(False)
        entry._last_committed_availability = dates
        entry.bind('<<Modified>>', self._text_changed)
        item = (name, entry, frame)
        self.performers.append(item)
        formatting_status = tk.StringVar()
        ttk.Label(frame, textvariable=formatting_status, style='InlineStatus.TLabel',
                  wraplength=650).pack(anchor='w')
        commit = lambda event: self._commit_schedule_availability(name, entry, formatting_status)
        entry.bind('<FocusOut>', commit)
        entry.bind('<Control-Return>', commit)
        entry.bind('<Command-Return>', commit)

        def remove():
            self.performers.remove(item)
            frame.destroy()
            self._invalidate()

        ttk.Button(header, text='Remove', command=remove).pack(side='right')
        self._bind_scrolling(frame)

    def _commit_schedule_availability(self, name, entry, status):
        if self._loading or self.campaign_id is None or not entry.winfo_exists():
            return 'break'
        if not any(field is entry for _, field, _ in self.performers):
            return 'break'
        raw = entry.get('1.0', 'end-1c')
        if raw == entry._last_committed_availability:
            return 'break'
        if not self._save_campaign():
            return 'break'
        if not raw.strip():
            entry._last_committed_availability = raw
            status.set('')
            return 'break'
        # Saving synchronizes this field into its shared draft. Use the same
        # local conversion path as the expanded table, preserving the raw text.
        try:
            data = self.store.load(self.campaign_id)['data']
            draft = next(row for row in data['availability_drafts']
                         if performer_key(row['name']) == performer_key(name))
            self._convert_inline(self.campaign_id, draft['id'])
            if not self._save_campaign():
                return 'break'
            data = self.store.load(self.campaign_id)['data']
            saved = next(row for row in data['availability_drafts'] if row['id'] == draft['id'])
            status.set(saved.get('status', ''))
            if saved.get('status', '').startswith(('Updated', 'Needs review')):
                entry._last_committed_availability = entry.get('1.0', 'end-1c')
        except Exception as error:
            status.set('Could not format availability. Leave the field again to retry.')
            messagebox.showerror('Availability could not be formatted', str(error), parent=self)
        return 'break'

    def _load_defaults(self):
        self.dates_text.edit_modified(False)
        self._invalidate()

    def _read_inputs(self):
        try:
            gap = int(self.gap.get())
        except ValueError:
            raise ValueError('Minimum days between gigs must be a whole number.') from None
        dates = parse_open_dates(self.dates_text.get('1.0', 'end'))
        year, month = infer_date_context(dates)
        if not self.performers:
            raise ValueError('Enter at least one open date and add at least one performer.')
        if gap < 0:
            raise ValueError('Minimum days between gigs cannot be negative.')
        people = {}
        for name, entry, _ in self.performers:
            try:
                people[name] = parse_dates(entry.get('1.0', 'end'), year, month)
            except ValueError as error:
                raise ValueError(f'{name}: {error}') from None
        return gap, dates, people

    def _generate(self):
        self._flush_input_changes()
        try:
            gap, dates, people = self._read_inputs()
            rows, counts = generate_schedule(dates, people, gap)
        except ValueError as error:
            messagebox.showerror('Check your inputs', str(error), parent=self)
            return
        self._invalidate()
        self.rows = rows
        self._render_schedule()
        self._queue_save()

    def _render_schedule(self):
        self.table.delete(*self.table.get_children())
        self.names_table.delete(*self.names_table.get_children())
        self.alternate_button.configure(state='normal' if self.rows else 'disabled')
        counts = dict.fromkeys((name for name, _, _ in self.performers), 0)
        for date, name in self.rows:
            if name is not None:
                counts[name] = counts.get(name, 0) + 1
            self.table.insert('', 'end', values=(date.strftime('%m/%d/%Y'), name or 'Unassigned', date.strftime('%A')))
            self.names_table.insert('', 'end', values=(name or '',))
        self._show_confirmations()
        ranked_counts = sorted(counts.items(), key=lambda item: item[1], reverse=True)
        self.totals.set('   •   '.join(f'{name}: {count} gigs' for name, count in ranked_counts))
        unfilled = sum(name is None for _, name in self.rows)
        self.status.set(f'{len(self.rows)} dates • {len(self.rows) - unfilled} booked • {unfilled} unfilled.')

    def _scroll_schedule_table(self, axis, *args):
        self._finish_schedule_edit()
        getattr(self.table, axis + 'view')(*args)

    def _edit_schedule_cell(self, event):
        self._finish_schedule_edit()
        if event.keysym == 'Return':
            selected = self.table.selection()
            item = selected[0] if selected else ''
        else:
            if self.table.identify_region(event.x, event.y) != 'cell' or self.table.identify_column(event.x) != '#2':
                return
            item = self.table.identify_row(event.y)
        if not item:
            return
        self._flush_input_changes()
        if not self.table.exists(item):
            return
        # Finish any pending autosave before typing begins, so its timer cannot
        # commit a partially typed name.
        if not self._save_campaign():
            return
        index = self.table.index(item)
        self.table.selection_set(item)
        self.table.see(item)
        box = self.table.bbox(item, 'performer')
        if not box:
            return
        editor = ttk.Entry(self.table)
        current = self.rows[index][1]
        editor.insert(0, current or '')
        editor.selection_range(0, 'end')
        self._schedule_edit = (editor, index)
        editor.place(x=box[0], y=box[1], width=box[2], height=box[3])
        editor.bind('<Return>', lambda event: self._finish_schedule_edit())
        editor.bind('<Escape>', lambda event: self._finish_schedule_edit(cancel=True))
        editor.bind('<FocusOut>', lambda event: self.after_idle(self._schedule_edit_blurred, editor))
        self._bind_scrolling(editor)
        editor.focus_set()
        return 'break'

    def _schedule_edit_blurred(self, editor):
        if self._schedule_edit is None or self._schedule_edit[0] is not editor:
            return
        focused = str(self.tk.call('focus'))
        if focused == str(editor):
            return
        self._finish_schedule_edit()

    def _finish_schedule_edit(self, cancel=False):
        if self._schedule_edit is None:
            return 'break'
        editor, index = self._schedule_edit
        self._schedule_edit = None
        name = editor.get().strip() or None
        editor.destroy()
        if cancel or not 0 <= index < len(self.rows):
            return 'break'
        date, previous = self.rows[index]
        if name == previous:
            return 'break'
        self.rows[index] = (date, name)
        self._render_schedule()
        item = self.table.get_children()[index]
        self.table.selection_set(item)
        self.table.focus(item)
        self.arrangement_status.set('Booking updated · saved automatically')
        self._queue_save()
        return 'break'

    def _try_another_arrangement(self):
        self._flush_input_changes()
        if not self.rows:
            self._generate()
            return
        try:
            gap, dates, people = self._read_inputs()
            result = alternate_schedule(dates, people, gap, self.rows)
        except ValueError as error:
            messagebox.showerror('Check your inputs', str(error), parent=self)
            return
        if result is None:
            self.arrangement_status.set('No alternative found with as many booked dates. Current schedule kept.')
            return
        rows, _ = result
        self._clear_results()
        self.rows = rows
        self._render_schedule()
        self.arrangement_status.set('New arrangement · saved automatically')
        self._queue_save()


if __name__ == '__main__':
    AvailabilityApp().mainloop()
