import unittest
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

from scheduler import generate_schedule, alternate_schedule, parse_dates, parse_open_dates, infer_date_context, parse_availability, extract_dates

# Keep regression data independent of the application's empty initial inputs.
baseline = json.loads((Path(__file__).parent / 'tests/fixtures/original_schedule.json').read_text())
availability, openDates = baseline['availability'], baseline['open_dates']


class OpenDateTests(unittest.TestCase):
    def test_availability_years_come_from_earliest_open_date(self):
        context = infer_date_context(parse_open_dates('1/4/2027 11/3/2026 12/8/2026'))
        self.assertEqual(context, (2026, 11))
        self.assertEqual(parse_dates('12/8 1/4', *context),
                         [datetime(2026, 12, 8), datetime(2027, 1, 4)])

    def test_context_moves_with_open_dates_and_keeps_explicit_years(self):
        context = infer_date_context(parse_open_dates('2/5/2031 1/4/2031'))
        self.assertEqual(parse_dates('1/4 2/5 12/8/2026', *context),
                         [datetime(2026, 12, 8), datetime(2031, 1, 4), datetime(2031, 2, 5)])

    def test_empty_open_dates_cannot_supply_a_year(self):
        with self.assertRaisesRegex(ValueError, 'Enter at least one open date'):
            infer_date_context([])

    def test_explicit_dates_sort_deduplicate_and_accept_leading_zeroes(self):
        self.assertEqual(parse_open_dates('1/4/2027, 11/03/2026\n11/3/2026'),
                         [datetime(2026, 11, 3), datetime(2027, 1, 4)])

    def test_rejects_missing_short_or_invalid_years_and_other_formats(self):
        for text in ('11/3', '11/3/26', '11/3/202', '11/3/20260', '11/3/0000',
                     '2026-11-03', 'November 3, 2026', '11.3.2026', '13/3/2026',
                     '2/29/2027', '11/3/2026 12/1'):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, 'Use M/D/YYYY'):
                parse_open_dates(text)

    def test_leap_year_and_defaults(self):
        self.assertEqual(parse_open_dates('2/29/2028'), [datetime(2028, 2, 29)])
        self.assertEqual(len(parse_open_dates(','.join(openDates))), 21)


