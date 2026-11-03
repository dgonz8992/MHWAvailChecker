"""Regression cases taken from the mixed-format availability list."""
from datetime import datetime, timedelta
from pathlib import Path
import unittest

from availability_import import extract_dates, parse_import
from scheduler import parse_dates


def dates(text):
    return parse_dates(text, 2026, 10)


class WeekdayAvailabilityTests(unittest.TestCase):
    def setUp(self):
        self.open_dates = [datetime(2026, 11, 1) + timedelta(days=i) for i in range(95)]

    def test_each_weekday_can_be_included_or_excluded(self):
        for weekday, name in enumerate(('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')):
            for raw, include in ((f'Only {name}s', True), (f'All except {name}s', False)):
                with self.subTest(raw=raw):
                    result = parse_import(f'Alex - {raw}', 2026, 11, self.open_dates)
                    self.assertEqual(result.availability['Alex'],
                                     [d for d in self.open_dates if (d.weekday() == weekday) == include])
                    self.assertFalse(result.notes)

    def test_weekday_groups_multiple_days_and_multiline_exclusions(self):
        for raw, allowed in (('all except Fridays and Saturdays', {0, 1, 2, 3, 6}),
                             ('All except\nFridays\nSaturdays', {0, 1, 2, 3, 6}),
                             ('Only Saturdays and Sundays', {5, 6}),
                             ('Weekends', {5, 6}), ('All except weekends', set(range(5))),
                             ('all except weekdays', {5, 6})):
            with self.subTest(raw=raw):
                result = parse_import(f'Alex - {raw}', 2026, 11, self.open_dates)
                self.assertEqual(result.availability['Alex'], [d for d in self.open_dates if d.weekday() in allowed])
                self.assertFalse(result.notes)

    def test_exclusions_mix_recurring_weekdays_and_specific_dates(self):
        result = parse_import('Alex - All except Fridays and 11/7/2026', 2026, 11, self.open_dates)
        self.assertEqual(result.availability['Alex'], [d for d in self.open_dates
                         if d.weekday() != 4 and d != datetime(2026, 11, 7)])
        result = parse_import('Alex - All except Friday 11/6 and Saturday 11/7', 2026, 11, self.open_dates)
        self.assertEqual(result.availability['Alex'], [d for d in self.open_dates
                         if d not in (datetime(2026, 11, 6), datetime(2026, 11, 7))])

    def test_weekday_exclusion_can_be_scoped_to_a_month(self):
        result = parse_import('Alex - All except Fridays in November', 2026, 11, self.open_dates)
        self.assertEqual(result.availability['Alex'], [d for d in self.open_dates if not (d.weekday() == 4 and d.month == 11)])

    def test_no_matching_weekday_is_a_valid_rule(self):
        saturday = [datetime(2026, 11, 7)]
        for raw, expected in (('All except Fridays', saturday), ('Only Fridays', [])):
            with self.subTest(raw=raw):
                result = parse_import(f'Alex - {raw}', 2026, 11, saturday)
                self.assertEqual(result.availability, {'Alex': expected})
                self.assertFalse(result.notes)


class MixedAvailabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.open_dates = [datetime(2026, 10, 1) + timedelta(days=offset) for offset in range(212)]
        cls.text = (Path(__file__).parent / 'tests/fixtures/availability_examples.txt').read_text()
        cls.result = parse_import(cls.text, 2026, 10, cls.open_dates)

    def test_complete_example_has_expected_confirmed_performers(self):
        self.assertEqual(len(self.result.availability), 80)
        self.assertFalse(any('script' in name.casefold() for name in self.result.availability))
        for name in ('DJ Ortiz', 'DJ Nott Dana', 'Michael James', 'Chris Bank', 'Will Baxter',
                     'Shed', 'Vetted Good Fits', 'Potential Good Fits', 'Bin 47'):
            with self.subTest(name=name):
                self.assertNotIn(name, self.result.availability)
        self.assertTrue(any('DJ Ortiz' in note and 'has no dates' in note for note in self.result.notes))

    def test_numeric_written_month_and_shared_day_examples(self):
        expected = {
            'DJ Parallel Attractions': '11/19 11/20 11/21 11/26 11/27 11/28',
            'DJ Mahealani': '11/26 12/5 12/11 12/12 12/17 12/18 1/2',
            'DJ BittyScorp': '11/20 11/27 11/28 12/4 12/5 12/12 12/18 12/19 1/1 1/2',
            'Soul Wagon': '12/4 12/11 12/19',
            'Aautumn': '12/10 12/17',
            'Chris Yak': '11/28 12/14 12/26',
            "Karrie O'Neill": '12/26 12/27 12/28',
            'Fleur Wood': '12/4 12/5 12/11 12/12 1/2 1/16 1/29 1/23',
            'Valerie Vampola': '12/3',
        }
        for name, values in expected.items():
            with self.subTest(name=name):
                self.assertEqual(self.result.availability[name], dates(values))

    def test_month_headings_and_ordinal_typos(self):
        self.assertEqual(self.result.availability['DJ Nite Kap'], dates('11/6 11/13 12/4 12/11 12/18 1/8 1/15 1/22 1/29'))
        self.assertEqual(self.result.availability['Michelle Winters'], dates('1/9 1/16 1/23 2/6 2/13 2/27 3/6 3/20 3/27'))
        mitch = self.result.availability['Mitch Carter']
        self.assertEqual(len(mitch), 45)
        self.assertEqual(mitch.count(datetime(2027, 1, 22)), 1)
        self.assertIn(datetime(2027, 3, 6), mitch)

    def test_short_and_long_years_are_preserved(self):
        self.assertEqual(self.result.availability['Steve Schuffert'], dates('1/11/27 1/18/27 2/8/27 2/22/27 3/8/27 3/22/27 4/5/27'))
        self.assertEqual(self.result.availability['DJ Raquiqui'][0], datetime(2026, 11, 26))
        self.assertEqual(self.result.availability['DJ Raquiqui'][-1], datetime(2027, 1, 2))
        self.assertEqual(extract_dates('11/26/2025, 2027-01-02, 01-03-2027', 2026, 10),
                         [datetime(2025, 11, 26), datetime(2027, 1, 2), datetime(2027, 1, 3)])

    def test_ranges_expand_inclusively_across_new_year(self):
        bentley = self.result.availability['DJ Bentley']
        self.assertEqual(len(bentley), 81)
        self.assertIn(datetime(2026, 12, 21), bentley)
        self.assertNotIn(datetime(2026, 12, 25), bentley)
        self.assertIn(datetime(2027, 1, 31), bentley)
        self.assertNotIn(datetime(2027, 2, 8), bentley)
        self.assertEqual(self.result.availability['Tony Elison'], dates('1/2 1/4 1/5 1/6 1/7 1/8'))
        self.assertEqual(extract_dates('12/30-1/2', 2026, 10), dates('12/30 12/31 1/1 1/2'))

    def test_hyphen_date_chain_is_a_list_with_a_review_note(self):
        self.assertEqual(self.result.availability['DJ Ramone Ambassador'], dates('12/5 12/20 12/21 12/27 12/28 12/25 12/31'))
        self.assertTrue(any('DJ Ramone Ambassador' in note and 'chain' in note for note in self.result.notes))

    def test_all_and_month_scoped_rules(self):
        self.assertEqual(self.result.availability['DJ Brandon Shabazz'], self.open_dates)
        self.assertEqual(self.result.availability['Shayna Sands'], [d for d in self.open_dates if d.month in (12, 1)])
        self.assertEqual(self.result.availability['DJ Mz Rico'], [d for d in self.open_dates if d.month == 1])
        self.assertEqual(self.result.availability['Late Native'], [d for d in self.open_dates if d not in dates('12/24 12/31')])
        self.assertEqual(self.result.availability['Eleni Witte'], [d for d in self.open_dates if d != datetime(2027, 1, 3)])
        self.assertEqual(self.result.availability['Cooper Tisdale'],
                         sorted([d for d in self.open_dates if d.month == 1 and d.day not in (30, 31)] + dates('2/6 2/7 2/21 2/28 3/7 3/14 3/21 3/28')))

    def test_weekday_rules_use_open_dates_and_apply_exceptions(self):
        expected = [d for d in self.open_dates if d.weekday() in (6, 1) and d not in dates('12/20 2/14 1/8 1/22')]
        self.assertEqual(self.result.availability['DJ Cam Reeve'], expected)
        explicit = set(dates('12/26 12/28 1/2 1/11 1/24 2/1 2/15 2/21 3/1 3/7 3/15 3/21 3/28'))
        recurring = {d for d in self.open_dates if d.weekday() in (0, 3, 5, 6)}
        self.assertEqual(self.result.availability['DJ Josh (UT)'], sorted(recurring | explicit))

    def test_checkmarks_ignore_unchecked_dates_rates_and_timestamps(self):
        self.assertEqual(self.result.availability['DJ EyeQue (CA)'],
                         dates('12/4 12/5 12/18 12/19 12/20 12/22 12/23 12/26 12/27 12/29 12/30 12/31'))
        result = parse_import('Alex - copied from chat\n11:12 am\nAll except 10/31', 2026, 10, self.open_dates)
        self.assertEqual(result.availability['Alex'], [d for d in self.open_dates if d != datetime(2026, 10, 31)])

    def test_tentative_dates_are_omitted_and_ambiguous_entries_are_skipped(self):
        self.assertNotIn(datetime(2027, 2, 14), self.result.availability['Steven Bosco'])
        for name in ('Jonny Wild', 'DJ David Aaron'):
            self.assertNotIn(name, self.result.availability)
            self.assertTrue(any(name in note and 'skipped' in note for note in self.result.notes))
        self.assertTrue(any('Tentative date omitted' in note for note in self.result.notes))

    def test_script_boundaries_and_names_without_dates_do_not_inherit(self):
        result = parse_import('Alex - November 20\nDJ Ortiz\nScript other\n12/3\nTyler - 12/5', 2026, 10)
        self.assertEqual(result.availability, {'Alex': dates('11/20'), 'Tyler': dates('12/5')})
        self.assertTrue(any('DJ Ortiz' in note for note in result.notes))
        self.assertTrue(any('Line 4' in note for note in result.notes))

    def test_bad_performer_does_not_stop_valid_entries_or_import_partial_block(self):
        result = parse_import('Alex - 11/20\n2/30\nTyler - 12/5', 2026, 10)
        self.assertEqual(result.availability, {'Tyler': dates('12/5')})
        self.assertTrue(any('Alex' in note and 'Invalid date' in note for note in result.notes))
        self.assertIn('REVIEW NOTES', result.preview())

    def test_explicit_holiday_rules_and_reversed_ranges(self):
        result = parse_import("Alex - All except Christmas and New Year's Day", 2026, 10, self.open_dates)
        self.assertEqual(result.availability['Alex'], [d for d in self.open_dates if d not in dates('12/25 1/1')])
        result = parse_import('Alex - 12/10-12/5', 2026, 10)
        self.assertFalse(result.availability)
        self.assertTrue(any('ends before' in note for note in result.notes))

    def test_repeated_names_merge_and_report_that_script_sections_are_ignored(self):
        self.assertEqual(self.result.availability['Ben Reneer'], dates('11/29 12/14 1/2 1/9 1/23 1/30'))
        self.assertTrue(any('Ben Reneer: repeated entries combined' in note for note in self.result.notes))


if __name__ == '__main__':
    unittest.main()
