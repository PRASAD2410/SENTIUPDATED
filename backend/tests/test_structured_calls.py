import unittest
from unittest.mock import patch
import mongomock
from mongomock.gridfs import enable_gridfs_integration
from app.file_reader import parse_upload
from app.extraction import extract, entity
from app.mongo_store import MongoStore

enable_gridfs_integration()
CSV = b'CALL_ID,TIMESTAMP,CALLER_ID,RECEIVER_ID,DURATION_SEC,CALL_TYPE,CELL_TOWER,CASE_ID\nCL-1,2026-09-18 09:00,9000010001,9000010002,0,INCOMING,TWR-1,OP-104\nCL-2,2026-09-18 09:10,9000010001,9000010002,120,OUTGOING,TWR-1,OP-104\n'


class CallLogTests(unittest.TestCase):
    def result(self, content=CSV):
        parsed = parse_upload('calls.csv', content)
        with patch.dict('os.environ', {'ENABLE_LLM_EXTRACTION': 'false'}):
            return parsed, extract(parsed['text'], parsed, scope='case:SELECTED')

    def test_calls_not_header_entities_and_source_direction(self):
        parsed, result = self.result()
        self.assertEqual(len(result['entities']), 2)
        self.assertEqual(len(result['relationships']), 2)
        self.assertEqual(len(result['mentions']), 4)
        self.assertEqual({e['type'] for e in result['entities']}, {'Phone'})
        edge = result['relationships'][0]
        self.assertEqual(edge['source'], entity('9000010001', 'Phone')['id'])
        self.assertEqual(edge['target'], entity('9000010002', 'Phone')['id'])
        self.assertEqual(edge['event']['durationSeconds'], 0)
        self.assertEqual(edge['event']['sourceCaseId'], 'OP-104')
        self.assertEqual(edge['location']['row_number'], 2)
        for mention in result['mentions']:
            row = ' | '.join(parsed['units'][mention['unitIndex']]['cells'])
            self.assertEqual(row[mention['start']:mention['end']], mention['label'])

    def test_aliases_missing_phone_and_invalid_duration(self):
        _, result = self.result(b'From Number,To Number,Duration Seconds\n+91 9000010001,9000010002,bad\nmissing,9000010002,42\n')
        self.assertEqual(len(result['relationships']), 1)
        self.assertEqual(len(result['warnings']), 2)
        self.assertEqual(result['relationships'][0]['event']['durationRaw'], 'bad')
        self.assertEqual(len(result['entities']), 2)

    def test_headers_do_not_bleed_between_sheets(self):
        from app.structured_calls import extract_calls
        result = extract_calls([
            {'kind': 'row', 'sheet': 'Calls', 'cells': ['caller', 'receiver']},
            {'kind': 'row', 'sheet': 'Other', 'cells': ['9000010001', '9000010002']},
            {'kind': 'row', 'sheet': 'Calls', 'cells': ['9000010001', '9000010002']},
        ], entity)
        self.assertEqual(len(result['relationships']), 1)
        self.assertEqual(result['handled'], {0, 2})

    def test_transfer_columns_are_not_assumed_to_be_calls(self):
        _, result = self.result(b'FROM,TO,AMOUNT\n9000010001,9000010002,500\n')
        self.assertEqual(result['relationships'], [])

    def test_docx_tables_do_not_inherit_previous_headers(self):
        from app.structured_calls import extract_calls
        result = extract_calls([
            {'kind': 'row', 'block_number': 1, 'cells': ['caller', 'receiver']},
            {'kind': 'row', 'block_number': 1, 'cells': ['9000010001', '9000010002']},
            {'kind': 'row', 'block_number': 2, 'cells': ['9000010001', '9000010002']},
        ], entity)
        self.assertEqual(len(result['relationships']), 1)
        self.assertEqual(result['handled'], {0, 1})

    def test_reanalyze_old_upload_idempotent_preserves_other_case(self):
        store = MongoStore()
        store.db = mongomock.MongoClient().calls
        parsed, result = self.result()
        doc = store.save_document('SELECTED', 'calls.csv', CSV)
        report = {'id': 'R1', 'title': 'Calls', 'date': '2026-10-05',
                  'source': 'Uploaded file', 'documentId': doc['documentId']}
        junk = entity('CALL_ID', 'Organization')
        store.save_extraction('SELECTED', report, {'entities': [junk], 'mentions': [{'entityId': junk['id']}], 'relationships': []})
        store.save_extraction('OTHER', {**report, 'id': 'R2'}, {'entities': [junk], 'mentions': [], 'relationships': []})
        store.document_status('SELECTED', doc['documentId'], 'completed', reportId='R1')
        for _ in range(2):
            updated = store.reanalyze_relationships('SELECTED', doc['documentId'], parsed)
            self.assertEqual(updated['relationshipCount'], 2)
        self.assertEqual(store.db.documents.count_documents({}), 1)
        self.assertEqual(store.db['fs.files'].count_documents({}), 1)
        self.assertEqual(len(store.entities_for_case('SELECTED')), 2)
        self.assertEqual(len(store.entities_for_case('OTHER')), 1)
        self.assertEqual(len(store.extraction_for_report('SELECTED', 'R1')['mentions']), 4)
        self.assertEqual(len(store.relationships_for_case('SELECTED')), 2)
        self.assertEqual(store.db.relationships.count_documents({}), 2)
        self.assertTrue(store.save_document('SELECTED', 'renamed.csv', CSV)['duplicate'])
        self.assertTrue(all(r['caseId'] == 'SELECTED' for r in store.relationships_for_case('SELECTED')))


if __name__ == '__main__':
    unittest.main()
