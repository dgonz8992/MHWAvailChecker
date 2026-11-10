"""Multi-venue parsing, matching, storage, and desktop workflows."""
from datetime import datetime
import os
from pathlib import Path
import random
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from campaigns import CampaignStore
from scheduler import parse_open_dates
from venue_support import (schedule_venues, venue_rule, format_venue_availability,
                           generate_venue_schedule, alternate_venue_schedule, parse_venue_import)

VENUES = [dict(id='main', name='Lobby', open_dates='11/6/2026, 11/7/2026, 11/13/2026, 11/14/2026'),
          dict(id='pool', name='Pool', open_dates='11/6/2026, 11/7/2026, 11/13/2026, 11/14/2026')]
DATES = parse_open_dates(VENUES[0]['open_dates'])


class VenueLogicTests(unittest.TestCase):
    def test_bulk_import_handles_venue_sections_and_plain_named_availability(self):
        result = parse_venue_import('Alex - Lobby: only Fridays\nPool: only Saturdays\nSam - All at Pool', VENUES)
        self.assertEqual(set(result.availability), {'Alex', 'Sam'})
        self.assertEqual(result.venue_rules['Alex']['mode'], 'by_venue')
        self.assertEqual(result.venue_rules['Sam']['venues'], ['pool'])
        result, rule = format_venue_availability('Alex', 'Lobby only Fridays; Pool only Saturdays', VENUES)
        self.assertEqual(rule['mode'], 'by_venue')
        self.assertEqual(result.availability['Alex'], DATES)

    def test_labeled_paste_detects_venues_and_different_weekday_rules(self):
        result, rule = format_venue_availability('Alex', 'Lobby: only Fridays\nPool: only Saturdays', VENUES)
        self.assertEqual(rule['mode'], 'by_venue')
        self.assertEqual(rule['venues'], ['main', 'pool'])
        self.assertEqual(rule['availability']['main'], '11/6/2026, 11/13/2026')

        self.assertEqual(rule['availability']['pool'], '11/7/2026, 11/14/2026')
        self.assertEqual(result.availability['Alex'], DATES)

    def test_shared_paste_selects_only_named_venues_case_insensitively(self):
        for raw, expected in (('All at pool', ['pool']), ('Lobby and Pool: all', ['main', 'pool']),
                              ('All dates, not Lobby', ['pool'])):
            with self.subTest(raw=raw):
                result, rule = format_venue_availability('Alex', raw, VENUES)
                self.assertEqual(rule['venues'], expected)
                self.assertEqual(result.availability['Alex'], DATES)

    def test_unknown_venue_label_is_reviewed(self):
        with self.assertRaisesRegex(ValueError, 'Unknown venue'):
            format_venue_availability('Alex', 'Rooftop: all Fridays', VENUES)

    def test_same_day_matching_preserves_venue_only_performer_and_no_double_booking(self):
        people = dict(Flexible=DATES, LobbyOnly=DATES)
        rules = {'lobbyonly': dict(mode='shared', venues=['main'])}
        rows, counts = generate_venue_schedule(VENUES, people, rules, 0)
        self.assertEqual(sum(counts.values()), 8)
        for day in DATES:
            booked = [(vid, name) for date, vid, name in rows if date == day]
            self.assertEqual(booked, [('main', 'LobbyOnly'), ('pool', 'Flexible')])

    def test_per_venue_availability_and_spacing_apply_across_venues(self):
        _, rule = format_venue_availability('Alex', 'Lobby: only Fridays\nPool: only Saturdays', VENUES)
        rows, counts = generate_venue_schedule(VENUES, dict(Alex=DATES), {'alex': rule}, 7)
        self.assertEqual([(day, vid) for day, vid, name in rows if name], [(DATES[0], 'main'), (DATES[2], 'main')])
        self.assertEqual(counts['Alex'], 2)

    def test_random_assignments_respect_each_venue_and_global_constraints(self):
        rng = random.Random(63)
        for _ in range(100):
            people = {f'Person {i}': [date for date in DATES if rng.random() < .7] for i in range(6)}
            rules = {name.casefold(): dict(mode='shared', venues=[v['id'] for v in VENUES if rng.random() < .7]) for name in people}
            gap = rng.choice((0, 1, 7, 8))
            rows, _ = generate_venue_schedule(VENUES, people, rules, gap, rng=rng)
            seen = {}
            for day, vid, name in rows:
                if name is None:
                    continue
                self.assertIn(day, people[name]); self.assertIn(vid, rules[name.casefold()]['venues'])
                if name in seen:
                    self.assertGreaterEqual((day - seen[name]).days, max(gap, 1))
                seen[name] = day
            alternate = alternate_venue_schedule(VENUES, people, rules, gap, rows, rng=rng)
            if alternate:
                self.assertGreaterEqual(sum(alternate[1].values()), sum(name is not None for _, _, name in rows))


class VenueStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store = CampaignStore(Path(self.temp.name) / 'venues.sqlite3')
        self.sid = self.store.create('Hotel')
        self.store.save(self.sid, dict(open_dates=VENUES[0]['open_dates'], performers=[dict(name='Alex', availability='11/6/2026')], notes='Keep notes'))

    def test_legacy_schedule_upgrades_without_losing_notes_or_performer(self):
        self.store.save_venues(self.sid, VENUES)
        data = self.store.load(self.sid)['data']
        self.assertEqual(data['notes'], 'Keep notes')
        self.assertEqual(venue_rule(data, 'Alex')['venues'], ['main'])
        self.assertEqual(len(data['venues']), 2)
        result, rule = format_venue_availability('Alex', 'Lobby: only Fridays\nPool: only Saturdays', VENUES)
        self.store.save_performer_venues(self.sid, 'Alex', rule, 'Lobby: only Fridays\nPool: only Saturdays', result.availability['Alex'])
        restored = CampaignStore(self.store.path).load(self.sid)['data']
        self.assertEqual(restored['performer_venue_rules']['alex'], rule)
        self.assertEqual(restored['performers'][0]['availability'], '11/6/2026, 11/7/2026, 11/13/2026, 11/14/2026')


@unittest.skipUnless(os.environ.get('MHW_RUN_GUI_TESTS') == '1', 'Requires a desktop session')
class VenueDesktopTests(unittest.TestCase):
    def setUp(self):
        from main import AvailabilityApp
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store = CampaignStore(Path(self.temp.name) / 'venues.sqlite3')
        self.sid = self.store.create('Hotel')
        self.store.save(self.sid, dict(open_dates=VENUES[0]['open_dates'], minimum_gap='0',
            performers=[dict(name='Alex', availability=VENUES[0]['open_dates']), dict(name='Sam', availability=VENUES[0]['open_dates'])]))
        self.store.save_venues(self.sid, VENUES)
        for name in ('Alex', 'Sam'):
            self.store.save_performer_venues(self.sid, name, dict(mode='shared', venues=['main', 'pool'], availability={}, raw_availability={}),
                                             'All', DATES)
        self.app = AvailabilityApp(store=self.store)
        self.errors = []; self.app.report_callback_exception = lambda *error: self.errors.append(error)
        self.addCleanup(self.cleanup)
        self.app.update()

    def cleanup(self):
        self.app._close(); self.assertEqual(self.errors, [])

    def test_whole_column_copy_keeps_offscreen_rows_and_highlights_follow_scroll(self):
        from datetime import timedelta
        self.app._open_campaign(self.sid)
        self.app.rows = [(DATES[0] + timedelta(days=i), f'Performer {i}') for i in range(150)]
        self.app.row_venues = ['main' if i % 2 == 0 else 'pool' for i in range(150)]
        self.app._render_schedule(); self.app.update()
        table = self.app.table
        self.app._copy_whole_column('performer'); self.app.update()
        self.assertEqual(len(self.app.clipboard_get().splitlines()), 75)
        table.yview_moveto(1); self.app.update()
        shown = [label.cget('text') for label in table._highlights if label.winfo_ismapped()]
        self.assertIn('Performer 148', shown)
        self.assertNotIn('Performer 0', shown)
        self.assertLess(len(table._highlights), 40)
        self.assertEqual(len(table.selection_text().splitlines()), 75)

    def test_grid_clicks_and_shift_clicks_select_cells_and_double_click_edits(self):
        self.app._open_campaign(self.sid); self.app._generate(); self.app.update()
        table = self.app.table
        x, y, w, h = table.bbox('0', 'performer')
        table.select_cell('0', 'date')
        self.app._edit_schedule_cell(SimpleNamespace(keysym='Return'))
        self.assertIsNone(self.app._schedule_edit)
        table._click(SimpleNamespace(x=x+w//2, y=y+h//2, state=0, time=1000))
        self.app.update()
        self.assertEqual(table.selected_cells(), (['0'], [1]))
        table._click(SimpleNamespace(x=x+w//2, y=y+h//2, state=0, time=1200))
        self.assertIsNotNone(self.app._schedule_edit)
        self.app._finish_schedule_edit(cancel=True)
        x2, y2, w2, h2 = table.bbox('2', 'day')
        table._click(SimpleNamespace(x=x2+w2//2, y=y2+h2//2, state=1, time=2000))
        rows, columns = table.selected_cells()
        self.assertEqual(rows, ['0', '2'])
        self.assertEqual(columns, [1, 2, 3])
        table._arrow(SimpleNamespace(keysym='Left', state=0))
        self.assertEqual(table.selected_cells(), (['2'], [2]))
        table.select_column('performer')
        self.app.update()
        self.app._change_appearance('Dark'); self.app.update()
        shown = [label for label in table._highlights if label.winfo_ismapped()]
        self.assertTrue(shown)
        self.assertEqual(shown[0].cget('background'), self.app._appearance_palette['selection'])

    def test_combined_grid_selects_cells_ranges_columns_and_copies_values(self):
        self.app._open_campaign(self.sid)
        self.app.rows = [(DATES[0], 'Alex'), (DATES[0], 'Sam'), (DATES[1], None), (DATES[1], 'Alex')]
        self.app.row_venues = ['main', 'pool', 'main', 'pool']
        self.app._render_schedule(); self.app.update()
        table = self.app.table
        table.select_cell('0', 'date')
        table.select_cell('2', 'performer', extend=True)
        self.app._copy_schedule_selection()
        self.assertEqual(self.app.clipboard_get(), '11/06/2026\tAlex\n11/07/2026\t')
        self.app.tk.call(table.heading('performer', 'command'))
        self.app.update()
        self.assertEqual(table.selection_text(), 'Alex\n')
        self.assertTrue(any(label.winfo_ismapped() for label in table._highlights))
        self.app._copy_schedule_selection(); self.assertEqual(self.app.clipboard_get(), 'Alex\n')
        self.app.schedule_venue_tabs.select(self.app._schedule_venue_pages['pool']); self.app.update()
        self.assertIsNone(table.selection_text())
        self.assertEqual(table.get_children(), ('1', '3'))
        self.app._copy_whole_column('performer'); self.assertEqual(self.app.clipboard_get(), 'Sam\nAlex')
        self.app._copy_schedule()
        self.assertNotIn('Lobby', self.app.clipboard_get())
        self.assertEqual(len(self.app.rows), 4)

    def test_switching_venue_commits_edit_to_correct_booking(self):
        self.app._open_campaign(self.sid); self.app._generate(); self.app.update()
        self.app.schedule_venue_tabs.select(self.app._schedule_venue_pages['pool']); self.app.update()
        self.app.table.select_cell('1', 'performer')
        self.app._edit_schedule_cell(SimpleNamespace(keysym='Return'))
        field = self.app._schedule_edit[0]
        field.delete(0, 'end'); field.insert(0, 'Hotel Guest')
        self.app.schedule_venue_tabs.select(self.app._schedule_venue_pages['main']); self.app.update()
        self.assertEqual(self.app.rows[1][1], 'Hotel Guest')
        self.assertEqual(self.app._schedule_venue, 'main')
        self.assertNotIn('1', self.app.table.get_children())
        self.app._save_campaign()
        self.assertEqual(self.store.load(self.sid)['data']['rows'][1]['performer'], 'Hotel Guest')

    def test_names_tabs_filter_in_date_order_and_copy_only_current_venue(self):
        self.app._open_campaign(self.sid)
        self.app.rows = [(DATES[0], 'Alex'), (DATES[0], 'Sam'), (DATES[1], None), (DATES[1], 'Alex')]
        self.app.row_venues = ['main', 'pool', 'main', 'pool']
        self.app._render_schedule(); self.app.update()
        def names():
            return [self.app.table.item(item, 'values')[1] for item in self.app.table.get_children()]
        self.assertEqual(names(), ['Alex', ''])
        self.assertEqual([self.app.schedule_venue_tabs.tab(page, 'text') for page in self.app.schedule_venue_tabs.tabs()], ['Lobby', 'Pool'])
        self.app._copy_whole_column('performer'); self.assertEqual(self.app.clipboard_get(), 'Alex\n')
        self.app.schedule_venue_tabs.select(self.app._schedule_venue_pages['pool']); self.app.update()
        self.assertEqual(names(), ['Sam', 'Alex'])
        self.app._copy_whole_column('performer'); self.assertEqual(self.app.clipboard_get(), 'Sam\nAlex')
        self.app.table.select_cell(self.app.table.get_children()[1], 'performer')
        self.app._copy_schedule_selection(); self.assertEqual(self.app.clipboard_get(), 'Alex')
        self.assertEqual(len(self.app.table.get_children()), 2)
        self.app._queue_save(); self.app._save_campaign()
        self.app._show_home(); self.app._open_campaign(self.sid); self.app.update()
        self.assertEqual(names(), ['Sam', 'Alex'])

    def test_manual_booking_edit_keeps_active_schedule_venue(self):
        self.app._open_campaign(self.sid); self.app._generate(); self.app.update()
        self.app.schedule_venue_tabs.select(self.app._schedule_venue_pages['pool']); self.app.update()
        index = self.app.row_venues.index('pool')
        self.app.table.selection_set(str(index))
        self.app._edit_schedule_cell(SimpleNamespace(keysym='Return'))
        field = self.app._schedule_edit[0]
        field.delete(0, 'end'); field.insert(0, 'Guest Performer')
        self.app._finish_schedule_edit(); self.app.update()
        self.assertEqual(self.app._schedule_venue, 'pool')
        self.assertEqual(self.app.table.item(self.app.table.get_children()[0], 'values')[1], 'Guest Performer')

    def test_deleting_active_schedule_venue_falls_back_and_single_venue_hides_tabs(self):
        self.app._open_campaign(self.sid); self.app._generate(); self.app.update()
        self.app.schedule_venue_tabs.select(self.app._schedule_venue_pages['pool']); self.app.update()
        self.app.venue_dates.delete_venue(self.app.venue_dates.cards[1]); self.app.update()
        self.assertEqual(self.app._schedule_venue, 'main')
        self.assertFalse(self.app.schedule_venue_tabs.winfo_ismapped())
        self.assertEqual(self.app.table.get_children(), ())
        self.app._generate(); self.app.update()
        self.assertEqual(len(self.app.table.get_children()), len(self.app.rows))

    def test_reloading_wrapped_venues_repositions_new_cards(self):
        self.app._open_campaign(self.sid)
        dates = self.app.venue_dates
        dates.add_venue(); dates.add_venue()
        saved = self.store.load(self.sid)['data']
        with patch.object(dates.body, 'winfo_width', return_value=600):
            dates._layout_cards()
            dates.load(saved)
            self.app.dates_text = dates.texts[0]
            self.assertEqual([int(card['frame'].grid_info()['column']) for card in dates.cards], [0, 1, 0, 1])
            self.assertEqual([int(card['frame'].grid_info()['row']) for card in dates.cards], [0, 0, 1, 1])

    def test_unchanged_dates_do_not_reformat_performers_on_either_screen(self):
        self.app._open_campaign(self.sid)
        with patch.object(self.app, '_convert_inline') as convert:
            self.app._commit_venue_dates()
            self.app._commit_venue_dates()
            convert.assert_not_called()
            self.app.venue_dates.texts[0].insert('end', ', 11/20/2026')
            self.app.update()
            self.app._commit_venue_dates()
            changed_calls = convert.call_count
            self.assertGreater(changed_calls, 0)
            self.app._commit_venue_dates()
            self.assertEqual(convert.call_count, changed_calls)
        self.app._show_home()
        self.app.campaign_list.toggle_expanded(self.sid); self.app.update()
        editor = self.app._inline_editor(self.sid)
        with patch.object(self.app, '_convert_inline') as convert:
            editor.commit_dates(); editor.commit_dates()
            convert.assert_not_called()

    def test_resize_keeps_neighbor_dates_compact_and_skips_redundant_layout(self):
        self.app._open_campaign(self.sid); self.app.update()
        dates = self.app.venue_dates
        first, second = dates.texts
        with patch.object(dates.cards[0]['frame'], 'grid_configure', wraps=dates.cards[0]['frame'].grid_configure) as grid:
            dates._layout_cards(); dates._layout_cards()
            grid.assert_not_called()
        first._start_resize(SimpleNamespace(y_root=100))
        self.assertEqual(first._drag_height, 18)
        first._resize(SimpleNamespace(y_root=100))
        self.assertEqual(int(first.cget('height')), 18)
        self.app.update()
        self.assertEqual(int(second.cget('height')), 12)
        self.assertLess(dates.cards[1]['frame'].winfo_height(), dates.cards[0]['frame'].winfo_height())
        first._end_resize(SimpleNamespace(y_root=100))

    def test_new_venue_fields_get_app_scroll_and_click_out_bindings(self):
        self.app._open_campaign(self.sid)
        dates = self.app.venue_dates
        dates.add_venue()
        card = dates.cards[-1]
        for field in (card['entry'], card['text'], card['text'].resize_handle):
            self.assertEqual(field.bindtags()[0], 'MHWScroll')
        self.app._show_home()
        self.app.campaign_list.toggle_expanded(self.sid); self.app.update()
        dates = self.app._inline_editor(self.sid).venue_dates
        dates.add_venue()
        self.assertEqual(dates.texts[-1].bindtags()[0], 'MHWScroll')

    def test_deleting_venues_releases_unused_columns_on_both_screens(self):
        self.app._open_campaign(self.sid)
        dates = self.app.venue_dates
        dates.add_venue()
        self.app.update()
        dates.delete_venue(dates.cards[-1])
        dates.delete_venue(dates.cards[-1])
        self.app.update()
        for width in (1180, 1000):
            self.app.geometry(f'{width}x820'); self.app.update()
            self.assertLess(dates.winfo_reqwidth(), 300)
            self.assertEqual([dates.body.grid_columnconfigure(i)['weight'] for i in range(3)], [1, 0, 0])
            people = dates.people_panel
            self.assertLessEqual(dates.winfo_rootx() + dates.winfo_width(), people.winfo_rootx())
            self.assertLessEqual(people.winfo_rootx() + people.winfo_width(), self.app.winfo_rootx() + width)
        self.app._show_home()
        self.app.campaign_list.toggle_expanded(self.sid); self.app.update()
        editor = self.app._inline_editor(self.sid)
        dates = editor.venue_dates
        dates.add_venue(); self.app.update()
        dates.delete_venue(dates.cards[0]); self.app.update()
        for width in (1180, 900):
            self.app.geometry(f'{width}x820'); self.app.update()
            self.assertLess(dates.winfo_reqwidth(), 300)
            people = dates.people_panel
            canvas = self.app.campaign_list.canvas
            self.assertLessEqual(people.winfo_rootx() + people.winfo_width(), canvas.winfo_rootx() + canvas.winfo_width())
            self.assertEqual(canvas.xview(), (0.0, 1.0))

    def test_delete_venue_on_full_schedule_prunes_rules_and_persists(self):
        self.app._open_campaign(self.sid)
        self.app._generate()
        self.app.venue_dates.delete_venue(self.app.venue_dates.cards[0])
        self.app.update()
        data = self.store.load(self.sid)['data']
        self.assertEqual([v['id'] for v in data['venues']], ['pool'])
        self.assertEqual(venue_rule(data, 'Alex')['venues'], ['pool'])
        self.assertEqual(data['rows'], [])
        self.assertIs(self.app.dates_text, self.app.venue_dates.texts[0])
        self.assertEqual(int(self.app.venue_dates.people_panel.grid_info()['column']), 1)
        self.app._show_home(); self.app._open_campaign(self.sid)
        self.assertEqual(len(self.app.venue_dates.cards), 1)
        self.app.venue_dates.delete_venue(self.app.venue_dates.cards[0])
        self.assertEqual(len(self.app.venue_dates.cards), 1)

    def test_right_click_delete_from_expanded_schedule(self):
        self.app._refresh_campaigns(); self.app.campaign_list.toggle_expanded(self.sid); self.app.update()
        editor = self.app._inline_editor(self.sid)
        card = editor.venue_dates.cards[1]
        from tkinter import Menu
        def select_delete(menu, x, y):
            self.assertEqual(menu.entrycget('end', 'label'), 'Delete venue')
            menu.invoke('end')
        with patch.object(Menu, 'tk_popup', select_delete):
            result = editor.venue_dates._venue_menu(SimpleNamespace(widget=card['text'], x_root=0, y_root=0), card)
        self.assertEqual(result, 'break')
        self.app.update()
        data = self.store.load(self.sid)['data']
        self.assertEqual([v['id'] for v in data['venues']], ['main'])
        self.assertEqual(venue_rule(data, 'Alex')['venues'], ['main'])
        self.assertEqual(len(editor.venue_dates.cards), 1)
        self.assertIs(editor.open_dates_text, editor.venue_dates.texts[0])

    def test_full_schedule_keeps_default_layout_until_venue_added(self):
        sid = self.store.create('Single venue')
        self.app._open_campaign(sid)
        self.app.update()
        dates = self.app.venue_dates
        people = dates.people_panel
        self.assertEqual(int(people.grid_info()['row']), 0)
        self.assertEqual(int(people.grid_info()['column']), 1)
        self.assertFalse(dates.cards[0]['entry'].winfo_ismapped())
        field = dates.texts[0]
        field._expand()
        self.assertEqual(int(field.cget('height')), 18)
        field._collapse_on_blur()
        self.assertEqual(int(field.cget('height')), 12)
        dates.add_venue()
        self.app.update()
        self.assertEqual(int(people.grid_info()['row']), 1)
        self.assertEqual(len(dates.cards), 2)
        self.assertTrue(dates.cards[0]['entry'].winfo_ismapped())
        self.app._show_home(); self.app._open_campaign(sid)
        self.assertEqual(int(dates.people_panel.grid_info()['row']), 1)

    def test_add_and_rename_inline_venue_preserves_dates_and_persists(self):
        self.app._open_campaign(self.sid)
        self.app.venue_dates.add_venue()
        card = self.app.venue_dates.cards[-1]
        card['name'].set('Terrace')
        card['text'].insert('1.0', '11/20/2026')
        self.app.update()
        self.app._commit_venue_dates()
        data = self.store.load(self.sid)['data']
        self.assertEqual(data['venues'][-1]['name'], 'Terrace')
        self.assertEqual(data['venues'][-1]['open_dates'], '11/20/2026')
        self.assertEqual(data['venues'][0]['open_dates'], VENUES[0]['open_dates'])
        self.assertIn('11/20/2026', data['open_dates'])
        self.app._show_home(); self.app._open_campaign(self.sid)
        self.assertEqual(len(self.app.venue_dates.cards), 3)
        self.assertEqual(self.app.venue_dates.cards[-1]['name'].get(), 'Terrace')

    def test_expanded_add_venue_shows_settings_and_saves_drafts(self):
        self.app._refresh_campaigns(); self.app.campaign_list.toggle_expanded(self.sid); self.app.update()
        editor = self.app._inline_editor(self.sid)
        editor.venue_dates.add_venue()
        card = editor.venue_dates.cards[-1]
        card['name'].set('Terrace')
        card['text'].insert('1.0', '11/')
        self.app.update(); editor.commit_dates()
        self.assertEqual(self.store.load(self.sid)['data']['venues'][-1]['open_dates'], '11/')
        card['text'].delete('1.0', 'end'); card['text'].insert('1.0', '11/20/2026')
        self.app.update(); editor.commit_dates()
        data = self.store.load(self.sid)['data']
        self.assertIn('11/20/2026', data['open_dates'])
        self.assertTrue(all('venue_button' in row for row in editor.rows))

    def test_generation_venue_copy_confirmation_and_restart(self):
        self.app._open_campaign(self.sid); self.app._generate(); self.app.update()
        self.assertEqual(len(self.app.rows), 8)
        self.assertEqual(self.app.table['columns'], ('date', 'performer', 'venue', 'day'))
        for day in DATES:
            names = [name for date, name in self.app.rows if date == day and name]
            self.assertEqual(len(names), len(set(names)))
        self.app._copy_schedule(); self.assertIn('Date\tPerformer\tVenue\tDay', self.app.clipboard_get())
        self.app._copy_confirmation('Alex'); self.assertRegex(self.app.clipboard_get(), r'\((?:Lobby|Pool)\)')
        expected = list(zip(self.app.rows, self.app.row_venues))
        self.app._show_home(); self.app._open_campaign(self.sid)
        self.assertEqual(list(zip(self.app.rows, self.app.row_venues)), expected)

    def test_removing_second_venue_does_not_book_its_exclusive_performer_elsewhere(self):
        self.store.save_performer_venues(self.sid, 'Alex', dict(mode='shared', venues=['pool'], availability={}, raw_availability={}), 'All', DATES)
        self.store.save_venues(self.sid, VENUES[:1])
        self.app._open_campaign(self.sid); self.app._generate(); self.app.update()
        self.assertTrue(self.app.rows)
        self.assertFalse(any(name == 'Alex' for _, name in self.app.rows))
        self.assertEqual(self.app.table['columns'], ('date', 'performer', 'day'))

    def test_manual_edit_cannot_double_book_at_two_venues(self):
        self.app._open_campaign(self.sid); self.app._generate(); self.app.update()
        name = self.app.rows[0][1]
        self.app.schedule_venue_tabs.select(self.app._schedule_venue_pages['pool']); self.app.update()
        self.app.table.selection_set('1')
        self.app._edit_schedule_cell(SimpleNamespace(keysym='Return'))
        field = self.app._schedule_edit[0]; field.delete(0, 'end'); field.insert(0, name)
        self.app._finish_schedule_edit()
        self.assertNotEqual(self.app.rows[1][1], name)
        self.assertIn('another venue', self.app.arrangement_status.get())

    def test_inline_paste_auto_detects_venues_and_by_venue_mode(self):
        self.app._refresh_campaigns(); self.app.campaign_list.toggle_expanded(self.sid); self.app.update()
        editor = self.app._inline_editor(self.sid)
        row = editor.rows[0]
        row['text'].delete('1.0', 'end'); row['text'].insert('1.0', 'Lobby: only Fridays\nPool: only Saturdays')
        editor.commit(row); self.app.update()
        data = self.store.load(self.sid)['data']; rule = venue_rule(data, 'Alex')
        self.assertEqual(rule['mode'], 'by_venue')
        self.assertEqual(rule['availability']['pool'], '11/7/2026, 11/14/2026')
        self.app._open_campaign(self.sid); self.app._generate()
        for index, (day, name) in enumerate(self.app.rows):
            if name == 'Alex':
                self.assertIn(day.weekday(), (4,) if self.app.row_venues[index] == 'main' else (5,))

    def test_inline_dates_and_shared_by_venue_settings(self):
        from venue_widgets import PerformerVenuesDialog
        self.app._open_campaign(self.sid)
        field = self.app.venue_dates.texts[1]
        field.delete('1.0', 'end'); field.insert('1.0', '11/7/2026, 11/14/2026')
        self.app.update()
        self.app._commit_venue_dates()
        self.assertEqual(schedule_venues(self.store.load(self.sid)['data'])[1]['open_dates'], '11/7/2026, 11/14/2026')
        def edit_performer():
            dialog = next(w for w in self.app.winfo_children() if isinstance(w, PerformerVenuesDialog))
            dialog.mode.set('by_venue'); dialog._layout()
            for vid, (selected, field) in dialog.controls.items():
                selected.set(True); field.delete('1.0', 'end'); field.insert('1.0', 'only Saturdays' if vid == 'pool' else 'only Fridays')
            dialog.ok()
        self.app.after(100, edit_performer); self.app._edit_performer_venues(self.sid, 'Alex')
        rule = venue_rule(self.store.load(self.sid)['data'], 'Alex')
        self.assertEqual(rule['mode'], 'by_venue')
        self.assertEqual(rule['availability']['main'], '11/6/2026, 11/13/2026')
        def switch_back():
            dialog = next(w for w in self.app.winfo_children() if isinstance(w, PerformerVenuesDialog))
            dialog.mode.set('shared'); dialog._layout()
            dialog.shared.delete('1.0', 'end'); dialog.shared.insert('1.0', 'All')
            for vid, (selected, _) in dialog.controls.items():
                selected.set(vid == 'pool')
            dialog.ok()
        self.app.after(100, switch_back); self.app._edit_performer_venues(self.sid, 'Alex')
        rule = venue_rule(self.store.load(self.sid)['data'], 'Alex')
        self.assertEqual(rule['mode'], 'shared')
        self.assertEqual(rule['venues'], ['pool'])
