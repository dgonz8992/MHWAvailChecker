"""Exact expectations for the second set of 50 pasted availability examples."""
from datetime import datetime
from pathlib import Path
import unittest

from availability_import import parse_import
from scheduler import infer_date_context, parse_dates

MONTH_DAYS = {
    1: [3, 7, 11, 15, 19, 23, 27, 31], 2: [4, 8, 12, 16, 20, 24, 28],
    3: [4, 8, 12, 16, 20, 24, 28], 4: [1, 5, 9, 13, 17, 21, 25, 29],
    5: [3, 7, 11, 15, 19, 23, 27, 31], 6: [4, 8, 12, 16, 20, 24, 28],
    7: [2, 6, 10, 14, 18, 22, 26, 30], 8: [3, 7, 11, 15, 19, 23, 27, 31],
    9: [4, 8, 12, 16, 20, 24, 28], 10: [2, 6, 10, 14, 18, 22, 26, 30],
    11: [3, 7, 11, 15, 19, 23, 27], 12: [1, 5, 9, 13, 17, 21, 25, 29],
}
OPEN_DATES = [datetime(2027, month, day) for month, days in MONTH_DAYS.items() for day in days]
OPEN_DATES += [datetime(2028, month, day) for month, days in
               {1: [5, 13, 21], 2: [2, 10, 18], 3: [1, 9, 17]}.items() for day in days]


def expected_dates(text):
    return parse_dates(text, 2027, 1)


EXPECTED = {
    'Alex Mercer': '1/3 1/11 1/19 1/27',
    'Brianna Cole': '1/3 1/7 1/15 1/23',
    'Caleb Stone': '1/3 2/4 3/4 4/1',
    'Dani Brooks': '1/11 2/8 3/8 4/5',
    'Ethan Vale': '1/15 2/12 3/12 4/9',
    'Fiona Hart': '1/3 1/7 1/19 2/4 2/16 2/28',
    'Isaac Monroe': '3/4 3/12 3/20 3/28',
    'Jade Ellis': '4/1 4/9 4/17 4/25',
    'Kai Bennett': '5/3 5/7 5/19 5/23 5/31',
    'Lena Frost': '6/4 6/12 6/20 6/28',
    'Miles Rowan': '7/2 7/10 7/18 7/26 7/30',
    'Nora Blake': '8/3 8/11 8/19 8/27',
    'Owen Hayes': '9/4 9/12 9/20 9/28',
    'Piper Quinn': '10/2 10/10 10/18 10/26',
    'Quentin Marsh': '11/3 11/11 11/19 11/27',
    'Riley West': '12/1 12/9 12/17 12/21 12/29',
    'Sasha Wynn': '1/5/2028 1/21/2028 2/10/2028 3/9/2028',
    'Theo Grant': '1/13/2028 2/2/2028 2/18/2028 3/17/2028',
    'Cora Finch': '4/1 4/5 4/13 4/21 4/29',
    'Declan Pierce': '5/11 5/15 6/8 6/16',
    'Eliza Shaw': '7/6 7/14 7/22 7/30',
    'Felix North': '8/7 8/15 8/23 8/31',
    'Gia Palmer': '9/8 9/16 9/24',
    'Holden Rivers': '10/6 10/14 10/22 10/30',
    'Ivy Sloan': '11/7 11/15 11/23',
    'Jonah Crest': '12/5 12/13 12/21 12/29',
    'Keira Moss': '1/5/2028 1/13/2028 1/21/2028 2/2/2028 2/10/2028 2/18/2028',
    'Maya Rhodes': '1/3 3/4 5/3 7/2 9/4 11/3',
    'Nico Wilder': '1/31 2/28 3/28 4/29',
    'Opal James': '5/3 5/11 5/19 5/27',
    'Sienna Fox': '8/3 8/19 8/31 9/16',
    'Tristan Bell': '9/8 9/24 10/6 10/22',
    'Uma Brooks': '11/7 11/19 12/1 12/17',
    'Vera Knight': '12/9/2027 12/25/2027 1/5/2028',
    'Wesley Moon': '1/13/2028 1/21/2028 2/2/2028 2/18/2028 3/1/2028 3/17/2028',
    'Zane Hollow': '1/7 2/12 4/17 6/24 8/31',
    'Amber Cove': '3/8 3/24 4/13 4/25 5/7 5/23',
    'Blake Arden': '7/6 7/18 7/26 8/7 8/15 8/27',
    'Dorian Ash': '12/1/2027 12/5/2027 12/13/2027 12/29/2027 1/5/2028 1/21/2028',
    'Emery Voss': '2/2/2028 2/10/2028 3/1/2028 3/9/2028',
}
EXPECTED = {name: expected_dates(values) for name, values in EXPECTED.items()}
EXPECTED.update({
    'Gavin Reed': [d for d in OPEN_DATES if d.year == 2027 and d.month == 1 and d.day != 23],
    'Harper Lane': [d for d in OPEN_DATES if d.year == 2027 and d.month == 2],
    'Aria Wells': [d for d in OPEN_DATES if d.year == 2027 and d.month in (1, 2)],
    'Beckett Ross': [d for d in OPEN_DATES if d.year == 2027 and d.month == 3 and d.day != 16],
    'Luca Sterling': [d for d in OPEN_DATES if d.year == 2028 and d.month == 3],
    'Paxton Grey': [d for d in OPEN_DATES if datetime(2027, 6, 4) <= d <= datetime(2027, 6, 20)],
    'Remy Lake': [d for d in OPEN_DATES if d.year == 2027 and d.month == 7 and d.day not in (2, 30)],
    'Xavier Dale': OPEN_DATES,
    'Yara Bloom': [d for d in OPEN_DATES if d.year == 2027 and d != datetime(2027, 12, 25)],
    'Celeste Ray': [d for d in OPEN_DATES if datetime(2027, 9, 12) <= d <= datetime(2027, 11, 15)],
})


class AdditionalAvailabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (Path(__file__).parent / 'tests/fixtures/additional_availability.txt').read_text()
        cls.result = parse_import(cls.source, *infer_date_context(OPEN_DATES), OPEN_DATES)

    def test_every_supplied_example_and_each_example_in_isolation(self):
        self.assertEqual(set(self.result.availability), set(EXPECTED))
        for line in self.source.splitlines():
            name = line.split(' - ', 1)[0]
            with self.subTest(name=name):
                self.assertEqual(self.result.availability[name], EXPECTED[name])
                # Brianna has no explicit year, so use the actual open-date context
                # when testing her otherwise intentionally unqualified date list.
                context = infer_date_context(OPEN_DATES) if name == 'Brianna Cole' else (2025, 10)
                alone = parse_import(line, *context, OPEN_DATES)
                self.assertEqual(alone.availability.get(name), EXPECTED[name], alone.notes)
        self.assertFalse(any('skipped:' in note for note in self.result.notes))

    def test_written_year_scope_overrides_a_different_open_date_context(self):
        for name in ('Caleb Stone', 'Sasha Wynn', 'Wesley Moon', 'Dorian Ash', 'Emery Voss'):
            with self.subTest(name=name):
                source = next(line for line in self.source.splitlines() if line.startswith(name + ' - '))
                result = parse_import(source, 2025, 10, OPEN_DATES)
                self.assertEqual(result.availability[name], EXPECTED[name])

    def test_supplied_windows_do_not_invent_unlisted_dates(self):
        self.assertEqual(len(self.result.availability['Paxton Grey']), 5)
        self.assertNotIn(datetime(2027, 6, 5), self.result.availability['Paxton Grey'])
        self.assertEqual(len(self.result.availability['Celeste Ray']), 17)

    def test_all_good_and_all_year_do_not_expand_an_explicit_date_list(self):
        self.assertEqual(len(self.result.availability['Holden Rivers']), 4)
        self.assertEqual(len(self.result.availability['Kai Bennett']), 5)
        self.assertEqual(len(self.result.availability['Caleb Stone']), 4)

    def test_year_exclusions_and_other_dates_do_not_add_availability(self):
        self.assertTrue(all(d.year == 2027 for d in self.result.availability['Yara Bloom']))
        self.assertNotIn(datetime(2027, 12, 25), self.result.availability['Yara Bloom'])
        self.assertEqual(self.result.availability['Opal James'], EXPECTED['Opal James'])
        self.assertEqual(self.result.availability['Emery Voss'], EXPECTED['Emery Voss'])

    def test_unrecognized_negative_qualifications_do_not_silently_import(self):
        result = parse_import("Alex - Jan 3, 2027. The other date 1/3 doesn't work.", 2027, 1, OPEN_DATES)
        self.assertNotIn('Alex', result.availability)
        self.assertTrue(any('Unclear negative qualification' in note for note in result.notes))

    def test_claimed_supplied_count_mismatch_appears_in_review_notes(self):
        result = parse_import('Alex - All three supplied March 2028 dates', 2027, 1, [datetime(2028, 3, 1)])
        self.assertEqual(result.availability['Alex'], [datetime(2028, 3, 1)])
        self.assertTrue(any('but 1 open dates match' in note for note in result.notes))

    def test_explicit_date_year_is_not_replaced_by_general_year_phrase(self):
        result = parse_import('Alex - January 3, 2027 and 1/5/2028', 2025, 10, OPEN_DATES)
        self.assertEqual(result.availability['Alex'], [datetime(2027, 1, 3), datetime(2028, 1, 5)])


if __name__ == '__main__':
    unittest.main()
