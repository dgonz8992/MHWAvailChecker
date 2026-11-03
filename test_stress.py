"""Opt-in load tests: MHW_RUN_STRESS_TESTS=1 (plus MHW_RUN_GUI_TESTS=1 for Tk).

Every database is temporary. No real schedules or network services are used.
"""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import random
import sqlite3
import tempfile
import threading
import unittest

from availability_import import parse_import
from campaigns import CampaignStore
from inline_availability import editor_drafts, sync_schedule_performers
from scheduler import alternate_schedule, generate_schedule


STRESS = os.environ.get('MHW_RUN_STRESS_TESTS') == '1'
GUI = os.environ.get('MHW_RUN_GUI_TESTS') == '1'
DATES = [datetime(2026, 11, day) for day in (3, 10, 17)]
DATE_TEXT = '11/3/2026, 11/10/2026, 11/17/2026'


def fixture(index, count):
    people = [dict(name=f'Person {index}-{i}', availability=DATE_TEXT) for i in range(count)]
    drafts = [dict(id=f'{index}-{i}', name=p['name'], availability=DATE_TEXT, status='Existing performer')
              for i, p in enumerate(people)]
    return dict(open_dates=DATE_TEXT, notes=f'Notes {index}', performers=people, availability_drafts=drafts)


@unittest.skipUnless(STRESS, 'Opt-in stress suite')
class StressDataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = CampaignStore(Path(self.temp.name) / 'stress.sqlite3')

    def test_750_random_schedules_and_alternatives_obey_constraints(self):
        rng = random.Random(20261103)
        for case in range(750):
            dates = [datetime(2026, 1, 1) + timedelta(days=n) for n in sorted(rng.sample(range(120), rng.randrange(1, 61)))]
            people = {f'Person {n}': rng.sample(dates, rng.randrange(len(dates) + 1)) for n in range(rng.randrange(1, 21))}
            gap = rng.randrange(22)
            original = json.dumps({name: [d.isoformat() for d in ds] for name, ds in people.items()})
            rows, counts = generate_schedule(dates + dates[:3], people, gap)
            variants = [(rows, counts)]
            if case < 100:
                alternate = alternate_schedule(dates, people, gap, rows, rng=rng)
                if alternate:
                    self.assertNotEqual(alternate[0], rows)
                    self.assertGreaterEqual(sum(alternate[1].values()), sum(counts.values()))
                    variants.append(alternate)
            for result, totals in variants:
                self.assertEqual([d for d, _ in result], dates)
                observed = Counter(name for _, name in result if name is not None)
                for name in people:
                    self.assertEqual(totals[name], observed[name])
                    booked = [d for d, selected in result if selected == name]
                    self.assertTrue(all(d in people[name] for d in booked))
                    self.assertTrue(all((b - a).days >= gap for a, b in zip(booked, booked[1:])))
            self.assertEqual(json.dumps({name: [d.isoformat() for d in ds] for name, ds in people.items()}), original)

    def test_1500_performer_import_keeps_valid_entries_after_bad_blocks(self):
        text = '\n'.join(f'Person {i} - ' + ('2/30/2026' if i % 100 == 0 else 'All except 11/10') for i in range(1500))
        result = parse_import(text, 2026, 11, DATES)
        self.assertEqual(len(result.availability), 1485)
        self.assertEqual(len([note for note in result.notes if 'skipped:' in note]), 15)
        self.assertTrue(all(dates == [DATES[0], DATES[2]] for dates in result.availability.values()))

    def test_600_roster_round_trips_keep_names_ids_and_untouched_data(self):
        schedule = self.store.create('Roster stress')
        self.store.save(schedule, fixture(0, 15))
        rng = random.Random(36)
        next_id = 15
        for cycle in range(600):
            data = self.store.load(schedule)['data']
            drafts = editor_drafts(data)
            action = rng.randrange(3)
            if action == 0 or not drafts:
                drafts.append(dict(id=f'new-{next_id}', name=f'New {next_id}', availability='All', status='Draft'))
                next_id += 1
            elif action == 1:
                drafts.pop(rng.randrange(len(drafts)))
            else:
                draft = rng.choice(drafts)
                draft['name'] = f'Renamed {next_id}'
                next_id += 1
            self.store.save_inline_editor(schedule, drafts)
            data = self.store.load(schedule)['data']
            expected_names = [d['name'] for d in drafts]
            expected_ids = [d['id'] for d in drafts]
            self.assertEqual([p['name'] for p in data['performers']], expected_names)
            sync_schedule_performers(data, data['performers'])
            self.store.save(schedule, data)
            reopened = CampaignStore(self.store.path).load(schedule)['data']
            self.assertEqual([d['name'] for d in reopened['availability_drafts']], expected_names)
            self.assertEqual([d['id'] for d in reopened['availability_drafts']], expected_ids)
            self.assertEqual(reopened['notes'], 'Notes 0')
            self.assertEqual(reopened['open_dates'], DATE_TEXT)

    def test_overlapping_notes_and_roster_saves_preserve_both_fields(self):
        schedule = self.store.create('Overlapping saves')
        self.store.save(schedule, fixture(0, 1))
        barrier = threading.Barrier(4)
        def worker(kind):
            local = CampaignStore(self.store.path)
            barrier.wait()
            for i in range(125):
                if kind == 0:
                    local.set_notes(schedule, f'Note {i}')
                elif kind == 1:
                    local.save_inline_editor(schedule, [dict(id='0-0', name='Person 0-0', availability=f'Raw {i}', status='Draft')])
                else:
                    local.update_fields(schedule, {f'worker_{kind}': i})
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(worker, range(4)))
        data = self.store.load(schedule)['data']
        self.assertEqual(data['notes'], 'Note 124')
        self.assertEqual(data['availability_drafts'][0]['availability'], 'Raw 124')
        self.assertEqual(data['worker_2'], 124)
        self.assertEqual(data['worker_3'], 124)
        with sqlite3.connect(self.store.path) as connection:
            self.assertEqual(connection.execute('PRAGMA integrity_check').fetchone()[0], 'ok')

    def test_duplicate_rename_does_not_silently_drop_confirmed_availability(self):
        schedule = self.store.create('Duplicate rename')
        data = fixture(0, 2)
        data['performers'][1]['availability'] = '11/10/2026'
        self.store.save(schedule, data)
        drafts = editor_drafts(data)
        drafts[1]['name'] = drafts[0]['name'].upper()
        with self.assertRaises(ValueError):
            self.store.save_inline_editor(schedule, drafts)
        self.assertEqual(self.store.load(schedule)['data'], data)

    def test_600_schedule_library_search_folder_changes_and_restart(self):
        folders = [self.store.create_folder(f'Folder {i}') for i in range(3)]
        ids = []
        for i in range(600):
            schedule = self.store.create(f'Schedule {i}', folders[i % 3])
            self.store.save(schedule, fixture(i, 30))
            ids.append(schedule)
        reopened = CampaignStore(self.store.path)
        for i in (0, 17, 257, 599):
            query = f'Person {i}-'
            self.assertEqual([r['id'] for r in reopened.list_campaigns(query)], [ids[i]])
            self.assertEqual([r['id'] for r in reopened.list_campaigns(query, folders[i % 3])], [ids[i]])
        reopened.move_to_folder(ids[:100], folders[2])
        reopened.reorder_folders(list(reversed(folders)))
        self.assertEqual([r['id'] for r in reopened.list_folders()], list(reversed(folders)))
        self.assertEqual(len(reopened.list_campaigns()), 600)
        for i in range(100):
            self.assertEqual(reopened.load(ids[i])['data'], fixture(i, 30))