class AvailabilityImportTests(unittest.TestCase):
    def test_extracts_dates_from_prose_punctuation_and_bullets(self):
        text = '''Sarah Navy - Available Fridays (11/6), 11 / 13; and Saturday 12/5.
Thanks!
• 12/12 — Saturday works too
Ben Kmosko - Here are my dates:
* 11/7, 11/14 & 11/21!'''
        people = parse_availability(text, 2026, 10)
        self.assertEqual(people['Sarah Navy'], parse_dates('11/6 11/13 12/5 12/12', 2026, 10))
        self.assertEqual(people['Ben Kmosko'], parse_dates('11/7 11/14 11/21', 2026, 10))

    def test_extracts_exclusions_from_surrounding_words(self):
        dates = parse_dates('10/24 10/31 11/7', 2026, 10)
        self.assertEqual(parse_availability('Alex - All except Friday (10/31) and Saturday 11/7.', 2026, 10, dates),
                         {'Alex': [datetime(2026, 10, 24)]})

    def test_extraction_still_rejects_invalid_date_tokens(self):
        for text in ('Available 2/30.', 'Dates: 13/5'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                extract_dates(text, 2026, 10)

    def test_all_and_exceptions_mixed_with_explicit_dates(self):
        text = '''DJ Presyce - All
DJ Retrospec - All except 10/31
DJ Koe - All
DJ Kent Clarc - 11/6, 11/7, 11/13, 12/5, 12/12
Bobby Ross - 10/24, 11/7, 11/14, 11/21, 12/5, 12/12'''
        dates = parse_dates('10/24 10/31 11/6 11/7 11/13 11/14 11/21 12/5 12/12', 2026, 10)
        people = parse_availability(text, 2026, 10, dates)
        self.assertEqual(people['DJ Presyce'], dates)
        self.assertEqual(people['DJ Koe'], dates)
        self.assertEqual(people['DJ Retrospec'], [date for date in dates if date != datetime(2026, 10, 31)])
        self.assertEqual(people['DJ Kent Clarc'], parse_dates('11/6 11/7 11/13 12/5 12/12', 2026, 10))
        self.assertEqual(people['Bobby Ross'], parse_dates('10/24 11/7 11/14 11/21 12/5 12/12', 2026, 10))

    def test_all_is_case_insensitive_and_exceptions_can_span_lines(self):
        dates = parse_dates('12/31 1/4 1/11', 2026, 10)
        people = parse_availability('Alex - aLl ExCePt\n12/31, 1/4\n\nTyler - ALL', 2026, 10, dates)
        self.assertEqual(people['Alex'], [datetime(2027, 1, 11)])
        self.assertEqual(people['Tyler'], dates)

    def test_all_requires_open_dates_and_valid_exceptions(self):
        dates = parse_dates('10/31', 2026, 10)
        for text, open_dates in [('Alex - All', []), ('Alex - All except 10/31', None),
                                  ('Alex - All except', dates), ('Alex - All except 2/30', dates),
                                  ('Alex - All nonsense', dates)]:
            with self.subTest(text=text, open_dates=open_dates):
                with self.assertRaises(ValueError):
                    parse_availability(text, 2026, 10, open_dates)

    def test_excluding_all_dates_is_valid_and_does_not_change_open_dates(self):
        dates = parse_dates('10/31', 2026, 10)
        people = parse_availability('Alex - All except 10/31, 11/1', 2026, 10, dates)
        self.assertEqual(people, {'Alex': []})
        self.assertEqual(dates, [datetime(2026, 10, 31)])

    def test_users_pasted_format(self):
        text = '''Sarah Navy - 11/5
11/12
11/19
12/3
12/10
12/17
12/24
12/31
Ben Kmosko - 11/5
11/12
11/19

12/3
12/10
12/17
12/31'''
        people = parse_availability(text, 2026, 11)
        self.assertEqual(list(people), ['Sarah Navy', 'Ben Kmosko'])
        self.assertEqual(len(people['Sarah Navy']), 8)
        self.assertEqual(len(people['Ben Kmosko']), 7)
        self.assertIn(datetime(2026, 12, 24), people['Sarah Navy'])
        self.assertNotIn(datetime(2026, 12, 24), people['Ben Kmosko'])

    def test_hyphenated_names_dashes_and_duplicate_headers(self):
        people = parse_availability('Mary-Jane Smith – 12/31, 1/4\nMARY-JANE SMITH — 1/4\n1/11', 2026, 11)
        self.assertEqual(people, {'Mary-Jane Smith': [datetime(2026, 12, 31), datetime(2027, 1, 4), datetime(2027, 1, 11)]})

    def test_header_can_be_followed_by_dates_on_next_line(self):
        self.assertEqual(parse_availability('  Sarah Navy -\n\n11/05\n11/5  ', 2026, 11),
                         {'Sarah Navy': [datetime(2026, 11, 5)]})

    def test_invalid_input_reports_line_and_preserves_strict_validation(self):
        for text, message in [('', 'Paste at least one'), ('11/5', 'Line 1'),
                              ('Sarah Navy - 2/30', 'Line 1: Invalid date'),
                              ('Sarah Navy - 11/5\nFriday 2/30', 'Line 2: Invalid date'),
                              ('Sarah Navy -', 'has no dates')]:
            with self.subTest(text=text):
                with self.assertRaises(ValueError) as error:
                    parse_availability(text, 2026, 11)
                self.assertIn(message, str(error.exception))


class SchedulerTests(unittest.TestCase):
    def test_alternatives_change_assignments_preserve_balance_availability_and_spacing(self):
        dates = [datetime(2026, 11, 3) + timedelta(days=7 * index) for index in range(21)]
        people = {name: dates for name in ('Alex', 'Tyler', 'Sarah')}
        current, _ = generate_schedule(dates, people)
        rng = random.Random(42)
        for _ in range(5):
            rows, counts = alternate_schedule(dates, people, 7, current, rng=rng)
            self.assertNotEqual(rows, current)
            self.assertEqual([date for date, _ in rows], dates)
            self.assertEqual(list(counts.values()), [7, 7, 7])
            for name in people:
                booked = [date for date, person in rows if person == name]
                self.assertTrue(all(date in people[name] for date in booked))
                self.assertTrue(all((right - left).days >= 7 for left, right in zip(booked, booked[1:])))
            current = rows

    def test_alternatives_do_not_trade_booked_dates_for_variation(self):
        dates = parse_dates('11/1 11/2', 2026, 11)
        people = {'Alex': dates, 'Tyler': [dates[0]]}
        full = [(dates[0], 'Tyler'), (dates[1], 'Alex')]
        self.assertIsNone(alternate_schedule(dates, people, 7, full, rng=random.Random(1)))
        original, _ = generate_schedule(dates, people)
        rows, _ = alternate_schedule(dates, people, 7, original, rng=random.Random(1))
        self.assertEqual(rows, full)

    def test_no_alternative_when_assignments_are_forced_or_every_date_is_unfilled(self):
        dates = parse_dates('11/1 11/8', 2026, 11)
        for people in ({'Alex': dates}, {'Alex': []}):
            current, _ = generate_schedule(dates, people)
            self.assertIsNone(alternate_schedule(dates, people, 7, current))

    def test_original_schedule_stays_balanced(self):
        dates = parse_open_dates(','.join(openDates))
        people = {name: parse_dates(','.join(values), 2026, 11)
                  for name, values in availability.items()}
        rows, counts = generate_schedule(dates, people)
        self.assertEqual(len(rows), 21)
        self.assertEqual(list(counts.values()), [7, 7, 7])
        for date, name in rows:
            self.assertIn(date, people[name])
        for name in people:
            bookings = [date for date, selected in rows if selected == name]
            self.assertTrue(all((b - a).days >= 7 for a, b in zip(bookings, bookings[1:])))

    def test_dates_are_sorted_deduplicated_and_roll_into_next_year(self):
        self.assertEqual(parse_dates('1/4, 12/8\n11/3 11/03', 2026, 11),
                         [datetime(2026, 11, 3), datetime(2026, 12, 8), datetime(2027, 1, 4)])

    def test_invalid_dates_and_settings_are_rejected(self):
        for text, year, month in [('2/30', 2026, 11), ('13/1', 2026, 11),
                                  ('hello', 2026, 11), ('1/2/3', 2026, 11),
                                  ('1/1', 2026, 0), ('1/1', 10000, 11)]:
            with self.subTest(text=text, year=year, month=month):
                with self.assertRaises(ValueError):
                    parse_dates(text, year, month)

    def test_gap_allows_exactly_seven_days_and_reports_unfilled(self):
        dates = parse_dates('11/1 11/7 11/8', 2026, 11)
        rows, counts = generate_schedule(dates, {'Alex': dates})
        self.assertEqual([name for _, name in rows], ['Alex', None, 'Alex'])
        self.assertEqual(counts, {'Alex': 2})

    def test_fewer_gigs_win_and_ties_follow_order(self):
        dates = parse_dates('11/1 11/2 11/3', 2026, 11)
        rows, counts = generate_schedule(dates, {'Alex': dates, 'Tyler': dates}, minimum_gap=0)
        self.assertEqual([name for _, name in rows], ['Alex', 'Tyler', 'Alex'])
        self.assertEqual(counts, {'Alex': 2, 'Tyler': 1})

    def test_empty_availability_and_negative_gap(self):
        dates = parse_dates('11/3', 2026, 11)
        self.assertEqual(generate_schedule(dates, {'Alex': []}), ([(dates[0], None)], {'Alex': 0}))
        with self.assertRaises(ValueError):
            generate_schedule(dates, {}, -1)


if __name__ == '__main__':
    unittest.main()
