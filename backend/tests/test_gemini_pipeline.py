"""Integration coverage for spaCy entities and evidence-backed Gemini edges.

The provider and database are local doubles: no source data is sent to Gemini
and no Atlas records are created, changed, or removed by these tests.
"""
import unittest
from unittest.mock import Mock, patch

import mongomock
from fastapi.testclient import TestClient
from mongomock.gridfs import enable_gridfs_integration

from app.extraction import extract
from app.mongo_store import MongoStore


enable_gridfs_integration()

NARRATIVE = (
    'According to the FIR, phone 9000010001 spoke on the telephone with '
    'phone 9000010002.'
)


class GeminiPipelineTests(unittest.TestCase):
    def setUp(self):
        with patch('app.neo_store.NeoStore'):
            from app import main
        self.main = main
        self.store = MongoStore()
        self.store.db = mongomock.MongoClient().gemini_pipeline
        self.provider = Mock()
        self.provider.available = True
        self.provider.model = 'mock-model'
        self.provider.extract.side_effect = AssertionError('Gemini must never generate entities')
        self.provider.extract_relationships.side_effect = self.relationships
        for patcher in (
            patch.object(main, 'mongo', self.store),
            patch.object(main, 'neo', Mock()),
            patch('app.extraction.get_llm_provider', return_value=self.provider),
            patch.dict('os.environ', {
                'RELATIONSHIP_EXTRACTOR': 'gemini',
                'ENABLE_LLM_EXTRACTION': 'false',
            }),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        # Requests run without the lifespan, so Mongo startup never reaches Atlas.
        self.client = TestClient(main.app)

    @staticmethod
    def relationships(text, entities):
        phones = {e['label']: e['id'] for e in entities if e['type'] == 'Phone'}
        return {'relationships': [{
            'source': phones['9000010001'], 'target': phones['9000010002'],
            'type': 'CALLED', 'evidenceText': text, 'origin': 'reported',
        }]}

    def upload(self, content=NARRATIVE.encode(), filename='fir.txt', case='ONE'):
        return self.client.post('/api/upload', data={'case_id': case, 'source_type': 'FIR'},
                                files={'file': (filename, content)})

    def reanalyze(self, document_id, case='ONE'):
        return self.client.post(f'/api/cases/{case}/documents/{document_id}/reanalyze')

    def test_entities_are_unchanged_even_if_legacy_llm_flag_is_enabled(self):
        with patch.dict('os.environ', {'RELATIONSHIP_EXTRACTOR': 'regex'}):
            baseline = extract(NARRATIVE, scope='case:ONE')
        result_from_ids = self.relationships

        def response_with_entity_payload(text, entities):
            return {
                **result_from_ids(text, entities),
                'entities': [{'id': 'invented', 'label': 'Invented Person', 'type': 'Person'}],
            }

        self.provider.extract_relationships.side_effect = response_with_entity_payload
        with patch.dict('os.environ', {'ENABLE_LLM_EXTRACTION': 'true'}):
            result = extract(NARRATIVE, scope='case:ONE')
        self.assertEqual(result['entities'], baseline['entities'])
        self.assertEqual(result['mentions'], baseline['mentions'])
        self.assertEqual(len(result['relationships']), 1)
        self.assertNotIn('invented', {e['id'] for e in result['entities']})
        self.provider.extract.assert_not_called()
        self.provider.extract_relationships.assert_called_once()

    def test_upload_reanalysis_and_duplicates_reuse_file_report_and_entities(self):
        first = self.upload()
        self.assertEqual(first.status_code, 200, first.text)
        first = first.json()
        self.assertTrue(first['storage']['saved'])
        self.assertEqual(len(first['relationships']), 1)
        self.assertEqual(first['relationships'][0]['type'], 'CALLED')
        self.assertEqual(first['relationships'][0]['evidenceText'], NARRATIVE)
        self.assertEqual(first['relationships'][0]['origin'], 'reported')
        collections = ('documents', 'fs.files', 'fs.chunks', 'reports', 'entities', 'mentions', 'relationships')
        counts = {c: self.store.db[c].count_documents({}) for c in collections}
        saved_ids = {e['id'] for e in first['entities']}
        for _ in range(2):
            response = self.reanalyze(first['documentId'])
            self.assertEqual(response.status_code, 200, response.text)
            updated = response.json()
            self.assertEqual(updated['reportId'], first['reportId'])
            self.assertEqual(updated['relationshipCount'], 1)
            self.assertEqual(updated['relationships'][0]['type'], 'CALLED')
            self.assertEqual(counts, {c: self.store.db[c].count_documents({}) for c in collections})
            self.assertEqual(saved_ids, {e['id'] for e in self.store.entities_for_case('ONE')})
        self.provider.extract_relationships.reset_mock()
        repeated = self.upload(filename='renamed-fir.txt')
        self.assertEqual(repeated.status_code, 200, repeated.text)
        self.assertTrue(repeated.json()['duplicate'])
        self.assertEqual(repeated.json()['documentId'], first['documentId'])
        self.provider.extract_relationships.assert_not_called()
        workspace = self.client.get('/api/cases/ONE/workspace').json()
        self.assertEqual(len(workspace['network']['edges']), 1)
        edge = workspace['network']['edges'][0]
        self.assertEqual(edge['type'], 'CALLED')
        self.assertIn(edge['source'], saved_ids)
        self.assertIn(edge['target'], saved_ids)
        self.assertEqual(self.client.get('/api/cases/OTHER/workspace').json()['network']['edges'], [])

    def test_unknown_endpoints_and_fabricated_evidence_are_not_stored(self):
        valid_result = self.relationships

        def unsafe_response(text, entities):
            valid = valid_result(text, entities)['relationships'][0]
            return {'relationships': [
                valid,
                {**valid, 'source': 'person:not-extracted'},
                {**valid, 'type': 'MET', 'evidenceText': 'Both people met outside the police station.'},
            ]}

        self.provider.extract_relationships.side_effect = unsafe_response
        response = self.upload()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()['relationships']), 1)
        self.assertEqual(self.store.db.relationships.count_documents({}), 1)
        self.assertEqual(self.store.relationships_for_case('ONE')[0]['type'], 'CALLED')
        self.assertFalse(self.store.db.entities.find_one({'id': 'person:not-extracted'}))

    def test_provider_failure_does_not_retire_saved_relationships(self):
        first = self.upload()
        self.assertEqual(first.status_code, 200, first.text)
        first = first.json()
        before = self.store.relationships_for_case('ONE')
        report_before = self.store.db.reports.find_one({'_id': first['reportId']})
        document_before = self.store.db.documents.find_one({'documentId': first['documentId']})
        self.provider.extract_relationships.side_effect = None
        self.provider.extract_relationships.return_value = None
        response = self.reanalyze(first['documentId'])
        self.assertEqual(response.status_code, 502, response.text)
        self.assertEqual(before, self.store.relationships_for_case('ONE'))
        self.assertEqual(report_before, self.store.db.reports.find_one({'_id': first['reportId']}))
        self.assertEqual(document_before, self.store.db.documents.find_one({'documentId': first['documentId']}))

    def test_fresh_provider_failure_preserves_entities_and_duplicate_retries(self):
        self.provider.extract_relationships.side_effect = None
        self.provider.extract_relationships.return_value = None
        first = self.upload()
        self.assertEqual(first.status_code, 200, first.text)
        first = first.json()
        self.assertTrue(first['storage']['saved'])
        self.assertFalse(first['relationshipStatus']['complete'])
        self.assertGreater(len(first['entities']), 0)
        self.assertEqual(first['relationships'], [])
        self.assertEqual(self.store.db.reports.find_one({'_id': first['reportId']})['status'], 'relationships_pending')
        entity_ids = {e['id'] for e in first['entities']}
        self.provider.extract_relationships.side_effect = self.relationships
        retried = self.upload()
        self.assertEqual(retried.status_code, 200, retried.text)
        retried = retried.json()
        self.assertTrue(retried['duplicate'])
        self.assertTrue(retried['reanalyzed'])
        self.assertEqual(retried['documentId'], first['documentId'])
        self.assertEqual(retried['reportId'], first['reportId'])
        self.assertEqual({e['id'] for e in retried['entities']}, entity_ids)
        self.assertEqual(len(retried['relationships']), 1)
        self.assertTrue(retried['relationshipStatus']['complete'])
        self.assertEqual(self.store.db.reports.find_one({'_id': first['reportId']})['status'], 'complete')
        self.assertEqual(self.store.db.documents.count_documents({}), 1)
        self.assertEqual(self.store.db['fs.files'].count_documents({}), 1)
        self.assertEqual(self.store.db.reports.count_documents({}), 1)

    def test_structured_call_log_never_calls_gemini_and_retains_all_events(self):
        rows = ['CALL_ID,TIMESTAMP,CALLER_ID,RECEIVER_ID,DURATION_SEC,CALL_TYPE,CASE_ID']
        for index in range(30):
            source = f'900001{index % 12 + 1:04d}'
            target = f'900001{(index + 1) % 12 + 1:04d}'
            rows.append(f'CL-{index + 1},2026-09-18 09:00,{source},{target},120,OUTGOING,SOURCE-CASE')
        response = self.upload(('\n'.join(rows) + '\n').encode(), 'calls.csv')
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(len(result['entities']), 12)
        self.assertEqual(len(result['relationships']), 30)
        self.assertTrue(all(r['type'] == 'CALLED' for r in result['relationships']))
        self.assertTrue(all(r['caseId'] == 'ONE' for r in self.store.relationships_for_case('ONE')))
        self.assertTrue(all(r['event']['sourceCaseId'] == 'SOURCE-CASE' for r in result['relationships']))
        self.provider.extract_relationships.assert_not_called()
        refreshed = self.reanalyze(result['documentId'])
        self.assertEqual(refreshed.status_code, 200, refreshed.text)
        self.assertEqual(refreshed.json()['relationshipCount'], 30)
        self.provider.extract_relationships.assert_not_called()
        self.assertEqual(self.store.db.documents.count_documents({}), 1)
        self.assertEqual(self.store.db['fs.files'].count_documents({}), 1)
        self.assertEqual(self.store.db.relationships.count_documents({}), 30)


if __name__ == '__main__':
    unittest.main()