@unittest.skipUnless(STRESS and GUI, 'Opt-in desktop stress suite')
class StressDesktopTests(unittest.TestCase):
    def setUp(self):
        from main import AvailabilityApp
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = CampaignStore(Path(self.temp.name) / 'desktop.sqlite3')
        self.app = AvailabilityApp(store=self.store)
        self.errors = []
        self.app.report_callback_exception = lambda *error: self.errors.append(error)
        self.addCleanup(self.cleanup_app)
        self.app.update()

    def cleanup_app(self):
        self.app._close()
        self.assertEqual(self.errors, [])

    def populate(self, schedules, performers):
        ids = []
        for i in range(schedules):
            schedule = self.store.create(f'Schedule {i}')
            self.store.save(schedule, fixture(i, performers))
            ids.append(schedule)
        self.app._refresh_campaigns()
        self.app.update()
        return ids

    def test_36_expanded_schedules_864_performers_search_scroll_and_collapse(self):
        ids = self.populate(36, 24)
        self.app._set_all_schedules_expanded(True)
        self.app.update()
        canvas = self.app.campaign_list.canvas
        canvas.yview_moveto(1)
        self.app.update()
        last_id = self.app.campaign_list.get_children()[-1]
        last = self.app._inline_editor(last_id).rows[-1]['frame']
        self.assertTrue(last.winfo_ismapped())
        self.assertGreaterEqual(last.winfo_rooty(), canvas.winfo_rooty())
        self.assertLessEqual(last.winfo_rooty() + last.winfo_height(), canvas.winfo_rooty() + canvas.winfo_height())
        self.assertLess(sum(data['editor'] is not None for data in self.app.campaign_list._items.values()), len(ids))
        self.app.schedule_search.set('Person 12-3')
        self.app.update()
        self.assertEqual(self.app.campaign_list.get_children(), (ids[12],))
        editor = self.app._inline_editor(ids[12])
        self.assertEqual([r['name'].get() for r in editor.rows if r['frame'].winfo_ismapped()], ['Person 12-3'])
        self.app._clear_filters()
        self.app.update()
        self.app._set_all_schedules_expanded(False)
        self.app.update()
        for schedule in ids:
            self.assertEqual(self.store.load(schedule)['data'], fixture(ids.index(schedule), 24))
        self.assertEqual(self.errors, [])

    def test_scrolling_away_saves_drafts_and_scrolling_back_restores_them(self):
        self.populate(18, 24)
        self.app._set_all_schedules_expanded(True)
        self.app.update()
        listing = self.app.campaign_list
        first_id = listing.get_children()[0]
        editor = self.app._inline_editor(first_id)
        editor.rows[0]['name'].set('Renamed while editing')
        editor.rows[0]['text'].delete('1.0', 'end')
        editor.rows[0]['text'].insert('1.0', 'November 17')
        listing.canvas.yview_moveto(1)
        self.app.update()
        saved = self.store.load(first_id)['data']['availability_drafts'][0]
        self.assertEqual(saved['name'], 'Renamed while editing')
        self.assertEqual(saved['availability'], 'November 17')
        listing.canvas.yview_moveto(0)
        self.app.update()
        self.assertTrue(editor.rows[0]['frame'].winfo_ismapped())
        self.assertEqual(editor.rows[0]['text'].get('1.0', 'end-1c'), 'November 17')
        self.assertEqual(self.errors, [])

    def test_50_edit_generate_alternate_and_view_switch_cycles(self):
        from appearance import PALETTES
        ids = self.populate(5, 8)
        for cycle in range(50):
            schedule = ids[cycle % len(ids)]
            self.app._open_campaign(schedule)
            self.app.update()
            field = self.app.performers[0][1]
            field.focus_force()
            self.app.update()
            field.delete('1.0', 'end')
            field.insert('1.0', 'All except November 10' if cycle % 2 else 'All')
            self.app.page_canvas.event_generate('<Button-1>', x=5, y=5)
            self.app.update()
            self.app.notes_text.insert('end', f' [{cycle}]')
            self.app._generate()
            self.app._try_another_arrangement()
            self.app._show_home()
            if cycle % 10 == 0:
                self.app._change_appearance(list(PALETTES)[cycle // 10])
            self.app.update()
            data = self.store.load(schedule)['data']
            self.assertEqual([p['name'] for p in data['performers']], [d['name'] for d in data['availability_drafts']])
            self.assertEqual(len(data['rows']), 3)
            self.assertIn(f'[{cycle}]', data['notes'])
            self.assertEqual(self.errors, [])

    def test_100_notes_edits_leave_no_obscuring_frames_or_pending_save_callbacks(self):
        ids = self.populate(3, 0)
        for cycle in range(100):
            schedule = ids[cycle % len(ids)]
            self.app._edit_inline_notes(schedule)
            field = self.app.home_notes
            wrapper = field.frame
            field.focus_force()
            self.app.update()
            field.delete('1.0', 'end')
            field.insert('1.0', f'Note {cycle}')
            self.app.campaign_list.canvas.event_generate('<Button-1>', x=5, y=5)
            self.app.update()
            self.assertFalse(wrapper.winfo_exists())
            self.assertIsNone(self.app._home_notes_job)
            self.assertEqual(self.store.load(schedule)['data']['notes'], f'Note {cycle}')
            self.assertEqual(self.errors, [])


if __name__ == '__main__':
    unittest.main()
