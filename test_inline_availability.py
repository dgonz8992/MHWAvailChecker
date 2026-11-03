"""Inline availability persistence and desktop workflow regression checks."""
from datetime import datetime
from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch

from campaigns import CampaignStore
from inline_availability import request_signature, performer_value, format_inline, sync_schedule_performers
from availability_import import ImportResult

NAMES = '''Pedro Mendez
Merry Miller
Colin Priller
Vetted Good Fits
Sarah Navy
Aautumn
Sylvia Greenstein
Ricky Carr
Spicy Violin
Joseph Reding'''
DATES = [datetime(2026, 11, 3), datetime(2026, 11, 10)]


class InlineStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = CampaignStore(Path(self.temp.name) / 'schedules.sqlite3')
        self.schedule = self.store.create('November')
        self.draft = dict(id='row-one', name='pedro mendez', availability='November 3 and 10', status='Draft')
        self.store.save(self.schedule, dict(open_dates='11/3/2026, 11/10/2026', notes='Keep notes',
                                          performers=[dict(name='Pedro Mendez', availability='11/3/2026')],
                                          rows=[dict(date='2026-11-03', performer='Pedro Mendez')],
                                          availability_drafts=[self.draft]))

    def snapshot(self):
        data = self.store.load(self.schedule)['data']
        return dict(name=self.draft['name'], signature=request_signature(self.draft, data),
                    previous_availability=performer_value(data, self.draft['name']), dates=DATES)

    def test_apply_updates_existing_performer_and_preserves_notes_and_draft(self):
        snapshot = self.snapshot()
        self.store.set_notes(self.schedule, 'New notes while AI works')
        self.assertTrue(self.store.apply_inline_result(self.schedule, 'row-one', snapshot, DATES))
        data = CampaignStore(self.store.path).load(self.schedule)['data']
        self.assertEqual(data['performers'], [dict(name='Pedro Mendez', availability='11/3/2026, 11/10/2026')])
        self.assertEqual(data['notes'], 'New notes while AI works')
        self.assertEqual(data['rows'], [])
        self.assertEqual(data['availability_drafts'][0]['availability'], 'November 3 and 10')
        self.assertEqual(data['availability_drafts'][0]['last_applied'], snapshot['signature'])

    def test_late_results_cannot_overwrite_newer_draft_dates_or_manual_performer_edits(self):
        for field, value in [('open_dates', '1/4/2027'),
                             ('performers', [dict(name='Pedro Mendez', availability='manual edit')]),
                             ('availability_drafts', [dict(self.draft, availability='Different input')])]:
            with self.subTest(field=field):
                previous = self.store.load(self.schedule)['data']
                snapshot = self.snapshot()
                self.store.update_fields(self.schedule, {field: value})
                expected = self.store.load(self.schedule)['data']
                self.assertFalse(self.store.apply_inline_result(self.schedule, 'row-one', snapshot, DATES))
                self.assertEqual(self.store.load(self.schedule)['data'], expected)
                self.store.save(self.schedule, previous)

    def test_deleted_row_and_deleted_schedule_cannot_be_resurrected(self):
        snapshot = self.snapshot()
        self.store.save_inline_drafts(self.schedule, [])
        self.assertFalse(self.store.apply_inline_result(self.schedule, 'row-one', snapshot, DATES))
        self.store.delete(self.schedule)
        with self.assertRaises(ValueError):
            self.store.apply_inline_result(self.schedule, 'row-one', snapshot, DATES)

    def test_dates_outside_schedule_are_rejected(self):
        with self.assertRaises(ValueError):
            self.store.apply_inline_result(self.schedule, 'row-one', self.snapshot(), [datetime(2027, 1, 4)])
        self.assertEqual(self.store.load(self.schedule)['data']['performers'][0]['availability'], '11/3/2026')

    def test_inline_dates_save_preserves_notes_performers_and_invalidates_bookings(self):
        self.store.save_inline_editor(self.schedule, [self.draft], '1/4/2027')
        data = self.store.load(self.schedule)['data']
        self.assertEqual(data['open_dates'], '1/4/2027')
        self.assertEqual(data['rows'], [])
        self.assertEqual(data['notes'], 'Keep notes')
        self.assertEqual(data['performers'][0]['availability'], '11/3/2026')
        self.store.save_inline_editor(self.schedule, [], None)
        self.assertEqual(self.store.load(self.schedule)['data']['open_dates'], '1/4/2027')

    def test_inline_roster_tracks_add_rename_and_remove_with_confirmed_dates(self):
        renamed = dict(self.draft, name='Pedro Updated')
        added = dict(id='new', name='Sarah Navy', availability='', status='Draft')
        self.store.save_inline_editor(self.schedule, [renamed, added])
        data = self.store.load(self.schedule)['data']
        self.assertEqual(data['performers'], [dict(name='Pedro Updated', availability='11/3/2026'),
                                              dict(name='Sarah Navy', availability='')])
        self.assertEqual(data['rows'], [])
        self.store.save_inline_editor(self.schedule, [added])
        self.assertEqual(self.store.load(self.schedule)['data']['performers'], [dict(name='Sarah Navy', availability='')])

    def test_full_schedule_changes_update_drafts_and_preserve_unchanged_raw_input(self):
        data = self.store.load(self.schedule)['data']
        sync_schedule_performers(data, [dict(name='Pedro Mendez', availability='11/3/2026')])
        self.assertEqual(data['availability_drafts'][0]['availability'], 'November 3 and 10')
        sync_schedule_performers(data, [dict(name='Pedro Mendez', availability='11/10/2026'),
                                        dict(name='Sarah Navy', availability='')])
        self.assertEqual(data['availability_drafts'][0]['availability'], '11/10/2026')
        self.assertEqual(data['availability_drafts'][0]['id'], 'row-one')
        self.assertEqual(data['availability_drafts'][1]['name'], 'Sarah Navy')
        sync_schedule_performers(data, [dict(name='Sarah Navy', availability='')])
        self.assertEqual([row['name'] for row in data['availability_drafts']], ['Sarah Navy'])


