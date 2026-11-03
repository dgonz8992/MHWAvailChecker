"""Persistence regression tests; desktop checks opt in with MHW_RUN_GUI_TESTS=1."""
import os
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from campaigns import CampaignStore


class CampaignStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'nested/campaigns.sqlite3'
        self.store = CampaignStore(self.path)

    def test_restart_preserves_names_raw_inputs_and_generated_schedule(self):
        campaign = self.store.create(' November 🎵 ')
        data = {'open_dates': '11/3/2026', 'minimum_gap': '7',
                'performers': [{'name': 'Alex', 'availability': '11/3'}],
                'rows': [{'date': '2026-11-03T00:00:00', 'performer': 'Alex'}]}
        self.store.save(campaign, data)
        reopened = CampaignStore(self.path).load(campaign)
        self.assertEqual(reopened['name'], 'November 🎵')
        self.assertEqual(reopened['data'], data)

    def test_campaigns_with_same_name_are_independent(self):
        first = self.store.create('November')
        second = self.store.create('November')
        self.store.save(first, {'open_dates': '11/3/2026'})
        self.assertEqual(self.store.load(second)['data'], {})
        self.store.rename(first, 'December')
        self.assertEqual(self.store.load(second)['name'], 'November')
        self.store.delete(first)
        self.assertEqual([row['id'] for row in self.store.list_campaigns()], [second])

    def test_blank_name_is_rejected_without_modifying_campaign(self):
        with self.assertRaises(ValueError):
            self.store.create('  ')
        campaign = self.store.create('November')
        with self.assertRaises(ValueError):
            self.store.rename(campaign, '\n')
        self.assertEqual(self.store.load(campaign)['name'], 'November')

    def test_missing_campaign_is_not_silently_recreated(self):
        for operation in (lambda: self.store.load('missing'), lambda: self.store.save('missing', {}),
                          lambda: self.store.rename('missing', 'Name'), lambda: self.store.delete('missing')):
            with self.assertRaises(ValueError):
                operation()

    def test_failed_serialization_preserves_previous_save(self):
        campaign = self.store.create('November')
        self.store.save(campaign, {'open_dates': 'draft'})
        with self.assertRaises(TypeError):
            self.store.save(campaign, {'bad': object()})
        self.assertEqual(self.store.load(campaign)['data'], {'open_dates': 'draft'})

    def test_corrupt_database_is_not_overwritten(self):
        self.path.write_bytes(b'broken database')
        with self.assertRaises(sqlite3.DatabaseError):
            CampaignStore(self.path)
        self.assertEqual(self.path.read_bytes(), b'broken database')

    def test_legacy_database_is_upgraded_without_changing_saved_schedules(self):
        old = Path(self.temp.name) / 'legacy.sqlite3'
        with closing(sqlite3.connect(old)) as connection, connection:
            connection.execute('CREATE TABLE campaigns (id TEXT PRIMARY KEY, name TEXT, data TEXT, updated_at TEXT)')
            connection.execute("INSERT INTO campaigns VALUES ('old', 'Existing schedule', '{\"notes\": \"Keep me\", \"group\": \"Old group\"}', '2026-11-03T00:00:00+00:00')")
        upgraded = CampaignStore(old)
        listed = upgraded.list_campaigns()[0]
        self.assertIsNone(listed['folder_id'])
        self.assertEqual(listed['notes'], 'Keep me')
        self.assertEqual(upgraded.list_campaigns(folder_id='')[0]['id'], 'old')
        self.assertEqual(upgraded.list_folders(), [])

    def test_folders_persist_when_empty_and_can_be_renamed(self):
        folder = self.store.create_folder(' November shows ')
        self.assertEqual(CampaignStore(self.path).list_folders()[0]['name'], 'November shows')
        self.store.rename_folder(folder, 'Holiday shows')
        self.assertEqual(self.store.list_folders()[0]['id'], folder)
        self.assertEqual(self.store.list_folders()[0]['name'], 'Holiday shows')
        with self.assertRaises(ValueError):
            self.store.create_folder('holiday SHOWS')

    def test_search_matches_saved_and_draft_performers_within_selected_folder(self):
        folder = self.store.create_folder('Downtown')
        saved = self.store.create('November', folder)
        draft = self.store.create('December')
        self.store.save(saved, {'performers': [{'name': 'Pedro Méndez', 'availability': '11/3/2026'}]})
        self.store.save(draft, {'availability_drafts': [{'id': 'draft', 'name': 'Pedro Miller', 'availability': ''}]})
        self.assertEqual({row['id'] for row in self.store.list_campaigns('PEDRO')}, {saved, draft})
        self.assertEqual([row['id'] for row in self.store.list_campaigns(' MÉNDEZ ')], [saved])
        self.assertEqual([row['id'] for row in self.store.list_campaigns('pedro', folder)], [saved])
        self.assertEqual(self.store.list_campaigns('miller', folder), [])
        self.assertEqual(self.store.list_campaigns('11/3/2026'), [])
        self.store.save_inline_drafts(draft, [])
        self.assertEqual(self.store.list_campaigns('miller'), [])

    def test_folders_search_and_notes_combine(self):
        folder = self.store.create_folder('Downtown')
        first = self.store.create('November', folder)
        self.store.create('January')
        notes = 'Confirm sound system\nAsk venue about parking 🎵'
        self.store.set_notes(first, notes)
        self.assertEqual([row['id'] for row in self.store.list_campaigns('PARKING', folder)], [first])
        self.assertEqual(self.store.list_campaigns('January', folder), [])
        self.assertEqual(self.store.load(first)['data']['notes'], notes)
        self.store.rename_folder(folder, 'Uptown')
        self.assertEqual(self.store.list_campaigns('Uptown')[0]['id'], first)

    def test_bulk_moves_are_atomic_and_preserve_schedule_data(self):
        first = self.store.create('November')
        second = self.store.create('January')
        folder = self.store.create_folder('Downtown')
        data = {'notes': 'Keep me', 'rows': [{'performer': 'Alex'}]}
        self.store.save(first, data)
        self.store.move_to_folder([first, second], folder)
        self.assertEqual(len(self.store.list_campaigns(folder_id=folder)), 2)
        self.assertEqual(self.store.load(first)['data'], data)
        with self.assertRaises(ValueError):
            self.store.move_to_folder([first, 'missing'], None)
        self.assertEqual(self.store.load(first)['folder_id'], folder)
        self.store.move_to_folder([first], None)
        self.assertEqual(self.store.list_campaigns(folder_id='')[0]['id'], first)
        self.store.set_notes(first, 'New note')
        self.assertEqual(self.store.load(first)['data']['rows'], data['rows'])


    def test_delete_folder_preserves_all_schedules_and_their_contents(self):
        folder = self.store.create_folder('Downtown')
        other = self.store.create_folder('Keep this folder')
        first = self.store.create('November', folder)
        second = self.store.create('January', folder)
        elsewhere = self.store.create('Other show', other)
        data = {'notes': 'Keep the notes', 'rows': [{'date': '2026-11-03', 'performer': 'Alex'}]}
        self.store.save(first, data)
        self.store.delete_folder(folder)
        self.assertEqual({row['id'] for row in self.store.list_campaigns(folder_id='')}, {first, second})
        self.assertEqual(self.store.load(first)['data'], data)
        self.assertEqual(self.store.load(elsewhere)['folder_id'], other)
        self.assertEqual(self.store.list_folders(), [{'id': other, 'name': 'Keep this folder'}])
        for invalid in (None, '', 'missing'):
            with self.assertRaises(ValueError):
                self.store.delete_folder(invalid)
        self.store.delete_folder(other)
        self.assertEqual(len(self.store.list_campaigns()), 3)


    def test_folder_order_survives_restart_rename_create_and_delete(self):
        first = self.store.create_folder('First')
        second = self.store.create_folder('Second')
        third = self.store.create_folder('Third')
        schedule = self.store.create('November', second)
        self.store.reorder_folders([third, first, second])
        self.store.rename_folder(third, 'Z last alphabetically')
        reopened = CampaignStore(self.path)
        self.assertEqual([row['id'] for row in reopened.list_folders()], [third, first, second])
        newest = reopened.create_folder('A new folder')
        self.assertEqual([row['id'] for row in reopened.list_folders()], [third, first, second, newest])
        reopened.delete_folder(first)
        self.assertEqual([row['id'] for row in reopened.list_folders()], [third, second, newest])
        self.assertEqual(reopened.load(schedule)['folder_id'], second)
        for invalid in ([third, second], [third, second, second], [third, second, 'missing']):
            with self.assertRaises(ValueError):
                reopened.reorder_folders(invalid)
        self.assertEqual([row['id'] for row in reopened.list_folders()], [third, second, newest])

    def test_legacy_folder_order_migrates_alphabetically(self):
        old = Path(self.temp.name) / 'old-folders.sqlite3'
        with closing(sqlite3.connect(old)) as connection, connection:
            connection.execute('CREATE TABLE folders (id TEXT PRIMARY KEY, name TEXT NOT NULL)')
            connection.executemany('INSERT INTO folders VALUES (?, ?)', [('z', 'Zulu'), ('a', 'Alpha'), ('b', 'beta')])
        store = CampaignStore(old)
        self.assertEqual([row['id'] for row in store.list_folders()], ['a', 'b', 'z'])
        store.reorder_folders(['z', 'b', 'a'])
        self.assertEqual([row['id'] for row in CampaignStore(old).list_folders()], ['z', 'b', 'a'])



