"""Live appearance palettes and shared styling for the desktop workspace."""
import math
import tkinter as tk
from tkinter import font, ttk


PALETTES = {
    'Default': dict(backdrop='#ffffff', surface='#ffffff', sidebar='#f6faff', elevated='#eef5ff',
                    ink='#182d45', muted='#60758d', line='#dce7f1', accent='#1765cf',
                    primary='#1765cf', primary_ink='#ffffff', hover='#dbeafe', selection='#dceaff',
                    button_ink='#155ab6', success='#138148', success_hover='#0f6e3d'),
    'Dark': dict(backdrop='#0a0d12', surface='#131923', sidebar='#10151e', elevated='#1e2735',
                 ink='#edf2fb', muted='#9caabd', line='#283345', accent='#c1d4f4',
                 primary='#e6eefc', primary_ink='#111b2a', hover='#2a374b', selection='#2a3951'),
    'Miami Vice': dict(backdrop='#0c1020', surface='#14182e', sidebar='#101529', elevated='#202642',
                       ink='#f3f0ff', muted='#adaecc', line='#333754', accent='#42e8e0',
                       primary='#ff70bd', primary_ink='#20122d', hover='#303458', selection='#2e3154'),
    'Rose Quartz': dict(backdrop='#fce4ee', surface='#fff0f6', sidebar='#f8dce8', elevated='#f6e3eb',
                        ink='#402933', muted='#80616f', line='#e9cdd9', accent='#9e315f',
                        primary='#9e315f', primary_ink='#ffffff', hover='#ecd2df', selection='#efcfdf',
                        button_ink='#853250', success='#9e315f', success_hover='#853250'),
    'Crimson Noir': dict(backdrop='#09090d', surface='#111116', sidebar='#0d0d12', elevated='#1d171e',
                         ink='#f5edf0', muted='#b8a4ac', line='#37252d', accent='#ff6c7c',
                         primary='#b92539', primary_hover='#c62e43', primary_ink='#ffffff', hover='#30202a', selection='#45202b',
                         button_ink='#ff8593', success='#b92539', success_hover='#d6374c'),
}


def normalize_mode(mode):
    if mode == 'Light':
        return 'Default'
    return mode if mode in PALETTES else 'Default'


def _rounded_image(root, fill):
    image = tk.PhotoImage(master=root, width=28, height=28)
    radius = 8
    for y in range(28):
        edge = min(y, 27 - y)
        inset = max(0, math.ceil(radius - math.sqrt(max(0, radius * radius - (radius - edge - .5) ** 2)))) if edge < radius else 0
        image.put(fill, to=(inset, y, 28 - inset, y + 1))
    return image


def _button_layout(root, style, name, colors, key):
    # Nine-slice images give ttk controls rounded edges without replacing their
    # native keyboard, focus, or disabled-state behavior.
    elements = getattr(root, '_appearance_elements', {})
    element = f'MHW.{key}.{name}.border'
    if element not in elements:
        images = [_rounded_image(root, color) for color in colors]
        style.element_create(element, 'image', images[0], ('pressed', images[2]), ('active', images[1]),
                             border=10, padding=0, sticky='nswe')
        elements[element] = images
    root._appearance_elements = elements
    return [(element, {'sticky': 'nswe', 'children': [
        ('Button.focus', {'sticky': 'nswe', 'children': [
            ('Button.padding', {'sticky': 'nswe', 'children': [('Button.label', {'sticky': 'nswe'})]})]})]})]