class LocalFormatterTests(unittest.TestCase):
    def test_same_dates_as_import_for_common_availability(self):
        from availability_import import parse_import
        for raw in ('All', 'November 3 and 10', 'All except 11/10', 'Every Tuesday',
                    '11/3/2026', 'November 1–10, 2026'):
            with self.subTest(raw=raw):
                expected = parse_import(f'Pedro Mendez - {raw}', 2026, 11, DATES)
                actual = format_inline('Pedro Mendez', raw, DATES)
                self.assertEqual(actual.availability, {name: [date for date in dates if date in DATES]
                                                       for name, dates in expected.availability.items()})

    def test_unclear_input_and_multiple_performers_do_not_apply(self):
        for raw in ('maybe, please call me', 'All\nOther Person - 11/3'):
            with self.subTest(raw=raw):
                result = format_inline('Pedro Mendez', raw, DATES)
                self.assertFalse(result.availability)
                self.assertTrue(result.notes)

    def test_name_is_kept_separate_and_non_open_dates_are_excluded(self):
        result = format_inline('Mary - Jane', '11/3/2026, 11/4/2026', DATES)
        self.assertEqual(result.availability, {'Mary - Jane': [DATES[0]]})
        self.assertTrue(result.notes)


@unittest.skipUnless(os.environ.get('MHW_RUN_GUI_TESTS') == '1', 'Requires a desktop session')
class InlineDesktopTests(unittest.TestCase):
    def setUp(self):
        from main import AvailabilityApp
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = CampaignStore(Path(self.temp.name) / 'schedules.sqlite3')
        self.schedule = self.store.create('November')
        self.store.save(self.schedule, dict(open_dates='11/3/2026, 11/10/2026'))
        self.app = AvailabilityApp(store=self.store)
        self.addCleanup(lambda: self.app._close())
        self.errors = []
        self.app.report_callback_exception = lambda *args: self.errors.append(args)
        self.app.update()
        self.app.campaign_list.toggle_expanded(self.schedule)
        self.editor = self.app._inline_editor(self.schedule)
        self.app.update()

    def complete_row(self, name='Pedro Mendez', availability='November 3 and 10'):
        row = self.editor.rows[0]
        row['name'].set(name)
        row['text'].insert('1.0', availability)
        self.editor.flush()
        return row

    def test_paste_names_and_availability_survive_refresh(self):
        self.editor.paste_names(NAMES)
        self.editor.paste_names('pedro mendez\nSarah Navy')
        self.assertEqual(len(self.editor.rows), 10)
        self.editor.rows[0]['text'].insert('1.0', 'Nov 3')
        self.app._refresh_campaigns()
        self.editor = self.app._inline_editor(self.schedule)
        self.assertEqual([row['name'].get() for row in self.editor.rows], NAMES.splitlines())
        self.assertEqual(self.editor.rows[0]['text'].get('1.0', 'end-1c'), 'Nov 3')

    def test_roster_edits_sync_in_both_directions_and_removed_names_do_not_return(self):
        row = self.complete_row()
        self.editor.commit(row)
        self.editor.paste_names('Sarah Navy')
        self.app._open_campaign(self.schedule)
        self.assertEqual([name for name, _, _ in self.app.performers], ['Pedro Mendez', 'Sarah Navy'])
        self.app.performers[0][1].delete('1.0', 'end')
        self.app.performers[0][1].insert('1.0', '11/10/2026')
        # Remove Sarah through the full editor's native Remove button.
        self.app.performers[1][2].winfo_children()[0].winfo_children()[1].invoke()
        self.app._performer_row('Colin Priller', '11/3/2026')
        self.app._invalidate()
        self.app._show_home()
        editor = self.app._inline_editor(self.schedule)
        self.assertEqual([row['name'].get() for row in editor.rows], ['Pedro Mendez', 'Colin Priller'])
        self.assertEqual(editor.rows[0]['text'].get('1.0', 'end-1c'), '11/10/2026')
        editor.rows[0]['name'].set('Pedro Updated')
        editor.remove_row(editor.rows[1])
        self.app._open_campaign(self.schedule)
        self.assertEqual([name for name, _, _ in self.app.performers], ['Pedro Updated'])
        self.assertEqual(self.app.performers[0][1].get('1.0', 'end-1c'), '11/10/2026')
        self.app._show_home()
        reopened = CampaignStore(self.store.path).load(self.schedule)['data']
        self.assertEqual([person['name'] for person in reopened['performers']], ['Pedro Updated'])
        self.assertEqual([draft['name'] for draft in reopened['availability_drafts']], ['Pedro Updated'])
        self.assertEqual(self.errors, [])

    def test_legacy_mismatched_lists_are_recovered_without_losing_either_performer(self):
        self.editor.paste_names('Pedro Mendez')
        self.editor.flush()
        self.store.update_fields(self.schedule, {'performers': [dict(name='Sarah Navy', availability='11/3/2026')]})
        self.app._refresh_campaigns()
        editor = self.app._inline_editor(self.schedule)
        self.assertEqual([row['name'].get() for row in editor.rows], ['Sarah Navy', 'Pedro Mendez'])
        self.app._open_campaign(self.schedule)
        self.assertEqual([name for name, _, _ in self.app.performers], ['Sarah Navy', 'Pedro Mendez'])
        self.assertEqual(self.app.performers[0][1].get('1.0', 'end-1c'), '11/3/2026')

    def test_replacing_performers_in_import_updates_the_inline_list(self):
        self.editor.paste_names('Pedro Mendez\nSarah Navy')
        self.app._open_campaign(self.schedule)
        self.app._apply_availability_import({'Colin Priller': DATES}, replace=True)
        self.app._show_home()
        editor = self.app._inline_editor(self.schedule)
        self.assertEqual([row['name'].get() for row in editor.rows], ['Colin Priller'])
        self.assertEqual(editor.rows[0]['text'].get('1.0', 'end-1c'), '11/3/2026, 11/10/2026')
        self.app._open_campaign(self.schedule)
        self.assertEqual([name for name, _, _ in self.app.performers], ['Colin Priller'])

    def test_full_schedule_converts_pasted_availability_on_click_out_and_syncs_raw_text(self):
        self.app._open_campaign(self.schedule)
        self.app._performer_row('Pedro Mendez', '')
        field = self.app.performers[0][1]
        field.focus_force()
        self.app.update()
        raw = 'All except November 10'
        self.app.clipboard_clear()
        self.app.clipboard_append(raw)
        field.event_generate('<<Paste>>')
        self.app.update()
        with patch('main.convert_with_ai') as network, patch('main.format_inline', wraps=format_inline) as formatter:
            self.app.page_canvas.event_generate('<Button-1>', x=5, y=5)
            self.app.update()
            self.assertEqual(field.get('1.0', 'end-1c'), '11/3/2026')
            field.focus_force()
            self.app.update()
            self.app.page_canvas.event_generate('<Button-1>', x=5, y=5)
            self.app.update()
            formatter.assert_called_once()
            network.assert_not_called()
        saved = self.store.load(self.schedule)['data']
        self.assertEqual(saved['performers'][0]['availability'], '11/3/2026')
        self.assertEqual(saved['availability_drafts'][0]['availability'], raw)
        self.app._generate()
        self.assertEqual([name for _, name in self.app.rows], ['Pedro Mendez', None])
        self.app._show_home()
        self.assertEqual(self.app._inline_editor(self.schedule).rows[0]['text'].get('1.0', 'end-1c'), raw)
        self.assertEqual(self.errors, [])

    def test_full_schedule_unclear_availability_is_preserved_for_review(self):
        self.app._open_campaign(self.schedule)
        self.app._performer_row('Pedro Mendez', '')
        field = self.app.performers[0][1]
        field.focus_force()
        self.app.update()
        raw = 'maybe, please call me'
        field.insert('1.0', raw)
        self.app.page_canvas.event_generate('<Button-1>', x=5, y=5)
        self.app.update()
        self.assertEqual(field.get('1.0', 'end-1c'), raw)
        self.assertIn('Needs review', self.app.performers[0][2].winfo_children()[-1].cget('text'))
        self.assertEqual(self.store.load(self.schedule)['data']['availability_drafts'][0]['availability'], raw)
        self.assertEqual(self.errors, [])

    def test_full_schedule_retries_after_open_dates_are_added(self):
        self.app._open_campaign(self.schedule)
        self.app.dates_text.delete('1.0', 'end')
        self.app._performer_row('Pedro Mendez', '')
        field = self.app.performers[0][1]
        field.focus_force()
        self.app.update()
        field.insert('1.0', 'All')
        self.app.page_canvas.event_generate('<Button-1>', x=5, y=5)
        self.app.update()
        self.assertEqual(field.get('1.0', 'end-1c'), 'All')
        self.app.dates_text.insert('1.0', '11/3/2026')
        field.focus_force()
        self.app.update()
        self.app.page_canvas.event_generate('<Button-1>', x=5, y=5)
        self.app.update()
        self.assertEqual(field.get('1.0', 'end-1c'), '11/3/2026')
        self.assertEqual(self.errors, [])

    def test_search_finds_new_draft_names_and_keeps_matching_schedule(self):
        other = self.store.create('Other schedule')
        self.editor.rows[0]['name'].set('Pedro Mendez')
        self.app.schedule_search.set('mendez')
        self.app.update()
        self.assertEqual(self.app.campaign_list.get_children(), (self.schedule,))
        self.assertEqual(self.app._inline_editor(self.schedule).rows[0]['name'].get(), 'Pedro Mendez')
        self.app._clear_filters()
        self.app.update()
        self.assertEqual(set(self.app.campaign_list.get_children()), {self.schedule, other})

    def test_search_hides_other_performers_without_removing_drafts_or_availability(self):
        self.editor.paste_names('Pedro Mendez\nSarah Navy\nPedro Miller')
        for row in self.editor.rows:
            row['text'].insert('1.0', 'November 3')
        self.editor.flush()
        self.app.schedule_search.set(' PeDrO ')
        self.app.update()
        editor = self.app._inline_editor(self.schedule)
        self.assertEqual([row['name'].get() for row in editor.rows if row['frame'].winfo_ismapped()],
                         ['Pedro Mendez', 'Pedro Miller'])
        self.assertEqual(len(editor.rows), 3)
        editor.rows[0]['text'].delete('1.0', 'end')
        editor.rows[0]['text'].insert('1.0', 'November 10')
        editor.commit(editor.rows[0])
        drafts = self.store.load(self.schedule)['data']['availability_drafts']
        self.assertEqual(next(row['availability'] for row in drafts if row['name'] == 'Sarah Navy'), 'November 3')
        self.app._clear_filters()
        self.app.update()
        editor = self.app._inline_editor(self.schedule)
        self.assertEqual([row['name'].get() for row in editor.rows if row['frame'].winfo_ismapped()],
                         ['Pedro Mendez', 'Sarah Navy', 'Pedro Miller'])
        self.assertEqual(editor.rows[0]['text'].get('1.0', 'end-1c'), 'November 10')
        self.assertEqual(self.errors, [])

    def test_title_search_with_no_performer_match_has_clear_message(self):
        self.editor.paste_names('Pedro Mendez\nSarah Navy')
        self.app.schedule_search.set('November')
        self.app.update()
        editor = self.app._inline_editor(self.schedule)
        self.assertFalse(any(row['frame'].winfo_ismapped() for row in editor.rows))
        self.assertTrue(editor.empty_results.winfo_ismapped())
        self.assertEqual(len(self.store.load(self.schedule)['data']['availability_drafts']), 2)

    def test_clicking_blank_space_finishes_availability_and_dates(self):
        row = self.complete_row()
        row['text'].focus_force()
        self.app.update()
        canvas = self.app.campaign_list.canvas
        canvas.event_generate('<Button-1>', x=5, y=5)
        self.app.update()
        self.assertEqual(self.store.load(self.schedule)['data']['performers'][0]['availability'], '11/3/2026, 11/10/2026')
        self.editor.open_dates_text.focus_force()
        self.app.update()
        self.editor.open_dates_text.delete('1.0', 'end')
        self.editor.open_dates_text.insert('1.0', '1/4/2027')
        canvas.event_generate('<Button-1>', x=5, y=5)
        self.app.update()
        self.assertEqual(self.store.load(self.schedule)['data']['open_dates'], '1/4/2027')
        self.assertEqual(self.editor.date_status.get(), '1 open dates · saved')
        self.app._open_campaign(self.schedule)
        self.app.update()
        self.app.notes_text.focus_force()
        self.app.update()
        self.app.notes_text.insert('1.0', 'Saved when clicking outside')
        self.app.page_canvas.event_generate('<Button-1>', x=5, y=5)
        self.app.update()
        self.assertEqual(self.store.load(self.schedule)['data']['notes'], 'Saved when clicking outside')
        self.assertEqual(self.errors, [])

    def test_expanded_editor_fits_viewport_with_tall_dates_on_left(self):
        self.editor.paste_names(NAMES)
        for width in (1180, 1000, 900):
            self.app.geometry(f'{width}x820')
            self.app.update()
            canvas = self.app.campaign_list.canvas
            editor_right = self.editor.winfo_rootx() + self.editor.winfo_width()
            self.assertLessEqual(editor_right, canvas.winfo_rootx() + canvas.winfo_width())
            dates = self.editor.open_dates_text
            row = self.editor.rows[0]
            self.assertLess(dates.winfo_rootx() + dates.winfo_width(), row['entry'].winfo_rootx())
            self.assertGreater(dates.winfo_height(), dates.winfo_width())
            self.assertGreater(row['entry'].winfo_width(), 30)
            actions = row['frame'].winfo_children()[-1]
            self.assertLessEqual(actions.winfo_rootx() + actions.winfo_width(), editor_right)
            self.assertEqual(canvas.xview(), (0.0, 1.0))

    def test_expand_add_rows_and_collapse_update_scroll_range(self):
        canvas = self.app.campaign_list.canvas
        self.editor.paste_names('\n'.join(f'Performer {number}' for number in range(35)))
        self.app.update()
        self.assertLess(canvas.yview()[1], 1)
        # Wheel events over the editor must reach the containing list.
        field = self.editor.rows[0]['entry']
        field.event_generate('<MouseWheel>', delta=-120,
                             rootx=field.winfo_rootx() + 4, rooty=field.winfo_rooty() + 4)
        self.app.update()
        self.assertGreater(canvas.yview()[0], 0)
        canvas.yview_moveto(1)
        self.app.update()
        last = self.editor.rows[-1]['frame']
        self.assertLessEqual(last.winfo_rooty() + last.winfo_height(),
                             canvas.winfo_rooty() + canvas.winfo_height())
        self.app.campaign_list.toggle_expanded(self.schedule)
        self.app.update()
        self.assertEqual(canvas.yview(), (0.0, 1.0))
        self.app.campaign_list.toggle_expanded(self.schedule)
        self.app.update()
        self.assertLess(canvas.yview()[1], 1)
        self.assertEqual(self.errors, [])

    def test_local_formatting_updates_existing_performer_without_key_or_network(self):
        self.store.update_fields(self.schedule, {'performers': [dict(name='Pedro Mendez', availability='11/3/2026')]})
        row = self.complete_row()
        with patch.dict(os.environ, {'OPENAI_API_KEY': ''}), patch('main.convert_with_ai') as network:
            self.editor.commit(row)
            self.editor.commit(row)
            network.assert_not_called()
        data = self.store.load(self.schedule)['data']
        self.assertEqual(data['performers'], [dict(name='Pedro Mendez', availability='11/3/2026, 11/10/2026')])
        self.assertIn('Updated', row['status'].get())
        self.app._open_campaign(self.schedule)
        self.assertEqual(self.app.performers[0][1].get('1.0', 'end-1c'), '11/3/2026, 11/10/2026')
        self.app.notes_text.insert('1.0', 'New schedule notes')
        self.app._save_campaign()
        self.assertTrue(self.store.load(self.schedule)['data']['availability_drafts'])
        self.assertEqual(self.errors, [])

    def test_unclear_input_preserves_existing_and_retry_uses_corrected_draft(self):
        self.store.update_fields(self.schedule, {'performers': [dict(name='Pedro Mendez', availability='11/3/2026')]})
        row = self.complete_row(availability='maybe, please call me')
        self.editor.commit(row)
        self.assertIn('Needs review', row['status'].get())
        self.assertEqual(self.store.load(self.schedule)['data']['performers'][0]['availability'], '11/3/2026')
        row['text'].delete('1.0', 'end')
        row['text'].insert('1.0', 'November 10')
        self.editor.commit(row, retry=True)
        self.assertEqual(self.store.load(self.schedule)['data']['performers'][0]['availability'], '11/10/2026')

    def test_inline_dates_save_and_open_in_full_schedule(self):
        self.editor.open_dates_text.delete('1.0', 'end')
        self.editor.open_dates_text.insert('1.0', '1/4/2027\n1/11/2027')
        self.editor.flush()
        self.assertEqual(self.editor.date_status.get(), '2 open dates · saved')
        self.app._open_campaign(self.schedule)
        self.assertEqual(self.app.dates_text.get('1.0', 'end-1c'), '1/4/2027\n1/11/2027')

    def test_dates_commit_formats_ready_performers_and_partial_dates_stay_drafts(self):
        self.complete_row(availability='all dates')
        self.editor.open_dates_text.delete('1.0', 'end')
        self.editor.open_dates_text.insert('1.0', '1/4/')
        self.editor.commit_dates()
        self.assertEqual(self.store.load(self.schedule)['data']['open_dates'], '1/4/')
        self.assertIn('Draft saved', self.editor.date_status.get())
        self.assertEqual(self.store.load(self.schedule)['data']['performers'], [dict(name='Pedro Mendez', availability='')])
        self.editor.open_dates_text.insert('end', '2027')
        self.editor.commit_dates()
        self.assertEqual(self.store.load(self.schedule)['data']['performers'][0]['availability'], '1/4/2027')

    def test_missing_dates_keeps_draft_and_cleared_dates_invalidate_previous_result(self):
        row = self.complete_row()
        self.store.update_fields(self.schedule, {'open_dates': ''})
        self.editor.commit(row)
        self.assertIn('open dates', row['status'].get())
        self.assertEqual(self.store.load(self.schedule)['data']['availability_drafts'][0]['availability'], 'November 3 and 10')

    def test_real_multiline_paste_and_restart(self):
        from main import AvailabilityApp
        self.app.clipboard_clear()
        self.app.clipboard_append(NAMES)
        self.editor.rows[0]['entry'].event_generate('<<Paste>>')
        self.app.update()
        self.assertEqual(len(self.editor.rows), 10)
        self.app._close()
        self.app = AvailabilityApp(store=CampaignStore(self.store.path))
        self.app.update()
        self.app.campaign_list.toggle_expanded(self.schedule)
        self.editor = self.app._inline_editor(self.schedule)
        self.assertEqual([row['name'].get() for row in self.editor.rows], NAMES.splitlines())


if __name__ == '__main__':
    unittest.main()
