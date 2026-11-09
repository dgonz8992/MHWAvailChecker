"""Confirmation template placeholders remain literal and performer-specific."""
from datetime import datetime
import unittest

from confirmation_templates import DEFAULT_TEMPLATE, render_confirmation, render_schedule_template


class ConfirmationTemplateTests(unittest.TestCase):
    def test_notes_resolve_only_schedule_fields(self):
        result = render_schedule_template('@schedule | @dates | @count | @notes | @performer | @pdates',
                     open_dates=[datetime(2026, 11, 7)], schedule='November',
                     notes='Bring @dates list', booked_count=3)
        self.assertEqual(result, 'November | 11/7/2026 | 3 | Bring @dates list | @performer | @pdates')

    def render(self, template, **overrides):
        values = dict(performer='Alex', confirmed_dates=[datetime(2026, 11, 7)],
                      open_dates=[datetime(2026, 11, 6), datetime(2026, 11, 7)],
                      schedule='November', notes='Bring cables')
        return render_confirmation(template, **dict(values, **overrides))

    def test_default_preserves_existing_script(self):
        self.assertEqual(self.render(DEFAULT_TEMPLATE),
                         'Confirmed for 11/7/2026. Will send over the gig sheets now. '
                         'Please make sure all of the details are correct before signing. Thank you!')

    def test_all_fields_use_the_correct_schedule_and_performer_data(self):
        self.assertEqual(self.render('@performer | @pdates | @dates | @count | @schedule | @notes'),
                         'Alex | 11/7/2026 | 11/6/2026, 11/7/2026 | 1 | November | Bring cables')

    def test_dates_are_chronological_and_include_year_rollover(self):
        dates = [datetime(2027, 1, 2), datetime(2026, 12, 26)]
        self.assertEqual(self.render('@pdates (@count gigs)', confirmed_dates=dates),
                         '12/26/2026, 1/2/2027 (2 gigs)')

    def test_inserted_values_are_not_expanded_recursively(self):
        self.assertEqual(self.render('@performer: @notes', performer='@dates', notes='Contact @performer'),
                         '@dates: Contact @performer')

    def test_unknown_tokens_email_addresses_and_escaped_at_stay_literal(self):
        self.assertEqual(self.render('@unknown @@performer contact@performer.com (@performer)'),
                         '@unknown @performer contact@performer.com (Alex)')

    def test_multiline_template_is_preserved_and_empty_uses_original_default(self):
        self.assertEqual(self.render('Hi @performer!\n@pdates\n@notes'), 'Hi Alex!\n11/7/2026\nBring cables')
        for template in ('', '  \n\t'):
            self.assertEqual(self.render(template), self.render(DEFAULT_TEMPLATE))
