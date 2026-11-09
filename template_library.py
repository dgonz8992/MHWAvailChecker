"""Editor for reusable named notes and confirmation templates."""
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from tkinter.scrolledtext import ScrolledText

from confirmation_templates import SCHEDULE_TEMPLATE_FIELDS


class TemplateDialog(simpledialog.Dialog):
    def __init__(self, app, template=None):
        self.app = app
        self.template = template
        super().__init__(app, 'Edit template' if template else 'New template')

    def body(self, master):
        self.configure(background=self.app._appearance_palette['surface'])
        ttk.Label(master, text='Template name', style='Caption.TLabel').pack(anchor='w', pady=(8, 4))
        self.name_entry = ttk.Entry(master, width=50)
        self.name_entry.pack(fill='x', pady=(0, 12))
        toolbar = ttk.Frame(master)
        toolbar.pack(fill='x', pady=(0, 4))
        ttk.Label(toolbar, text='Template text', style='Caption.TLabel').pack(side='left')
        insert = ttk.Menubutton(toolbar, text='Insert field ▾')
        insert.pack(side='right')
        menu = tk.Menu(insert, tearoff=False)
        insert.configure(menu=menu)
        for token, description in SCHEDULE_TEMPLATE_FIELDS:
            menu.add_command(label=f'{token} — {description}', command=lambda value=token: self.insert_field(value))
        self.body_text = ScrolledText(master, height=12, width=58, wrap='word', undo=True)
        self.body_text.pack(fill='both', expand=True)
        ttk.Label(master, text='Schedule fields fill in when importing into notes.',
                  style='Muted.TLabel').pack(anchor='w', pady=(8, 4))
        if self.template:
            self.name_entry.insert(0, self.template['name'])
            self.body_text.insert('1.0', self.template['body'])
            self.name_entry.selection_range(0, 'end')
        self.name_entry.bind('<Return>', self.ok)
        self.app._bind_scrolling(master)
        return self.name_entry

    def insert_field(self, token):
        try:
            self.body_text.delete('sel.first', 'sel.last')
        except tk.TclError:
            pass
        if self.body_text.get('insert-1c', 'insert') == '@':
            self.body_text.delete('insert-1c', 'insert')
        self.body_text.insert('insert', token)
        self.body_text.focus_set()

    def buttonbox(self):
        buttons = ttk.Frame(self, padding=12)
        buttons.pack(fill='x')
        ttk.Button(buttons, text='Save template', style='Primary.TButton', command=self.ok).pack(side='right')
        ttk.Button(buttons, text='Cancel', command=self.cancel).pack(side='right', padx=(0, 8))
        self.bind('<Escape>', self.cancel)

    def validate(self):
        try:
            self.result = self.app.store.save_template(self.name_entry.get(), self.body_text.get('1.0', 'end-1c'),
                                                       self.template['id'] if self.template else None)
            return True
        except Exception as error:
            messagebox.showerror('Template could not be saved', str(error), parent=self)
            return False