def configure_appearance(root, mode='Default'):
    mode = normalize_mode(mode)
    palette = PALETTES[mode]
    p = palette
    root._appearance_palette = p
    root._appearance_name = mode
    style = ttk.Style(root)
    if style.theme_use() != 'clam':
        style.theme_use('clam')
    family = font.nametofont('TkDefaultFont', root=root).actual('family')
    for name in ('TkDefaultFont', 'TkTextFont', 'TkMenuFont'):
        font.nametofont(name, root=root).configure(family=family, size=12)
    root.configure(background=p['backdrop'])
    options = {
        '*Text.font': 'TkTextFont', '*Text.background': p['surface'], '*Text.foreground': p['ink'],
        '*Text.insertBackground': p['accent'], '*Text.selectBackground': p['selection'],
        '*Text.selectForeground': p['ink'], '*Text.relief': 'flat', '*Text.borderWidth': 0,
        '*Text.highlightThickness': 1, '*Text.highlightBackground': p['line'],
        '*Text.highlightColor': p['accent'], '*Text.padX': 12, '*Text.padY': 10,
        '*Canvas.background': p['surface'], '*Frame.background': p['surface'],
        '*Menu.background': p['elevated'], '*Menu.foreground': p['ink'],
        '*Menu.activeBackground': p['selection'], '*Menu.activeForeground': p['ink'],
        '*Listbox.background': p['surface'], '*Listbox.foreground': p['ink'],
        '*Listbox.selectBackground': p['selection'], '*Listbox.selectForeground': p['ink'],
        '*Scrollbar.background': p['elevated'], '*Scrollbar.troughColor': p['surface'],
        '*Scrollbar.activeBackground': p['hover'], '*Scrollbar.borderWidth': 0,
    }
    for option, value in options.items():
        root.option_add(option, value)
    style.configure('.', font=(family, 12), background=p['surface'], foreground=p['ink'])
    style.configure('TFrame', background=p['surface'])
    style.configure('Workspace.TFrame', background=p['backdrop'])
    style.configure('TLabel', background=p['surface'], foreground=p['ink'])
    style.configure('Brand.TLabel', font=(family, 17, 'bold'))
    style.configure('Title.TLabel', font=(family, 28, 'bold'))
    style.configure('LibraryTitle.TLabel', font=(family, 18, 'bold'))
    style.configure('Muted.TLabel', font=(family, 11), foreground=p['muted'])
    style.configure('Caption.TLabel', font=(family, 10, 'bold'), foreground=p['muted'])
    style.configure('Accent.TLabel', font=(family, 10, 'bold'), foreground=p['accent'])
    style.configure('Sun.TLabel', font=(family, 16), foreground=p['accent'])
    style.configure('RowName.TLabel', font=(family, 12, 'bold'))
    style.configure('RowMeta.TLabel', font=(family, 11), foreground=p['muted'])
    style.configure('InlineStatus.TLabel', font=(family, 10), foreground=p['muted'])
    style.configure('Sidebar.TFrame', background=p['sidebar'])
    style.configure('Sidebar.TLabel', background=p['sidebar'], foreground=p['muted'], font=(family, 10, 'bold'))
    style.configure('SidebarHint.TLabel', background=p['sidebar'], foreground=p['muted'], font=(family, 10))
    key = mode.replace(' ', '')
    variants = {
        'TButton': ('secondary', (p['elevated'], p['hover'], p['selection'])),
        'Primary.TButton': ('primary', (p['primary'], p.get('primary_hover', p['accent']), p['primary'])),
        'Quiet.TButton': ('quiet', (p['surface'], p['elevated'], p['hover'])),
        'Sidebar.TButton': ('sidebar', (p['sidebar'], p['elevated'], p['selection'])),
        'Success.TButton': ('success', (p.get('success', p['primary']), p.get('success_hover', p['accent']), p.get('success', p['primary']))),
    }
    for name, (variant, colors) in variants.items():
        style.layout(name, _button_layout(root, style, variant, colors, key))
        style.configure(name, padding=(12, 7), borderwidth=0, relief='flat',
                        background=colors[0], foreground=p['ink'], focuscolor=p['accent'], focusthickness=1)
        style.map(name, foreground=[('disabled', p['muted']), ('!disabled', p['ink'])])
    style.map('TButton', foreground=[('disabled', p['muted']), ('!disabled', p.get('button_ink', p['ink']))])
    style.configure('Primary.TButton', font=(family, 12, 'bold'), padding=(16, 9))
    style.map('Primary.TButton', foreground=[('disabled', p['muted']), ('!disabled', p['primary_ink'])])
    style.configure('Compact.Primary.TButton', font=(family, 11, 'bold'), padding=(10, 5))
    style.configure('Quiet.TButton', padding=(9, 6), font=(family, 11))
    style.map('Quiet.TButton', foreground=[('disabled', p['muted']), ('!disabled', p['muted'])])
    style.configure('Sidebar.TButton', font=(family, 11))
    style.configure('Success.TButton', font=(family, 12, 'bold'), padding=(14, 8))
    style.map('Success.TButton', foreground=[('disabled', p['muted']), ('!disabled', p['primary_ink'])])
    style.layout('Appearance.TMenubutton', _button_layout(root, style, 'appearance',
                 (p['elevated'], p['hover'], p['selection']), key))
    style.configure('Appearance.TMenubutton', font=(family, 11), padding=(12, 6),
                    background=p['elevated'], foreground=p['accent'], borderwidth=0,
                    focuscolor=p['accent'], focusthickness=1)
    style.configure('TEntry', fieldbackground=p['elevated'], foreground=p['ink'], insertcolor=p['accent'],
                    padding=(10, 8), bordercolor=p['line'], lightcolor=p['line'], darkcolor=p['line'],
                    selectbackground=p['selection'], selectforeground=p['ink'])
    style.configure('Compact.TEntry', padding=(8, 5))
    style.map('TEntry', bordercolor=[('focus', p['accent'])])
    style.configure('TCombobox', fieldbackground=p['elevated'], foreground=p['ink'], arrowcolor=p['muted'],
                    padding=(8, 7), bordercolor=p['line'], lightcolor=p['line'], darkcolor=p['line'], arrowsize=12)
    style.map('TCombobox', fieldbackground=[('readonly', p['elevated'])], selectbackground=[('readonly', p['elevated'])],
              selectforeground=[('readonly', p['ink'])], foreground=[('readonly', p['ink'])],
              background=[('readonly', p['elevated'])], bordercolor=[('focus', p['accent'])])
    style.configure('TLabelframe', background=p['surface'], bordercolor=p['line'], relief='solid', borderwidth=1)
    style.configure('TLabelframe.Label', background=p['surface'], foreground=p['ink'], font=(family, 12, 'bold'))
    style.configure('TSeparator', background=p['line'])
    style.configure('Accent.TSeparator', background=p['accent'])
    style.configure('TPanedwindow', background=p['backdrop'])
    style.configure('Sash', sashthickness=12, background=p['backdrop'])
    style.configure('Treeview', rowheight=30, background=p['surface'], fieldbackground=p['surface'], foreground=p['ink'],
                    borderwidth=0, bordercolor=p['line'], lightcolor=p['surface'], darkcolor=p['surface'])
    style.configure('Treeview.Heading', background=p['elevated'], font=(family, 10, 'bold'),
                    foreground=p['muted'], padding=(8, 8), bordercolor=p['line'], relief='flat')
    style.map('Treeview.Heading', background=[('active', p['hover'])])
    style.map('Treeview', background=[('selected', p['selection'])], foreground=[('selected', p['ink'])])
    style.configure('Folders.Treeview', background=p['sidebar'], fieldbackground=p['sidebar'], rowheight=36,
                    font=(family, 12), bordercolor=p['sidebar'], lightcolor=p['sidebar'], darkcolor=p['sidebar'], indent=8)
    style.map('Folders.Treeview', background=[('selected', p['selection'])], foreground=[('selected', p['accent'])])
    style.configure('TCheckbutton', background=p['surface'], foreground=p['ink'], indicatorbackground=p['surface'],
                    indicatorforeground=p['ink'], indicatorcolor=p['surface'], bordercolor=p['line'], padding=0)
    style.map('TCheckbutton', background=[('active', p['surface'])], indicatorbackground=[('selected', p['accent'])],
              indicatorforeground=[('selected', p['backdrop'])])
    for orientation in ('Vertical', 'Horizontal'):
        style.configure(f'{orientation}.TScrollbar', troughcolor=p['surface'], background=p['line'],
                        bordercolor=p['surface'], lightcolor=p['line'], darkcolor=p['line'],
                        arrowcolor=p['muted'], arrowsize=9, borderwidth=0)
        style.map(f'{orientation}.TScrollbar', background=[('active', p['hover'])])
    _recolor_widgets(root, p)
    return mode


