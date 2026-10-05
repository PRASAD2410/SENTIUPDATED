import re
import unittest

from app.relationship_context import MARKER_CHARS, plan_context


def fixture(texts):
    units = [{'kind': 'page', 'page_number': index + 1, 'text': text}
             for index, text in enumerate(texts)]
    anchors = {index: [{'entityId': match.group().casefold(), 'label': match.group(),
                        'start': match.start(), 'end': match.end()}
                       for match in re.finditer(r'\b(?:Sam|Tara|Noor)\b', text)]
               for index, text in enumerate(texts)}
    return units, anchors


class RelationshipContextTests(unittest.TestCase):
    def assert_source_passages(self, result, units):
        for request in result['requests']:
            ids = set()
            for segment in request:
                self.assertEqual(segment['text'], units[segment['unitIndex']]['text'][
                    segment['start']:segment['end']])
                for anchor in segment['anchors']:
                    self.assertLessEqual(segment['start'], anchor['start'])
                    self.assertLessEqual(anchor['end'], segment['end'])
                    ids.add(anchor['entityId'])
            self.assertGreaterEqual(len(ids), 2)
        self.assertLessEqual(result['metrics']['plannedRequests'], result['metrics']['originalRequests'])

    def test_long_irrelevant_context_is_removed_without_rewriting_source(self):
        text = ('Procedural note. ' * 400) + 'Witness said this happened. Sam called Tara at 09:15.' + (' Routine detail. ' * 400)
        units, anchors = fixture([text])
        result = plan_context(units, anchors)
        self.assertEqual(result['metrics']['mode'], 'entity-context')
        self.assertLess(result['metrics']['sentChars'], result['metrics']['originalChars'] // 5)
        self.assertIn('Witness said this happened.', result['requests'][0][0]['text'])
        self.assertIn('09:15', result['requests'][0][0]['text'])
        self.assertTrue(result['warnings'])
        self.assert_source_passages(result, units)

    def test_short_pages_batch_into_one_request_with_separate_passages(self):
        units, anchors = fixture(['Sam called Tara.', 'Tara met Noor.', 'Sam owns vehicle MH12AB1234 with Noor.'])
        result = plan_context(units, anchors)
        self.assertEqual(result['metrics']['originalRequests'], 3)
        self.assertEqual(result['metrics']['plannedRequests'], 1)
        self.assertEqual(result['metrics']['passageCount'], 3)
        self.assertEqual([item['unitIndex'] for item in result['requests'][0]], [0, 1, 2])
        self.assert_source_passages(result, units)

    def test_attribution_denial_numeric_values_and_whitespace_remain_exact(self):
        text = ('Administrative note. ' * 10) + 'Police denied this allegation.\nSam  called Tara using +91-9000010001. The claim remains disputed.\n' + ('Further note. ' * 10)
        units, anchors = fixture([text])
        result = plan_context(units, anchors)
        passage = result['requests'][0][0]['text']
        self.assertIn('Police denied this allegation.', passage)
        self.assertIn('Sam  called Tara using +91-9000010001.', passage)
        self.assertIn('The claim remains disputed.', passage)
        self.assert_source_passages(result, units)

    def test_single_id_passages_are_retained_inside_batch(self):
        text = 'Sam made a statement. ' + ('Irrelevant detail. ' * 40) + 'Tara also made a statement.'
        units, anchors = fixture([text])
        result = plan_context(units, anchors)
        self.assertEqual(result['metrics']['passageCount'], 2)
        self.assertEqual(result['metrics']['plannedRequests'], 1)
        self.assertEqual([{anchor['entityId'] for anchor in passage['anchors']}
                          for passage in result['requests'][0]], [{'sam'}, {'tara'}])
        self.assert_source_passages(result, units)

    def test_repeated_disjoint_statements_remain_distinct_original_slices(self):
        text = 'Sam called Tara. ' + ('Procedural note. ' * 40) + 'Sam called Tara.'
        units, anchors = fixture([text])
        result = plan_context(units, anchors)
        segments = result['requests'][0]
        self.assertEqual(len(segments), 2)
        self.assertLess(segments[0]['end'], segments[1]['start'])
        self.assertEqual(sum(segment['text'].count('Sam called Tara.') for segment in segments), 2)
        self.assert_source_passages(result, units)

    def test_compaction_cannot_increase_requests_for_dense_or_oversized_text(self):
        for text in ('Sam called Tara. ' * 80, 'Sam called Tara' + (' lengthy information' * 50)):
            units, anchors = fixture([text])
            result = plan_context(units, anchors, chunk_size=200, overlap=20)
            self.assert_source_passages(result, units)
            self.assertLessEqual(result['metrics']['sentChars'], result['metrics']['originalChars'])
            if result['metrics']['mode'] == 'entity-context':
                for request in result['requests']:
                    self.assertLessEqual(sum(len(item['text']) + min(MARKER_CHARS, 20)
                                             for item in request), 200)

    def test_unbatchable_single_id_context_is_not_silently_discarded(self):
        text = 'Sam called Tara. ' + ('Procedural note. ' * 30) + 'Sam ' + ('lengthy ' * 35) + '.'
        units, anchors = fixture([text, 'Sam called Tara.', 'Tara met Noor.'])
        result = plan_context(units, anchors, chunk_size=200, overlap=20)
        self.assertEqual(result['metrics']['mode'], 'full-context')
        self.assertIn('omit entity context', ' '.join(result['warnings']))
        self.assert_source_passages(result, units)

    def test_full_context_retains_original_eligible_chunks_one_per_request(self):
        units, anchors = fixture(['Sam called Tara. ' * 80, 'Noor was present.'])
        result = plan_context(units, anchors, chunk_size=200, overlap=20, compact=False)
        self.assertEqual(result['metrics']['mode'], 'full-context')
        self.assertEqual(result['metrics']['sentChars'], result['metrics']['originalChars'])
        self.assertEqual(result['metrics']['plannedRequests'], result['metrics']['originalRequests'])
        self.assertTrue(all(len(request) == 1 and len(request[0]['text']) <= 200
                            for request in result['requests']))
        self.assert_source_passages(result, units)

    def test_rows_and_ineligible_units_do_not_create_artificial_savings(self):
        units, anchors = fixture(['Sam called Tara.', 'Sam was present.'])
        units[0]['kind'] = 'row'
        result = plan_context(units, anchors)
        self.assertEqual(result['requests'], [])
        self.assertEqual(result['metrics']['originalChars'], 0)
        self.assertEqual(result['metrics']['sentChars'], 0)
        self.assertEqual(result['metrics']['originalRequests'], 0)

    def test_invalid_sizes_fail_and_large_overlap_is_bounded(self):
        units, anchors = fixture(['Sam called Tara. ' * 10])
        for kwargs in ({'chunk_size': 0}, {'chunk_size': True}, {'overlap': -1}):
            with self.assertRaises(ValueError):
                plan_context(units, anchors, **kwargs)
        result = plan_context(units, anchors, chunk_size=40, overlap=1000)
        self.assert_source_passages(result, units)


if __name__ == '__main__':
    unittest.main()
