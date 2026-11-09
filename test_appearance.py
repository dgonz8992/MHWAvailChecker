"""Appearance preference and live switching regression checks."""
import os
from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import ttk
import unittest

from appearance import PALETTES, normalize_mode
from campaigns import CampaignStore


class AppearancePreferenceTests(unittest.TestCase):
    def test_preference_persists_independently_of_schedule_data(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'schedules.sqlite3'
            store = CampaignStore(path)
            schedule = store.create('November')
            store.save(schedule, {'notes': 'Keep this note'})
            self.assertEqual(store.get_setting('appearance', 'Default'), 'Default')
            store.set_setting('appearance', 'Miami Vice')
            reopened = CampaignStore(path)
            self.assertEqual(reopened.get_setting('appearance'), 'Miami Vice')
            self.assertEqual(reopened.load(schedule)['data'], {'notes': 'Keep this note'})
            reopened.set_setting('appearance', 'Default')
            self.assertEqual(store.get_setting('appearance'), 'Default')

    def test_invalid_preference_falls_back_to_supported_mode(self):
        self.assertEqual(normalize_mode('old theme'), 'Default')
        self.assertEqual(normalize_mode('Light'), 'Default')
        for mode in PALETTES:
            self.assertEqual(normalize_mode(mode), mode)


@unittest.skipUnless(os.environ.get('MHW_RUN_GUI_TESTS') == '1', 'Requires a desktop session')
class LiveAppearanceTests(unittest.TestCase):
    def test_schedule_name_dialog_uses_current_theme(self):
        from tkinter import simpledialog
        for mode, palette in PALETTES.items():
            self.app._change_appearance(mode)
            observed = {}
            def inspect_and_close():
                dialog = next(child for child in self.app.winfo_children() if isinstance(child, tk.Toplevel))
                try:
                    observed['dialog'] = dialog.cget('background')
                    observed['entry'] = dialog.entry.cget('background')
                    observed['ink'] = dialog.entry.cget('foreground')
                    def labels(parent):
                        for child in parent.winfo_children():
                            if isinstance(child, tk.Label):
                                yield child.cget('background')
                            yield from labels(child)
                    observed['labels'] = list(labels(dialog))
                finally:
                    dialog.cancel()
            self.app.after(100, inspect_and_close)
            simpledialog.askstring('New schedule', 'Schedule name:', parent=self.app)
            self.assertEqual(observed['dialog'], palette['surface'])
            self.assertEqual(observed['entry'], palette['elevated'])
            self.assertEqual(observed['ink'], palette['ink'])
            self.assertTrue(observed['labels'])
            self.assertTrue(all(color == palette['surface'] for color in observed['labels']))

    def setUp(self):
        from main import AvailabilityApp
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = CampaignStore(Path(self.temp.name) / 'schedules.sqlite3')
        self.app = AvailabilityApp(store=self.store)
        self.addCleanup(lambda: self.app._close())
        self.errors = []
        self.app.report_callback_exception = lambda *args: self.errors.append(args)
        self.app.update()

    def test_switching_updates_existing_fields_without_losing_unsaved_notes(self):
        schedule = self.store.create('November')
        self.app._refresh_campaigns()
        self.app.campaign_list.selection_set(schedule)
        self.app._edit_inline_notes(schedule)
        self.app.home_notes.insert('1.0', 'Unsaved note stays here')
        canvas = self.app.campaign_list.canvas
        for mode, palette in PALETTES.items():
            self.app.appearance_menu.invoke(list(PALETTES).index(mode))
            self.app.update()
            self.assertEqual(self.app.appearance_mode.get(), mode)
            self.assertEqual(self.app.home_notes.cget('background'), palette['surface'])
            self.assertEqual(canvas.cget('background'), palette['surface'])
            self.assertEqual(self.app.home_notes.get('1.0', 'end-1c'), 'Unsaved note stays here')
            self.assertEqual(self.app.campaign_list.selection(), (schedule,))
            self.assertEqual(self.store.get_setting('appearance'), mode)
            self.assertIn(mode, self.app.appearance_label.get())
        self.assertEqual(self.errors, [])

    def test_new_widgets_and_open_dialogs_follow_current_palette(self):
        schedule = self.store.create('November')
        self.app._change_appearance('Miami Vice')
        self.app._open_campaign(schedule)
        self.app._performer_row('Alex', '11/3/2026')
        entry = self.app.performers[0][1]
        self.assertEqual(entry.cget('background'), PALETTES['Miami Vice']['surface'])
        dialog = tk.Toplevel(self.app)
        field = tk.Text(dialog)
        field.pack()
        chooser = ttk.Combobox(dialog, values=['One', 'Two'], state='readonly')
        chooser.pack()
        field.insert('1.0', 'Dialog draft')
        self.app._change_appearance('Default')
        self.app.update()
        self.assertEqual(entry.cget('background'), PALETTES['Default']['surface'])
        self.assertEqual(field.cget('background'), PALETTES['Default']['surface'])
        self.assertEqual(field.get('1.0', 'end-1c'), 'Dialog draft')
        self.assertEqual(self.errors, [])
        dialog.destroy()

    def test_selected_mode_returns_after_restart(self):
        from main import AvailabilityApp
        for mode in ('Miami Vice', 'Rose Quartz', 'Crimson Noir'):
            with self.subTest(mode=mode):
                self.app._change_appearance(mode)
                self.app._close()
                self.app = AvailabilityApp(store=CampaignStore(self.store.path))
                self.app.update()
                self.assertEqual(self.app.appearance_mode.get(), mode)
                self.assertEqual(self.app.notes_text.cget('background'), PALETTES[mode]['surface'])
                self.assertTrue(self.app.appearance_button.winfo_ismapped())

    def test_appearance_bar_stays_at_bottom_on_both_screens(self):
        for mode in PALETTES:
            self.app._change_appearance(mode)
            self.app.update()
            bar = self.app.appearance_footer
            self.assertTrue(bar.winfo_ismapped())
            self.assertEqual(bar.winfo_y() + bar.winfo_height(), self.app.winfo_height())
            self.assertTrue(self.app.appearance_button.winfo_ismapped())
        schedule = self.store.create('November')
        self.app._open_campaign(schedule)
        self.app.update()
        self.assertTrue(self.app.appearance_footer.winfo_ismapped())
        self.assertEqual(self.app.appearance_footer.winfo_y() + self.app.appearance_footer.winfo_height(),
                         self.app.winfo_height())


    def test_dropdown_has_five_modes_and_default_has_white_blue_and_green(self):
        from appearance import PALETTES
        menu = self.app.appearance_menu
        self.assertEqual([menu.entrycget(index, 'label') for index in range(5)],
                         ['Default', 'Dark', 'Miami Vice', 'Rose Quartz', 'Crimson Noir'])
        self.assertEqual(str(self.app.appearance_button.cget('direction')), 'above')
        menu.invoke(0)
        self.app.update()
        self.assertEqual(self.app.cget('background'), '#ffffff')
        self.assertEqual(self.app.notes_text.cget('background'), '#ffffff')
        style = ttk.Style(self.app)
        self.assertEqual(style.lookup('Primary.TButton', 'background'), PALETTES['Default']['primary'])
        self.assertEqual(style.lookup('Success.TButton', 'background'), PALETTES['Default']['success'])
        self.assertNotEqual(style.lookup('Primary.TButton', 'background'), style.lookup('Success.TButton', 'background'))

    def test_legacy_light_setting_opens_as_default(self):
        from main import AvailabilityApp
        self.app._close()
        self.store.set_setting('appearance', 'Light')
        self.app = AvailabilityApp(store=CampaignStore(self.store.path))
        self.app.update()
        self.assertEqual(self.app.appearance_mode.get(), 'Default')
        self.assertIn('Default', self.app.appearance_label.get())
        self.assertEqual(self.app.notes_text.cget('background'), '#ffffff')

    def test_failed_preference_save_restores_menu_selection(self):
        from unittest.mock import patch
        before = self.app.appearance_mode.get()
        with patch.object(self.store, 'set_setting', side_effect=OSError('Disk full')), patch('main.messagebox.showerror'):
            self.app.appearance_menu.invoke(1)
        self.assertEqual(self.app.appearance_mode.get(), before)
        self.assertIn(before, self.app.appearance_label.get())
        self.assertEqual(self.errors, [])



if __name__ == '__main__':
    unittest.main()