def _recolor_widgets(widget, p):
    if isinstance(widget, tk.Text):
        widget.configure(background=p['surface'], foreground=p['ink'], insertbackground=p['accent'],
                         selectbackground=p['selection'], selectforeground=p['ink'],
                         highlightbackground=p['line'], highlightcolor=p['accent'])
    elif isinstance(widget, tk.Canvas):
        widget.configure(background=p['surface'])
    elif isinstance(widget, (tk.Frame, tk.Toplevel)):
        widget.configure(background=p['surface'])
    elif isinstance(widget, tk.Scrollbar):
        # Tk 9 can expose a themed scrollbar through tkinter.Scrollbar. Those
        # controls take their colors from ttk styles rather than Tk options.
        options = dict(background=p['line'], troughcolor=p['surface'], activebackground=p['hover'],
                       highlightbackground=p['surface'])
        supported = widget.keys()
        widget.configure(**{key: value for key, value in options.items() if key in supported})
    elif isinstance(widget, tk.Menu):
        options = dict(background=p['elevated'], foreground=p['ink'],
                       activebackground=p['selection'], activeforeground=p['ink'])
        supported = widget.keys()
        widget.configure(**{key: value for key, value in options.items() if key in supported})
    elif isinstance(widget, ttk.Combobox):
        try:
            popdown = widget.tk.call('ttk::combobox::PopdownWindow', widget)
            widget.tk.call(str(popdown) + '.f.l', 'configure', '-background', p['surface'], '-foreground', p['ink'],
                           '-selectbackground', p['selection'], '-selectforeground', p['ink'])
        except tk.TclError:
            pass
    for child in widget.winfo_children():
        _recolor_widgets(child, p)
