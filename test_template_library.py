"""Saved template CRUD and imports into both notes editors and scripts."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from campaigns import CampaignStore


class TemplateStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = CampaignStore(Path(self.temp.name) / 'templates.sqlite3')

    def test_create_rename_edit_and_restart_preserve_text(self):
        tid = self.store.save_template(' Checklist ', 'Stage\nSound\n@dates')
        self.assertEqual(self.store.load_template(tid)['name'], 'Checklist')
        self.store.save_template('Venue checklist', 'Updated\n@performer', tid)
        reopened = CampaignStore(self.store.path)
        self.assertEqual(reopened.load_template(tid)['body'], 'Updated\n@performer')
        self.assertEqual(reopened.list_templates()[0]['name'], 'Venue checklist')

    def test_duplicate_rename_and_invalid_templates_do_not_overwrite_data(self):
        first = self.store.save_template('Alpha', 'Keep me')
        second = self.store.save_template('Beta', 'Keep me too')
        for name, body, tid in (('alpha', 'Overwrite', second), (' ', 'text', first), ('Valid', ' ', first)):
            with self.assertRaises(ValueError):
                self.store.save_template(name, body, tid)
        self.assertEqual(self.store.load_template(first)['body'], 'Keep me')
        self.assertEqual(self.store.load_template(second)['name'], 'Beta')

    def test_delete_template_preserves_imported_schedule_content(self):
        tid = self.store.save_template('Checklist', 'Stage and sound')
        sid = self.store.create('November')
        data = dict(notes='Stage and sound', confirmation_template='Hi @performer')
        self.store.save(sid, data)
        self.store.delete_template(tid)
        self.assertEqual(self.store.list_templates(), [])
        self.assertEqual(self.store.load(sid)['data'], data)
        with self.assertRaises(ValueError):
            self.store.save_template('Old', 'text', tid)


@unittest.skipUnless(os.environ.get('MHW_RUN_GUI_TESTS') == '1', 'Requires a desktop session')
class TemplateLibraryDesktopTests(unittest.TestCase):
    def setUp(self):
        from main import AvailabilityApp
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = CampaignStore(Path(self.temp.name) / 'templates.sqlite3')
        self.schedule = self.store.create('November')
        self.other = self.store.create('December')
        self.checklist = self.store.save_template('Checklist', 'Check stage\nCheck sound')
        self.script = self.store.save_template('Confirmation', 'Hi @performer | @pdates | @count | @schedule')
        self.app = AvailabilityApp(store=self.store)
        self.errors = []
        self.app.report_callback_exception = lambda *args: self.errors.append(args)
        self.addCleanup(self.cleanup_app)
        self.app.update()

    def cleanup_app(self):
        self.app._close()
        self.assertEqual(self.errors, [])

    def import_template(self, button, tid, notes=None):
        menu = button.template_menu
        self.app.tk.call(menu.cget('postcommand'))
        index = [template['id'] for template in self.store.list_templates()].index(tid)
        menu.invoke(index)
        if notes is not None:
            self.app._notes_import_dismissed(notes)
        self.app.update()

    def test_full_schedule_notes_import_appends_saves_and_keeps_resize(self):
        self.app._open_campaign(self.schedule)
        field = self.app.notes_text
        field.insert('1.0', 'Existing note')
        self.import_template(self.app.notes_import, self.checklist, field)
        expected = 'Existing note\nCheck stage\nCheck sound'
        self.assertEqual(field.get('1.0', 'end-1c'), expected)
        self.assertEqual(self.store.load(self.schedule)['data']['notes'], expected)
        self.assertTrue(field.resize_handle.winfo_exists())
        self.app._open_campaign(self.other)
        self.assertEqual(self.app.notes_text.get('1.0', 'end-1c'), '')
        self.import_template(self.app.notes_import, self.checklist, field)
        self.assertEqual(self.store.load(self.other)['data']['notes'], 'Check stage\nCheck sound')

    def test_schedule_tokens_work_in_both_notes_editors_without_performer_context(self):
        tid = self.store.save_template('Schedule fields', '@schedule: @dates | @count booked | @performer | @pdates')
        data = dict(open_dates='11/7/2026, 11/14/2026', notes='Existing', rows=[
            dict(date='2026-11-07T00:00:00', performer='Alex'),
            dict(date='2026-11-14T00:00:00', performer=None)])
        expected = 'Existing\nNovember: 11/7/2026, 11/14/2026 | 1 booked | @performer | @pdates'
        for mode in ('full', 'inline'):
            with self.subTest(mode=mode):
                self.store.save(self.schedule, data)
                if mode == 'full':
                    self.app._open_campaign(self.schedule)
                    self.import_template(self.app.notes_import, tid, self.app.notes_text)
                    self.assertEqual(self.app.notes_text.get('1.0', 'end-1c'), expected)
                    self.app._show_home()
                else:
                    self.app._refresh_campaigns()
                    self.app.update()
                    self.app._edit_inline_notes(self.schedule)
                    field = self.app.home_notes
                    field.focus_force()
                    self.app.update()
                    self.import_template(field.import_button, tid, field)
                    self.assertEqual(field.get('1.0', 'end-1c'), expected)
                    self.app._finish_inline_notes()
                self.assertEqual(self.store.load(self.schedule)['data']['notes'], expected)
        self.assertIn('@dates', self.store.load_template(tid)['body'])

    def test_inline_notes_import_menu_keeps_editor_alive_then_collapses(self):
        self.app._refresh_campaigns()
        self.app._edit_inline_notes(self.schedule)
        field = self.app.home_notes
        field.focus_force()
        self.app.update()
        menu = field.import_button.template_menu
        self.app.tk.call(menu.cget('postcommand'))
        self.app.campaign_list.canvas.focus_force()
        self.app.update()
        self.assertIs(self.app.home_notes, field)
        menu.invoke(0)
        self.app._notes_import_dismissed(field)
        self.app.update()
        self.assertIs(self.app.home_notes, field)
        self.assertEqual(field.get('1.0', 'end-1c'), 'Check stage\nCheck sound')
        self.app.campaign_list.canvas.event_generate('<Button-1>', x=5, y=5)
        self.app.update()
        self.assertIsNone(self.app.home_notes)
        self.assertEqual(self.store.load(self.schedule)['data']['notes'], 'Check stage\nCheck sound')

    def test_confirmation_import_expands_tokens_without_changing_bookings(self):
        self.app._open_campaign(self.schedule)
        self.app.dates_text.insert('1.0', '11/7/2026, 11/14/2026')
        self.app._performer_row('Alex', '11/7/2026, 11/14/2026')
        self.app._generate()
        self.app.update()
        before = list(self.app.rows)
        self.import_template(self.app.confirmation_import, self.script)
        self.assertEqual(self.app.rows, before)
        self.app.confirmations.winfo_children()[0].winfo_children()[0].winfo_children()[1].invoke()
        self.assertEqual(self.app.clipboard_get(), 'Hi Alex | 11/7/2026, 11/14/2026 | 2 | November')
        self.assertEqual(self.store.load(self.schedule)['data']['confirmation_template'], self.store.load_template(self.script)['body'])
        self.app.template_list.selection_set(self.script)
        with patch('main.messagebox.askyesno', return_value=True):
            self.app._delete_saved_template()
        self.assertEqual(self.app.template_text.get('1.0', 'end-1c'), 'Hi @performer | @pdates | @count | @schedule')

    def test_real_template_dialog_creates_and_edits_named_template(self):
        from template_library import TemplateDialog
        def fill_dialog(name, body):
            dialog = next(child for child in self.app.winfo_children() if isinstance(child, TemplateDialog))
            dialog.name_entry.delete(0, 'end')
            dialog.name_entry.insert(0, name)
            dialog.body_text.delete('1.0', 'end')
            dialog.body_text.insert('1.0', body)
            dialog.ok()
        self.app.after(100, lambda: fill_dialog('Travel', 'Parking and travel'))
        self.app._new_saved_template()
        selected = self.app.template_list.selection()[0]
        self.assertEqual(self.store.load_template(selected)['body'], 'Parking and travel')
        self.app.after(100, lambda: fill_dialog('Travel info', 'Updated travel text'))
        self.app._edit_saved_template()
        self.assertEqual(self.app.template_list.item(selected, 'text'), 'Travel info')
        self.assertEqual(self.store.load_template(selected)['body'], 'Updated travel text')

    def test_import_menu_reflects_recent_edits_and_empty_library(self):
        self.store.save_template('Checklist renamed', 'New body', self.checklist)
        self.app._open_campaign(self.schedule)
        menu = self.app.notes_import.template_menu
        self.app.tk.call(menu.cget('postcommand'))
        self.assertEqual(menu.entrycget(0, 'label'), 'Checklist renamed')
        self.app._notes_import_dismissed(self.app.notes_text)
        self.store.delete_template(self.checklist)
        self.store.delete_template(self.script)
        self.app.tk.call(menu.cget('postcommand'))
        self.assertEqual(menu.entrycget(0, 'state'), 'disabled')
        self.app._notes_import_dismissed(self.app.notes_text)

    def test_templates_button_opens_separate_page_and_returns_to_schedules(self):
        self.assertTrue(self.app.home.winfo_ismapped())
        self.assertFalse(self.app.template_list.winfo_ismapped())
        self.app.templates_button.invoke()
        self.app.update()
        self.assertTrue(self.app.templates_page.winfo_ismapped())
        self.assertTrue(self.app.template_list.winfo_ismapped())
        self.assertFalse(self.app.home.winfo_ismapped())
        self.assertIn('Check stage', self.app.template_list.item(self.checklist, 'values')[0])
        self.app._show_home()
        self.app.update()
        self.assertTrue(self.app.home.winfo_ismapped())
        self.assertFalse(self.app.templates_page.winfo_ismapped())

    def test_template_page_navigation_saves_pending_schedule_notes(self):
        self.app._open_campaign(self.schedule)
        self.app.notes_text.insert('1.0', 'Keep this note')
        self.app._show_templates()
        self.app.update()
        self.assertEqual(self.store.load(self.schedule)['data']['notes'], 'Keep this note')
        self.assertTrue(self.app.templates_page.winfo_ismapped())
        self.app._open_campaign(self.schedule)
        self.app.update()
        self.assertFalse(self.app.templates_page.winfo_ismapped())
        self.assertTrue(self.app.page.winfo_ismapped())
