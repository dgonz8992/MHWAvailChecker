"""Contract and failure handling for AI conversion; no paid API calls."""
from copy import deepcopy
from datetime import datetime
import io
import json
import os
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from ai_availability import (AIAvailabilityError, API_URL, MAX_INPUT_CHARS,
                             build_payload, convert_with_ai, validate_result)

DATES = [datetime(2027, 1, 3), datetime(2027, 1, 11)]
SOURCE = 'Alex - January 3 and 11, 2027\nBen - All except January 3'


def extracted():
    return {
        'performers': [{'name': 'Alex', 'available_date_indices': [1, 0, 1],
                        'status': 'confirmed', 'explanation': 'Both January dates.',
                        'source_excerpt': 'Alex - January 3 and 11, 2027'}],
        'skipped_entries': [], 'notes': [],
    }


def api_reply(data=None, status='completed', content=None):
    if content is None:
        content = [{'type': 'output_text', 'text': json.dumps(data or extracted())}]
    body = {'status': status, 'output': [{'type': 'reasoning'}, {'type': 'message', 'content': content}]}
    return io.BytesIO(json.dumps(body).encode())


class AIAvailabilityTests(unittest.TestCase):
    def test_valid_output_maps_to_real_dates_and_deduplicates(self):
        result = validate_result(extracted(), SOURCE, DATES)
        self.assertEqual(result.availability, {'Alex': DATES})
        self.assertIn('AI conversion', result.preview())

    def test_uncertain_performer_is_not_imported(self):
        data = extracted()
        data['performers'][0].update(status='needs_review', explanation='Year is unclear.')
        result = validate_result(data, SOURCE, DATES)
        self.assertFalse(result.availability)
        self.assertTrue(any('Year is unclear' in note for note in result.notes))

    def test_invalid_indices_cannot_add_dates(self):
        for indices in ([-1], [2], [True], [0.0], ['0'], None):
            with self.subTest(indices=indices), self.assertRaises(AIAvailabilityError):
                data = extracted()
                data['performers'][0]['available_date_indices'] = indices
                validate_result(data, SOURCE, DATES)

    def test_unverifiable_name_or_excerpt_is_rejected(self):
        for field, value in (('name', 'Made Up Performer'), ('source_excerpt', 'Alex is available every day')):
            with self.subTest(field=field), self.assertRaises(AIAvailabilityError):
                data = extracted()
                data['performers'][0][field] = value
                validate_result(data, SOURCE, DATES)

    def test_missing_or_wrongly_typed_fields_are_rejected(self):
        for field, value in (('performers', None), ('skipped_entries', {}), ('notes', [1])):
            with self.subTest(field=field), self.assertRaises(AIAvailabilityError):
                data = extracted()
                data[field] = value
                validate_result(data, SOURCE, DATES)
        with self.assertRaises(AIAvailabilityError):
            validate_result({'performers': []}, SOURCE, DATES)

    def test_uncertain_or_skipped_duplicate_removes_confirmed_occurrence(self):
        for skip in (False, True):
            data = extracted()
            if skip:
                data['skipped_entries'] = [{'name': 'Alex', 'reason': 'Conflicting text.'}]
            else:
                second = deepcopy(data['performers'][0])
                second['status'] = 'needs_review'
                data['performers'].append(second)
            result = validate_result(data, SOURCE, DATES)
            self.assertFalse(result.availability)

    def test_clear_empty_selection_is_valid(self):
        data = extracted()
        data['performers'][0]['available_date_indices'] = []
        self.assertEqual(validate_result(data, SOURCE, DATES).availability, {'Alex': []})

    def test_request_uses_structured_output_and_does_not_store_response(self):
        with patch('ai_availability.request.urlopen', return_value=api_reply()) as send:
            result = convert_with_ai(SOURCE, list(reversed(DATES)), api_key='test-key', model='gpt-5-mini')
        self.assertEqual(result.availability, {'Alex': DATES})
        req = send.call_args[0][0]
        self.assertEqual(req.full_url, API_URL)
        self.assertEqual(req.get_header('Authorization'), 'Bearer test-key')
        payload = json.loads(req.data)
        self.assertFalse(payload['store'])
        self.assertTrue(payload['text']['format']['strict'])
        self.assertNotIn('test-key', req.data.decode())
        self.assertNotIn('tools', payload)
        user_data = json.loads(payload['input'])
        self.assertEqual(user_data['source_text'], SOURCE)
        self.assertEqual(user_data['open_dates'][0], {'index': 0, 'date': '2027-01-03'})
        self.assertEqual(send.call_args.kwargs['timeout'], 120)

    def test_missing_key_does_not_make_network_request(self):
        with patch.dict(os.environ, {}, clear=True), patch('ai_availability.request.urlopen') as send:
            with self.assertRaisesRegex(AIAvailabilityError, 'API key'):
                convert_with_ai(SOURCE, DATES)
            send.assert_not_called()

    def test_environment_key_and_model_are_used_without_being_sent_as_input(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'env-test-key', 'OPENAI_MODEL': 'chosen-model'}), patch('ai_availability.request.urlopen', return_value=api_reply()) as send:
            convert_with_ai(SOURCE, DATES)
        req = send.call_args[0][0]
        self.assertEqual(req.get_header('Authorization'), 'Bearer env-test-key')
        self.assertEqual(json.loads(req.data)['model'], 'chosen-model')
        self.assertNotIn('env-test-key', req.data.decode())

    def test_refusals_incomplete_and_malformed_responses_are_not_imported(self):
        replies = [api_reply(status='incomplete'),
                   api_reply(content=[{'type': 'refusal', 'refusal': 'Cannot comply'}]),
                   api_reply(content=[{'type': 'output_text', 'text': '{broken'}]),
                   io.BytesIO(b'{"status":"completed","output":null}'),
                   io.BytesIO(b'not-json')]
        for reply in replies:
            with self.subTest(reply=reply), patch('ai_availability.request.urlopen', return_value=reply), self.assertRaises(AIAvailabilityError):
                convert_with_ai(SOURCE, DATES, api_key='test-key')

    def test_http_errors_do_not_echo_credentials_or_server_response(self):
        for status in (400, 401, 403, 404, 429, 500):
            failure = HTTPError(API_URL, status, 'secret-server-detail', {}, io.BytesIO(b'test-key'))
            with self.subTest(status=status), patch('ai_availability.request.urlopen', side_effect=failure):
                with self.assertRaises(AIAvailabilityError) as error:
                    convert_with_ai(SOURCE, DATES, api_key='test-key')
                self.assertNotIn('test-key', str(error.exception))
                self.assertNotIn('secret-server-detail', str(error.exception))

    def test_network_failures_have_a_useful_message(self):
        for failure in (URLError('offline'), TimeoutError('timed out')):
            with self.subTest(failure=failure), patch('ai_availability.request.urlopen', side_effect=failure):
                with self.assertRaisesRegex(AIAvailabilityError, 'internet connection'):
                    convert_with_ai(SOURCE, DATES, api_key='test-key')

    def test_empty_or_excessive_input_and_missing_open_dates_are_rejected(self):
        for source, dates in (('', DATES), ('x' * (MAX_INPUT_CHARS + 1), DATES), (SOURCE, [])):
            with self.subTest(source_length=len(source), dates=dates), self.assertRaises(AIAvailabilityError):
                build_payload(source, dates, 'gpt-5-mini')


if __name__ == '__main__':
    unittest.main()