@unittest.skipUnless(os.environ.get('MHW_RUN_GUI_TESTS') == '1', 'Requires a desktop session')
class CampaignDesktopTests(unittest.TestCase):
    def setUp(self):
        from main import AvailabilityApp
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = CampaignStore(Path(self.temp.name) / 'campaigns.sqlite3')
        self.app = AvailabilityApp(store=self.store)
        self.errors = []
        self.app.report_callback_exception = lambda *args: self.errors.append(args)
        self.addCleanup(self.cleanup_app)
        self.app.update()
        self.first = self.store.create('November')
        self.second = self.store.create('January')

    def cleanup_app(self):
        if self.app.winfo_exists():
            self.app._close()
        self.assertEqual(self.errors, [])

    def fill_schedule(self):
        self.app._open_campaign(self.first)
        self.app.dates_text.insert('1.0', '11/3/2026, 11/10/2026, 12/1/2026, 1/4/2027')
        self.app._performer_row('Alex', '11/3/2026, 11/10/2026')
        self.app._performer_row('Sam', '1/4/2027')
        self.app._generate()
        self.app.update()

    def test_home_switching_and_restart_restore_exact_schedule_and_scripts(self):
        self.assertTrue(self.app.home.winfo_ismapped())
        self.fill_schedule()
        expected_rows = list(self.app.rows)
        expected_totals = self.app.totals.get()
        self.assertEqual(len(self.app.confirmations.winfo_children()), 2)
        self.app._show_home()
        self.assertEqual(len(self.app.campaign_list.get_children()), 2)
        self.app._open_campaign(self.second)
        self.assertEqual(self.app.performers, [])
        self.assertEqual(self.app.rows, [])
        self.app._close()
        from main import AvailabilityApp
        self.app = AvailabilityApp(store=CampaignStore(self.store.path))
        self.app.report_callback_exception = lambda *args: self.errors.append(args)
        self.app._open_campaign(self.first)
        self.app.update()
        self.assertEqual(self.app.rows, expected_rows)
        self.assertEqual(self.app.totals.get(), expected_totals)
        self.assertEqual(len(self.app.names_table.get_children()), 4)
        frames = self.app.confirmations.winfo_children()
        self.assertEqual(len(frames), 2)
        frames[0].winfo_children()[0].winfo_children()[1].invoke()
        self.assertIn('Confirmed for 11/3/2026, 11/10/2026.', self.app.clipboard_get())
        frames[1].winfo_children()[0].winfo_children()[1].invoke()
        self.assertIn('Confirmed for 1/4/2027.', self.app.clipboard_get())

    def test_another_arrangement_updates_names_scripts_and_saved_schedule(self):
        self.app._open_campaign(self.first)
        self.assertTrue(self.app.alternate_button.instate(['disabled']))
        dates = '11/3/2026, 11/10/2026, 11/17/2026'
        self.app.dates_text.insert('1.0', dates)
        for name in ('Alex', 'Tyler', 'Sarah'):
            self.app._performer_row(name, dates)
        self.app._generate()
        before = list(self.app.rows)
        self.app.alternate_button.invoke()
        expected = list(self.app.rows)
        self.assertNotEqual(expected, before)
        self.assertEqual([self.app.names_table.item(item, 'values')[0]
                          for item in self.app.names_table.get_children()], [name for _, name in expected])
        for frame in self.app.confirmations.winfo_children():
            header = frame.winfo_children()[0]
            name = header.winfo_children()[0].cget('text')
            header.winfo_children()[1].invoke()
            date = next(date for date, person in expected if person == name)
            self.assertIn(f'Confirmed for {date.month}/{date.day}/{date.year}.', self.app.clipboard_get())
        self.app._show_home()
        self.app._open_campaign(self.first)
        self.assertEqual(self.app.rows, expected)
        self.assertTrue(self.app.alternate_button.instate(['!disabled']))
        self.app.gap.set('8')
        self.assertTrue(self.app.alternate_button.instate(['disabled']))

    def test_try_another_arrangement_keeps_forced_schedule_and_reports_no_alternative(self):
        self.app._open_campaign(self.first)
        self.app.dates_text.insert('1.0', '11/3/2026')
        self.app._performer_row('Alex', '11/3/2026')
        self.app._generate()
        before = list(self.app.rows)
        self.app.alternate_button.invoke()
        self.assertEqual(self.app.rows, before)
        self.assertEqual(len(self.app.table.get_children()), 1)
        self.assertIn('Current schedule kept', self.app.arrangement_status.get())

    def test_autosave_keeps_unfinished_input_and_excludes_api_key(self):
        self.app._open_campaign(self.first)
        self.app.ai_api_key.set('do-not-store-this')
        self.app.dates_text.insert('1.0', 'unfinished date draft')
        self.app.gap.set('not yet a number')
        self.app.after(700, self.app.quit)
        self.app.mainloop()
        data = self.store.load(self.first)['data']
        self.assertEqual(data['open_dates'], 'unfinished date draft')
        self.assertEqual(data['minimum_gap'], 'not yet a number')
        self.assertNotIn('do-not-store-this', str(data))

    def test_immediate_navigation_flushes_pending_edit_and_removes_stale_schedule(self):
        self.fill_schedule()
        self.app.dates_text.insert('end', ', unfinished')
        self.app._show_home()
        data = self.store.load(self.first)['data']
        self.assertTrue(data['open_dates'].endswith(', unfinished'))
        self.assertEqual(data['rows'], [])
        self.app._open_campaign(self.first)
        self.app.update()
        self.assertEqual(self.app.rows, [])

    def test_failed_save_blocks_navigation_and_close_until_retry(self):
        self.app._open_campaign(self.first)
        self.app.dates_text.insert('1.0', 'draft')
        with patch.object(self.store, 'save', side_effect=OSError('Disk full')), patch('main.messagebox.showerror'):
            self.app._show_home()
            self.assertEqual(self.app.campaign_id, self.first)
            self.app._close()
            self.assertTrue(self.app.winfo_exists())
            self.assertTrue(self.app._dirty)
        self.assertTrue(self.app._save_campaign())
        self.assertEqual(self.store.load(self.first)['data']['open_dates'], 'draft')

    def test_rename_and_delete_controls(self):
        self.app._open_campaign(self.first)
        with patch('main.simpledialog.askstring', return_value='Holiday bookings'):
            self.app._rename_active()
        self.assertEqual(self.app.campaign_name.get(), 'Holiday bookings')
        self.app._show_home()
        self.app.campaign_list.selection_set(self.first)
        with patch('main.messagebox.askyesno', return_value=False):
            self.app._delete_selected()
        self.assertEqual(self.store.load(self.first)['name'], 'Holiday bookings')
        with patch('main.messagebox.askyesno', return_value=True):
            self.app._delete_selected()
        self.assertEqual([row['id'] for row in self.store.list_campaigns()], [self.second])

    def test_notes_editor_opens_in_row_and_restores_compact_preview(self):
        self.app._refresh_campaigns()
        self.assertIsNone(self.app.home_notes)
        label = self.app.campaign_list._items[self.first]['notes']
        self.assertTrue(label.bind('<Double-1>'))
        self.app._edit_inline_notes(self.first)
        self.assertIs(self.app.home_notes.frame.master, label.master)
        self.app.home_notes.insert('1.0', 'Inline notes\nSecond line')
        self.assertTrue(self.app._finish_inline_notes())
        self.assertIsNone(self.app.home_notes)
        self.app.update()
        self.assertTrue(label.winfo_ismapped())
        self.assertEqual(label.cget('text'), 'Inline notes Second line')
        self.assertEqual(self.store.load(self.first)['data']['notes'], 'Inline notes\nSecond line')
        self.assertEqual(self.errors, [])

    def test_entire_notes_cell_opens_and_clicking_blank_space_reveals_saved_preview(self):
        self.app._refresh_campaigns()
        self.app.update()
        label = self.app.campaign_list._items[self.first]['notes']
        for x in (3, label.winfo_width() - 3):
            label.event_generate('<Button-1>', x=x, y=label.winfo_height() - 2)
            self.assertIsNotNone(self.app.home_notes)
            field = self.app.home_notes
            wrapper = field.frame
            field.focus_force()
            self.app.update()
            field.delete('1.0', 'end')
            field.insert('1.0', 'Visible after finishing')
            self.app.campaign_list.canvas.event_generate('<Button-1>', x=5, y=200)
            self.app.update()
            self.assertIsNone(self.app.home_notes)
            self.assertFalse(wrapper.winfo_exists())
            self.assertTrue(label.winfo_ismapped())
            self.assertEqual(label.cget('text'), 'Visible after finishing')
            self.assertEqual(self.store.load(self.first)['data']['notes'], 'Visible after finishing')
        self.assertEqual(self.errors, [])

    def test_notes_on_both_screens_stay_in_sync_without_clearing_bookings(self):
        self.fill_schedule()
        expected_rows = list(self.app.rows)
        self.app.notes_text.insert('1.0', 'Ask venue about parking\nBring extra cables')
        self.app._show_home()
        self.app.campaign_list.selection_set(self.first)
        self.app.update()
        self.app._edit_inline_notes(self.first)
        self.assertEqual(self.app.home_notes.get('1.0', 'end-1c'), 'Ask venue about parking\nBring extra cables')
        self.app.home_notes.insert('end', '\nCheck microphone')
        self.app._open_campaign(self.first)
        self.app.update()
        self.assertEqual(self.app.rows, expected_rows)
        self.assertTrue(self.app.notes_text.get('1.0', 'end-1c').endswith('Check microphone'))
        self.app.notes_text.insert('end', '\nConfirm stage')
        self.app._show_home()
        self.app.update()
        self.app._edit_inline_notes(self.first)
        self.assertTrue(self.app.home_notes.get('1.0', 'end-1c').endswith('Confirm stage'))
        self.assertEqual(len(self.store.load(self.first)['data']['rows']), 4)

    def test_folders_switch_create_rename_and_move(self):
        with patch('main.simpledialog.askstring', return_value='Downtown'):
            self.app._new_folder()
        self.app.update()
        folder = self.app.active_folder
        self.assertTrue(folder)
        self.assertEqual(self.app.campaign_list.get_children(), ())
        with patch('main.simpledialog.askstring', return_value='Night shows'):
            self.app._new_campaign()
        self.assertEqual(self.store.load(self.app.campaign_id)['folder_id'], folder)
        self.app._show_home()
        self.app.update()
        with patch('main.simpledialog.askstring', return_value='Uptown'):
            self.app._rename_folder()
        self.assertEqual(self.store.list_folders()[0]['name'], 'Uptown')
        self.app.folder_list.selection_set('all')
        self.app.update()
        self.assertIsNone(self.app.active_folder)
        self.app.campaign_list.selection_set([self.first, self.second])
        self.app._move_selected()
        self.app.update()
        import tkinter as tk
        dialog = next(child for child in self.app.winfo_children() if isinstance(child, tk.Toplevel))
        outer = dialog.winfo_children()[0]
        chooser = outer.winfo_children()[1]
        chooser.current(1)
        buttons = outer.winfo_children()[2]
        buttons.winfo_children()[0].invoke()
        self.app.folder_list.selection_set(folder)
        self.app.update()
        self.assertEqual(len(self.app.campaign_list.get_children()), 3)
        self.app.schedule_search.set('November')
        self.assertEqual(self.app.campaign_list.get_children(), (self.first,))
        self.app._clear_filters()
        self.assertEqual(len(self.app.campaign_list.get_children()), 3)

    def test_main_notes_save_before_changing_selection_or_folder(self):
        self.app._refresh_campaigns()
        self.app.campaign_list.selection_set(self.first)
        self.app._edit_inline_notes(self.first)
        self.app.home_notes.insert('1.0', 'First note')
        self.app.campaign_list.selection_set(self.second)
        self.assertEqual(self.store.load(self.first)['data']['notes'], 'First note')
        self.app._edit_inline_notes(self.second)
        self.app.home_notes.insert('1.0', 'Second note')
        folder = self.store.create_folder('Empty folder')
        self.app._refresh_folders()
        self.app.folder_list.selection_set(folder)
        self.app.update()
        self.assertEqual(self.store.load(self.second)['data']['notes'], 'Second note')
        self.assertIsNone(self.app.home_notes)

    def test_main_notes_autosave_and_failed_save_keeps_notes_open(self):
        self.app._refresh_campaigns()
        self.app.campaign_list.selection_set(self.first)
        self.app._edit_inline_notes(self.first)
        self.app.home_notes.insert('1.0', 'Autosave this note')
        self.app.after(700, self.app.quit)
        self.app.mainloop()
        self.assertEqual(self.store.load(self.first)['data']['notes'], 'Autosave this note')
        self.app._edit_inline_notes(self.first)
        self.app.home_notes.insert('end', ' changed')
        with patch.object(self.store, 'set_notes', side_effect=OSError('Disk full')), patch('main.messagebox.showerror'):
            self.app.campaign_list.selection_set(self.second)
            self.assertEqual(self.app.campaign_list.selection(), (self.first,))
            self.assertTrue(self.app.home_notes.get('1.0', 'end-1c').endswith('changed'))
        self.assertTrue(self.app._save_home_notes())

    def test_compact_rows_have_native_dividers_and_no_colored_tags(self):
        self.app._refresh_campaigns()
        from tkinter import ttk
        frames = self.app.campaign_list.content.winfo_children()
        self.assertEqual(len(frames), 2)
        for frame in frames:
            self.assertIsInstance(frame.winfo_children()[-1], ttk.Separator)


    def test_context_menu_expands_and_collapses_all_visible_schedules_and_saves_drafts(self):
        import tkinter as tk
        from types import SimpleNamespace
        self.app._refresh_campaigns()
        with patch.object(tk.Menu, 'tk_popup'):
            self.app._schedule_context_menu(self.first, SimpleNamespace(x_root=10, y_root=10))
        menu = self.app._active_copy_menu
        menu.invoke('Expand all')
        self.app.update()
        for schedule in (self.first, self.second):
            self.assertTrue(self.app._inline_editor(schedule).winfo_ismapped())
        editor = self.app._inline_editor(self.first)
        editor.rows[0]['name'].set('Pedro Mendez')
        editor.rows[0]['text'].insert('1.0', 'November 3')
        menu.invoke('Collapse all')
        self.app.update()
        for schedule in (self.first, self.second):
            self.assertFalse(self.app._inline_editor(schedule).winfo_ismapped())
        self.assertEqual(self.store.load(self.first)['data']['availability_drafts'][0]['name'], 'Pedro Mendez')
        self.app.schedule_search.set('Pedro')
        self.app._set_all_schedules_expanded(True)
        self.app.update()
        self.assertEqual(self.app.campaign_list.get_children(), (self.first,))
        self.assertTrue(self.app._inline_editor(self.first).winfo_ismapped())
        self.app._clear_filters()
        self.app.update()
        self.assertFalse(self.app._inline_editor(self.second))

    def test_context_menu_targets_clicked_schedule_and_saves_pending_notes(self):
        import tkinter as tk
        self.app._refresh_campaigns()
        self.app.campaign_list.selection_set(self.first)
        self.app._edit_inline_notes(self.first)
        self.app.home_notes.insert('1.0', 'Save before opening menu')
        self.app.update()
        row = self.app.campaign_list._items[self.second]['name']
        with patch.object(tk.Menu, 'tk_popup'):
            row.event_generate('<Button-3>', x=5, y=5)
        menu = self.app._active_copy_menu
        self.assertEqual([menu.entrycget(index, 'label') for index in (0, 1, 2, 4)],
                         ['Open', 'Rename…', 'Move to folder…', 'Delete…'])
        self.assertEqual(self.app.campaign_list.selection(), (self.second,))
        self.assertEqual(self.store.load(self.first)['data']['notes'], 'Save before opening menu')
        with patch.object(self.app, '_open_campaign') as open_schedule:
            menu.invoke(0)
            open_schedule.assert_called_once_with(self.second)
        with patch('main.simpledialog.askstring', return_value='Renamed from menu'):
            menu.invoke(1)
        self.assertEqual(self.store.load(self.second)['name'], 'Renamed from menu')
        self.assertEqual(self.store.load(self.first)['name'], 'November')
        with patch.object(self.app, '_move_selected') as move:
            menu.invoke(2)
            move.assert_called_once_with((self.second,))
        with patch('main.messagebox.askyesno', return_value=False):
            menu.invoke(4)
        self.assertEqual(self.store.load(self.second)['name'], 'Renamed from menu')
        with patch('main.messagebox.askyesno', return_value=True):
            menu.invoke(4)
        self.assertEqual([row['id'] for row in self.store.list_campaigns()], [self.first])
        self.assertEqual(self.errors, [])

    def test_mac_context_clicks_do_not_toggle_selected_checkbox_or_open_copy_menu(self):
        import tkinter as tk
        if self.app.tk.call('tk', 'windowingsystem') != 'aqua':
            self.skipTest('Mac-specific click gestures')
        self.app._refresh_campaigns()
        self.app.campaign_list.selection_set(self.first)
        self.app.update()
        row = self.app.campaign_list._items[self.first]['frame'].winfo_children()[0]
        checkbox = row.winfo_children()[0]
        for sequence in ('<Button-3>', '<Button-2>', '<Control-Button-1>'):
            with patch.object(tk.Menu, 'tk_popup'):
                checkbox.event_generate(sequence, x=5, y=5)
            self.assertEqual(self.app.campaign_list.selection(), (self.first,))
            self.assertEqual(self.app._active_copy_menu.entrycget(0, 'label'), 'Open')
        self.assertEqual(self.errors, [])

    def test_context_menu_preserves_multiple_checked_schedules_for_move(self):
        import tkinter as tk
        self.app._refresh_campaigns()
        self.app.campaign_list.selection_set([self.first, self.second])
        self.app.update()
        with patch.object(tk.Menu, 'tk_popup'):
            self.app.campaign_list._items[self.first]['name'].event_generate('<Button-3>', x=5, y=5)
        menu = self.app._active_copy_menu
        self.assertEqual(menu.entrycget(2, 'label'), 'Move 2 schedules to folder…')
        with patch.object(self.app, '_move_selected') as move:
            menu.invoke(2)
            self.assertEqual(set(move.call_args.args[0]), {self.first, self.second})
        with patch.object(self.app, '_rename_campaign') as rename:
            menu.invoke(1)
            rename.assert_called_once_with(self.first)
        self.assertEqual(self.errors, [])


    def test_folder_context_menu_targets_clicked_folder_and_preserves_schedules(self):
        import tkinter as tk
        first_folder = self.store.create_folder('First folder')
        second_folder = self.store.create_folder('Second folder')
        self.store.move_to_folder([self.first], second_folder)
        self.app.active_folder = first_folder
        self.app._refresh_campaigns()
        self.app.update()
        x, y, width, height = self.app.folder_list.bbox(second_folder)
        with patch.object(tk.Menu, 'tk_popup'):
            self.app.folder_list.event_generate('<Button-3>', x=x + 10, y=y + height // 2)
        menu = self.app._active_copy_menu
        self.assertEqual([menu.entrycget(index, 'label') for index in (0, 1, 3)],
                         ['Open', 'Rename…', 'Delete folder…'])
        self.assertEqual(self.app.active_folder, first_folder)
        with patch('main.simpledialog.askstring', return_value='Renamed folder'):
            menu.invoke(1)
        self.assertEqual({row['id']: row['name'] for row in self.store.list_folders()}[second_folder], 'Renamed folder')
        with patch('main.messagebox.askyesno', return_value=False):
            menu.invoke(3)
        self.assertEqual(len(self.store.list_folders()), 2)
        with patch('main.messagebox.askyesno', return_value=True):
            menu.invoke(3)
        self.assertEqual(self.store.load(self.first)['folder_id'], None)
        self.assertEqual(self.app.active_folder, first_folder)
        self.assertEqual(self.errors, [])

    def test_deleting_open_folder_flushes_notes_and_shows_all(self):
        folder = self.store.create_folder('Downtown')
        self.store.move_to_folder([self.first], folder)
        self.app.active_folder = folder
        self.app._refresh_campaigns()
        self.app.campaign_list.selection_set(self.first)
        self.app._edit_inline_notes(self.first)
        self.app.home_notes.insert('1.0', 'Save before deleting folder')
        with patch('main.messagebox.askyesno', return_value=True):
            self.app._delete_folder(folder)
        self.app.update()
        self.assertIsNone(self.app.active_folder)
        self.assertEqual(self.app.folder_list.selection(), ('all',))
        self.assertFalse(self.app.folder_list.exists('unfiled'))
        self.assertEqual(self.store.load(self.first)['data']['notes'], 'Save before deleting folder')
        self.assertIn(self.first, self.app.campaign_list.get_children())
        self.assertEqual(self.errors, [])

    def test_builtin_folder_views_cannot_be_renamed_or_deleted_from_menu(self):
        import tkinter as tk
        self.app.update()
        for builtin in ('all',):
            x, y, width, height = self.app.folder_list.bbox(builtin)
            with patch.object(tk.Menu, 'tk_popup'):
                self.app.folder_list.event_generate('<Button-3>', x=x + 10, y=y + height // 2)
            menu = self.app._active_copy_menu
            self.assertEqual(menu.entrycget(1, 'state'), 'disabled')
            self.assertEqual(menu.entrycget(3, 'state'), 'disabled')
            menu.invoke(0)
            self.app.update()
            self.assertIsNone(self.app.active_folder)
        self.assertEqual(self.errors, [])


    def test_dragging_folders_saves_order_and_keeps_all_schedules_pinned(self):
        first = self.store.create_folder('First')
        second = self.store.create_folder('Second')
        third = self.store.create_folder('Third')
        self.store.move_to_folder([self.first], third)
        self.app._refresh_campaigns()
        self.app.update()
        tree = self.app.folder_list
        _, y, _, height = tree.bbox(third)
        tree.event_generate('<ButtonPress-1>', x=30, y=y + height // 2)
        self.app.update()
        _, destination_y, _, _ = tree.bbox(first)
        tree.event_generate('<B1-Motion>', x=30, y=destination_y + 2)
        tree.event_generate('<ButtonRelease-1>', x=30, y=destination_y + 2)
        self.app.update()
        self.assertEqual(tree.get_children(), ('all', third, first, second))
        self.assertEqual([row['id'] for row in CampaignStore(self.store.path).list_folders()], [third, first, second])
        self.assertEqual(self.app.active_folder, third)
        self.assertEqual(self.store.load(self.first)['folder_id'], third)
        self.assertIn(self.first, self.app.campaign_list.get_children())
        _, y, _, height = tree.bbox('all')
        tree.event_generate('<ButtonPress-1>', x=30, y=y + height // 2)
        tree.event_generate('<B1-Motion>', x=30, y=tree.winfo_height() - 10)
        tree.event_generate('<ButtonRelease-1>', x=30, y=tree.winfo_height() - 10)
        self.assertEqual(tree.get_children()[0], 'all')
        self.assertEqual(self.errors, [])

    def test_failed_folder_order_save_restores_previous_order(self):
        first = self.store.create_folder('First')
        second = self.store.create_folder('Second')
        self.app._refresh_campaigns()
        self.app.update()
        tree = self.app.folder_list
        _, y, _, height = tree.bbox(second)
        tree.event_generate('<ButtonPress-1>', x=30, y=y + height // 2)
        self.app.update()
        _, target_y, _, _ = tree.bbox(first)
        tree.event_generate('<B1-Motion>', x=30, y=target_y + 2)
        with patch.object(self.store, 'reorder_folders', side_effect=OSError('Disk full')), patch('main.messagebox.showerror'):
            tree.event_generate('<ButtonRelease-1>', x=30, y=target_y + 2)
        self.assertEqual(tree.get_children(), ('all', first, second))
        self.assertEqual(self.errors, [])



if __name__ == '__main__':
    unittest.main()
