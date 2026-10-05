import re
import unittest
from unittest.mock import patch

from app.gemini_relations import extract_gemini_relationships, VERSION, _chunks


class FakeProvider:
    model = 'test-gemini'
    last_error = None

    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def extract_relationships(self, text, entities):
        self.calls.append((text, entities))
        return self.answer(text, entities) if callable(self.answer) else self.answer


def fixture(texts):
    units = [{'kind': 'page', 'page_number': index + 1, 'text': text}
             for index, text in enumerate(texts)]
    entities = [{'id': name.casefold(), 'label': name, 'type': 'Person'}
                for name in ('Sam', 'Tara', 'Noor')]
    mentions = [{'entityId': entity['id'], 'label': match.group(), 'type': 'Person',
                 'unitIndex': index, 'start': match.start(), 'end': match.end()}
                for index, text in enumerate(texts) for entity in entities
                for match in re.finditer(entity['label'], text)]
    return units, entities, mentions


def proposal(quote='Sam called Tara.', **changes):
    return {'source': 'sam', 'target': 'tara', 'type': 'CALLED',
            'origin': 'asserted', 'evidenceText': quote, **changes}


class GeminiRelationshipValidationTests(unittest.TestCase):
    def test_cropped_quote_cannot_drop_adjacent_explicit_denial_or_dispute(self):
        for text in ('Sam called Tara. Police denied this allegation.',
                     'Police denied this claim. Sam called Tara.',
                     'Sam called Tara. This statement remains disputed.'):
            with self.subTest(text=text):
                result = extract_gemini_relationships(*fixture([text]), FakeProvider({'relationships': [proposal()]}))
                self.assertEqual(result['relationships'], [])
        edge, = extract_gemini_relationships(*fixture(['Noor did not call anyone. Sam called Tara.']),
                                            FakeProvider({'relationships': [proposal()]}))['relationships']
        self.assertEqual(edge['type'], 'CALLED')

    def test_adjacent_source_prefix_keeps_reported_origin(self):
        text = 'According to the witness statement. Sam called Tara.'
        edge, = extract_gemini_relationships(*fixture([text]), FakeProvider({'relationships': [proposal()]}))['relationships']
        self.assertEqual(edge['origin'], 'reported')
        self.assertIn('According to the witness statement.', edge['sentenceContext'])

    @patch.dict('os.environ', {'GEMINI_COMPACT_CONTEXT': 'true'})
    def test_compact_batch_reduces_requests_and_preserves_original_evidence_ids(self):
        text = ('Procedural note. ' * 300) + 'Sam   called\nTara.' + (' Routine detail. ' * 300)
        inputs = fixture([text] * 3)
        provider = FakeProvider({'relationships': [proposal()]})
        compact = extract_gemini_relationships(*inputs, provider)
        self.assertFalse(compact['failed'])
        self.assertEqual(compact['attempted'], 1)
        self.assertEqual(compact['input']['originalRequests'], 3)
        self.assertEqual(compact['input']['plannedRequests'], 1)
        self.assertLess(compact['input']['sentChars'], compact['input']['originalChars'] // 10)
        self.assertIn('[PASSAGE ', provider.calls[0][0])
        self.assertEqual(len(compact['relationships']), 3)
        self.assertEqual({edge['location']['page_number'] for edge in compact['relationships']}, {1, 2, 3})
        for edge in compact['relationships']:
            self.assertEqual(edge['evidenceText'], 'Sam   called\nTara.')
            self.assertEqual(text[edge['start']:edge['end']], edge['evidenceText'])
        with patch.dict('os.environ', {'GEMINI_COMPACT_CONTEXT': 'false'}):
            full = extract_gemini_relationships(*inputs, FakeProvider({'relationships': [proposal()]}))
        self.assertEqual({edge['id'] for edge in compact['relationships']}, {edge['id'] for edge in full['relationships']})

    @patch.dict('os.environ', {'GEMINI_COMPACT_CONTEXT': 'true', 'GEMINI_MAX_RELATIONSHIP_CHUNKS': '1'})
    def test_batched_pages_fit_one_request_cap_without_truncating_events(self):
        result = extract_gemini_relationships(*fixture(['Sam called Tara.'] * 3),
                                              FakeProvider({'relationships': [proposal()]}))
        self.assertFalse(result['failed'])
        self.assertEqual(result['attempted'], 1)
        self.assertEqual(len(result['relationships']), 3)

    @patch.dict('os.environ', {'GEMINI_COMPACT_CONTEXT': 'true'})
    def test_quotes_cannot_bridge_page_markers_or_skipped_passages(self):
        provider = FakeProvider({'relationships': [proposal(
            'Sam called Tara. Tara met Noor.', target='noor')]})
        result = extract_gemini_relationships(*fixture(['Sam called Tara.', 'Tara met Noor.']), provider)
        self.assertEqual(result['attempted'], 1)
        self.assertEqual(result['relationships'], [])
        self.assertIn('[PASSAGE ', provider.calls[0][0])
        gap = 'Sam called Tara. ' + ('Procedural note. ' * 80) + 'Sam called Tara.'
        result = extract_gemini_relationships(*fixture([gap]), FakeProvider({'relationships': [proposal(
            'Sam called Tara. Sam called Tara.')]}))
        self.assertEqual(result['relationships'], [])

    def test_only_preexisting_entities_and_verified_original_offsets(self):
        text = 'Statement:\nSam   called\nTara.'
        provider = FakeProvider({'relationships': [proposal()]})
        result = extract_gemini_relationships(*fixture([text]), provider)
        self.assertEqual((result['attempted'], result['succeeded'], result['failed']), (1, 1, False))
        edge, = result['relationships']
        self.assertEqual(edge['evidenceText'], 'Sam   called\nTara.')
        self.assertEqual(text[edge['start']:edge['end']], edge['evidenceText'])
        self.assertEqual(edge['location'], {'page_number': 1})
        self.assertEqual(edge['extractorVersion'], VERSION)
        self.assertEqual(edge['modelVersion'], provider.model)
        self.assertEqual(edge['method'], 'gemini-relationship')
        self.assertEqual(edge['reviewStatus'], 'pending')
        self.assertEqual({item['id'] for item in provider.calls[0][1]}, {'sam', 'tara'})

    def test_unknown_endpoints_types_self_edges_and_invented_quotes_rejected(self):
        values = [proposal(source='invented'), proposal(target='sam'),
                  proposal(type='GUILTY'), proposal(type='CALLED;DROP'),
                  proposal(evidenceText='Sam met Tara.'), proposal(origin=['asserted']),
                  'not a relationship', proposal(evidenceText='called Tara.')]
        provider = FakeProvider({'relationships': values})
        result = extract_gemini_relationships(*fixture(['Sam called Tara.']), provider)
        self.assertEqual(result['relationships'], [])
        self.assertFalse(result['failed'])
        self.assertIn('8 Gemini relationship proposals', ' '.join(result['warnings']))

    def test_quotes_cannot_borrow_endpoints_from_outside_the_evidence(self):
        text = 'Sam called Tara. Noor was nearby.'
        result = extract_gemini_relationships(*fixture([text]), FakeProvider({
            'relationships': [proposal(source='noor')]}))
        self.assertEqual(result['relationships'], [])

    def test_negated_uncertain_and_cropped_denial_rejected(self):
        for text, quote in [
                ('Sam did not call Tara.', 'Sam did not call Tara.'),
                ('Sam didn\u2019t call Tara.', 'Sam didn\u2019t call Tara.'),
                ('Police denied that Sam called Tara.', 'Sam called Tara.'),
                ('If Sam called Tara, investigate.', 'Sam called Tara'),
                ('Sam might have called Tara.', 'Sam might have called Tara.'),
                ('Sam called Tara, but this call is disputed.', 'Sam called Tara'),
        ]:
            with self.subTest(text=text):
                result = extract_gemini_relationships(*fixture([text]), FakeProvider({
                    'relationships': [proposal(quote)]}))
                self.assertEqual(result['relationships'], [])

    def test_attributed_and_alleged_statements_keep_reported_origin(self):
        for text, quote in [('Witness stated that Sam called Tara.', 'Sam called Tara.'),
                            ('Sam allegedly called Tara.', 'Sam allegedly called Tara.')]:
            with self.subTest(text=text):
                edge, = extract_gemini_relationships(*fixture([text]), FakeProvider({
                    'relationships': [proposal(quote)]}))['relationships']
                self.assertEqual(edge['origin'], 'reported')
        edge, = extract_gemini_relationships(*fixture(['Sam called Tara.']), FakeProvider({
            'relationships': [proposal(origin='reported')]}))['relationships']
        self.assertEqual(edge['origin'], 'reported')

    @patch.dict('os.environ', {'GEMINI_COMPACT_CONTEXT': 'false'})
    def test_overlap_deduplicates_same_event_but_not_distinct_occurrences(self):
        text = ('Note. ' * 1510) + 'Sam called Tara.' + (' Note. ' * 750)

        def respond(chunk, _):
            return {'relationships': [proposal()] if 'Sam called Tara.' in chunk else []}

        provider = FakeProvider(respond)
        result = extract_gemini_relationships(*fixture([text]), provider)
        self.assertGreaterEqual(result['attempted'], 2)
        self.assertEqual(len(result['relationships']), 1)
        self.assertTrue(all(len(chunk) <= 10000 for chunk, _ in provider.calls))
        repeat = 'Sam called Tara. Sam called Tara.'
        repeated = extract_gemini_relationships(*fixture([repeat]), FakeProvider({
            'relationships': [proposal()]}))
        self.assertEqual(len(repeated['relationships']), 2)
        self.assertEqual(len({edge['id'] for edge in repeated['relationships']}), 2)
        # Separate pages have independent, stable source evidence IDs.
        pages = extract_gemini_relationships(*fixture(['Sam called Tara.'] * 2), FakeProvider({
            'relationships': [proposal()]}))
        self.assertEqual(len({edge['id'] for edge in pages['relationships']}), 2)

    def test_table_rows_and_single_entity_units_do_not_call_provider(self):
        units, entities, mentions = fixture(['Sam called Tara.'])
        units[0] = {'kind': 'row', 'cells': ['Sam', 'Tara']}
        provider = FakeProvider({'relationships': [proposal()]})
        result = extract_gemini_relationships(units, entities, mentions, provider)
        self.assertEqual(provider.calls, [])
        self.assertEqual(result['relationships'], [])
        result = extract_gemini_relationships(*fixture(['Sam was present.']), provider)
        self.assertEqual(result['attempted'], 0)

    @patch.dict('os.environ', {'GEMINI_COMPACT_CONTEXT': 'false'})
    def test_variable_quotes_for_same_overlapping_occurrence_are_deduplicated(self):
        text = ('Note. ' * 1510) + 'Sam called Tara.' + (' Note. ' * 750)
        quotes = iter(['Note. Sam called Tara.', 'Sam called Tara.'])

        def respond(chunk, _):
            return {'relationships': [proposal(next(quotes))]}

        result = extract_gemini_relationships(*fixture([text]), FakeProvider(respond))
        edge, = result['relationships']
        self.assertEqual(edge['evidenceText'], 'Sam called Tara.')
        baseline, = extract_gemini_relationships(*fixture([text]), FakeProvider({
            'relationships': [proposal()]}))['relationships']
        self.assertEqual(edge['id'], baseline['id'])

    def test_missing_key_preflight_sends_no_requests_and_does_not_affect_rows(self):
        provider = FakeProvider({'relationships': [proposal()]})
        provider.available = False
        result = extract_gemini_relationships(*fixture(['Sam called Tara.']), provider)
        self.assertTrue(result['failed'])
        self.assertEqual(result['attempted'], 0)
        self.assertEqual(provider.calls, [])
        self.assertIn('API key is missing', ' '.join(result['warnings']))
        units, entities, mentions = fixture(['Sam called Tara.'])
        units[0] = {'kind': 'row', 'cells': ['Sam', 'Tara']}
        result = extract_gemini_relationships(units, entities, mentions, provider)
        self.assertFalse(result['failed'])

    def test_first_failure_stops_requests_and_returns_safe_adapter_diagnostic(self):
        provider = FakeProvider(None)
        provider.last_error = 'Gemini quota exceeded. Retry later.'
        result = extract_gemini_relationships(*fixture(['Sam called Tara.'] * 3), provider)
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(result['attempted'], 1)
        self.assertTrue(result['failed'])
        self.assertIn('Gemini quota exceeded', ' '.join(result['warnings']))

    def test_stale_existing_id_anchor_blocks_analysis_before_provider_request(self):
        units, entities, mentions = fixture(['Noor called Tara.'])
        stale = next(mention for mention in mentions if mention['entityId'] == 'noor')
        stale.update(entityId='sam', label='Sam')
        provider = FakeProvider({'relationships': [proposal('Noor called Tara.')]})
        result = extract_gemini_relationships(units, entities, mentions, provider)
        self.assertTrue(result['failed'])
        self.assertEqual(result['relationships'], [])
        self.assertEqual(provider.calls, [])
        self.assertEqual(result['attempted'], 0)
        self.assertIn('Re-extract the original document', ' '.join(result['warnings']))

    def test_invalid_unit_index_or_out_of_bounds_spans_are_incomplete(self):
        for changes in ({'unitIndex': 99}, {'unitIndex': None}, {'start': -1},
                        {'end': 1000}, {'label': 'a stale alias'}, {'label': None}):
            with self.subTest(changes=changes):
                units, entities, mentions = fixture(['Sam called Tara.'])
                mentions[0].update(changes)
                provider = FakeProvider({'relationships': [proposal()]})
                result = extract_gemini_relationships(units, entities, mentions, provider)
                self.assertTrue(result['failed'])
                self.assertEqual(provider.calls, [])

    def test_anchor_validation_accepts_pdf_whitespace_and_narrative_identifiers(self):
        text = 'Sam\n\tJones called phone +91-9000010001.'
        entities = [{'id': 'sam', 'label': 'Sam Jones', 'type': 'Person'},
                    {'id': 'phone', 'label': '9000010001', 'type': 'Phone'}]
        mentions = [{'entityId': 'sam', 'label': 'Sam Jones', 'unitIndex': 0,
                     'start': 0, 'end': text.index(' called')},
                    {'entityId': 'phone', 'label': '+91-9000010001', 'unitIndex': 0,
                     'start': text.index('+91'), 'end': text.index('+91') + len('+91-9000010001')}]
        provider = FakeProvider({'relationships': [proposal(
            'Sam Jones called phone +91-9000010001.', target='phone')]})
        result = extract_gemini_relationships([{'kind': 'page', 'text': text}], entities, mentions, provider)
        self.assertFalse(result['failed'])
        edge, = result['relationships']
        self.assertEqual(edge['evidenceText'], text)
        self.assertEqual({item['id'] for item in provider.calls[0][1]}, {'sam', 'phone'})

    def test_failed_and_malformed_providers_mark_analysis_incomplete(self):
        for answer in (None, {}, {'relationships': None}):
            result = extract_gemini_relationships(*fixture(['Sam called Tara.']), FakeProvider(answer))
            self.assertTrue(result['failed'])
            self.assertEqual(result['succeeded'], 0)
            self.assertIn('incomplete', ' '.join(result['warnings']))

        def raise_private_error(*_):
            raise RuntimeError('a-private-key-and-document-text')

        result = extract_gemini_relationships(*fixture(['Sam called Tara.']), FakeProvider(raise_private_error))
        self.assertTrue(result['failed'])
        self.assertNotIn('private', str(result))

    @patch.dict('os.environ', {'GEMINI_COMPACT_CONTEXT': 'false'})
    def test_chunk_cap_reports_partial_analysis_without_silent_truncation(self):
        with patch.dict('os.environ', {'GEMINI_MAX_RELATIONSHIP_CHUNKS': '1'}):
            result = extract_gemini_relationships(*fixture(['Sam called Tara.'] * 2), FakeProvider({
                'relationships': [proposal()]}))
        self.assertEqual(result['attempted'], 1)
        self.assertEqual(len(result['relationships']), 1)
        self.assertTrue(result['failed'])
        self.assertIn('remaining source text', ' '.join(result['warnings']))

    def test_long_sentence_chunk_warning_and_invalid_cap_default(self):
        text = 'Sam called Tara' + (' more details' * 1000)
        with patch.dict('os.environ', {'GEMINI_MAX_RELATIONSHIP_CHUNKS': 'invalid'}):
            result = extract_gemini_relationships(*fixture([text]), FakeProvider({'relationships': []}))
        warnings = ' '.join(result['warnings'])
        self.assertIn('Invalid GEMINI_MAX_RELATIONSHIP_CHUNKS', warnings)
        self.assertIn('longer than the chunk window', warnings)
        chunks = list(_chunks(text))
        self.assertTrue(all(end - start <= 10000 for start, end, _ in chunks))
        self.assertEqual(chunks[-1][1], len(text))


if __name__ == '__main__':
    unittest.main()
