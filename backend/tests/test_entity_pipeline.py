import os
import unittest
from unittest.mock import patch, Mock
import mongomock
from mongomock.gridfs import enable_gridfs_integration
enable_gridfs_integration()
from pymongo.errors import AutoReconnect
from app.extraction import extract
from app.nlp import nlp_status
from app.mongo_store import MongoStore

class ExtractionTests(unittest.TestCase):
    def setUp(self):
        self.provider = patch('app.extraction.get_llm_provider')
        self.mock_provider = self.provider.start()
        self.mock_provider.return_value.extract.return_value = None
        self.addCleanup(self.provider.stop)

    def test_trained_model_and_source_offsets(self):
        self.assertTrue(nlp_status()['nerReady'])
        text = 'Barack Obama visited London. Phone: 9876543210. Vehicle DL-8-CAB-1234. Account 001234567890.'
        result = extract(text, {'kind':'text','units':[{'kind':'page','page_number':2,'text':text}]}, scope='report-one')
        self.assertTrue(any(e['label']=='Barack Obama' and e['type']=='Person' for e in result['entities']))
        self.assertTrue(any(e['normalizedValue']=='DL8CAB1234' for e in result['entities']))
        self.assertTrue(any(e['normalizedValue']=='001234567890' and e['type']=='Account' for e in result['entities']))
        for mention in result['mentions']:
            self.assertEqual(mention['label'], text[mention['start']:mention['end']])
            self.assertEqual(mention['location']['page_number'], 2)
        self.assertEqual(result['relationships'], [])

    def test_phone_normalization_without_account_false_positive(self):
        result = extract('Phone +91 9876543210 and phone 9876543210.')
        phones = [e for e in result['entities'] if e['type']=='Phone']
        self.assertEqual(len(phones),1)
        self.assertFalse(any(e['type']=='Account' for e in result['entities']))

    def test_same_names_not_merged_across_documents(self):
        a = extract('Barack Obama visited London.',scope='report-one')
        b = extract('Barack Obama visited London.',scope='report-two')
        person_a = next(e for e in a['entities'] if e['type']=='Person')
        person_b = next(e for e in b['entities'] if e['type']=='Person')
        self.assertNotEqual(person_a['id'],person_b['id'])

    def test_provider_invented_entity_rejected(self):
        self.mock_provider.return_value.extract.return_value = {'entities':[{'label':'Invented Person','type':'Person'}], 'relationships':[]}
        self.assertFalse(any(e['label']=='Invented Person' for e in extract('Phone 9876543210.')['entities']))

class MongoTests(unittest.TestCase):
    def setUp(self):
        self.store = MongoStore()
        self.store.db = mongomock.MongoClient().test
        self.report = {'id':'REPORT-1','title':'Test','date':'2026-10-05','source':'Test source'}
        self.result = {'entities':[{'id':'phone:one','label':'9876543210','type':'Phone'}],
                       'mentions':[{'entityId':'phone:one','location':{'page_number':1}}]}

    def test_health_checks_current_connection_not_database_handle(self):
        from pymongo.errors import ServerSelectionTimeoutError
        self.store.uri = 'configured'
        self.store.client = Mock()
        self.store.client.admin.command.side_effect = ServerSelectionTimeoutError('timeout')
        self.assertFalse(self.store.status()['connected'])
        self.assertIn('connection failed', self.store.status()['warning'])
        self.store.client.admin.command.side_effect = None
        self.assertTrue(self.store.status()['connected'])
        self.assertIsNone(self.store.status()['warning'])

    def test_retries_deduplicate_but_retain_source_mentions(self):
        for _ in range(2):
            self.assertTrue(self.store.save_extraction('CASE-1', self.report, self.result)['saved'])
        self.assertEqual(self.store.db.entities.count_documents({}),1)
        self.assertEqual(self.store.db.mentions.count_documents({}),1)
        self.store.save_extraction('CASE-1',{**self.report,'id':'REPORT-2'},self.result)
        self.assertEqual(self.store.db.entities.count_documents({}),1)
        self.assertEqual(self.store.db.mentions.count_documents({}),2)
        self.assertEqual(self.store.db.reports.find_one({'_id':'REPORT-1'})['status'],'complete')
        self.assertEqual(set(self.store.entities_for_case('CASE-1')[0]['reportIds']), {'REPORT-1','REPORT-2'})

    def test_case_isolation(self):
        self.store.save_extraction('CASE-1',self.report,self.result)
        self.store.save_extraction('CASE-2',{**self.report,'id':'REPORT-2'},self.result)
        self.assertEqual(len(self.store.entities_for_case('CASE-1')),1)
        self.assertEqual(self.store.entities_for_case('CASE-1')[0]['caseId'],'CASE-1')
        self.assertEqual(self.store.db.entities.count_documents({}),2)

    def test_write_failure_and_missing_connection_visible(self):
        self.store.db = None
        self.assertFalse(self.store.save_extraction('CASE-1',self.report,self.result)['saved'])
        self.store.db = Mock()
        self.store.db.reports.update_one.side_effect = AutoReconnect('test')
        result = self.store.save_extraction('CASE-1',self.report,self.result)
        self.assertFalse(result['saved'])
        self.assertIn('incomplete',result['warning'])

class ApiTests(unittest.TestCase):
    def test_upload_persist_and_retrieve(self):
        from fastapi.testclient import TestClient
        # No real provider calls or Neo4j startup connections in tests.
        with patch('app.neo_store.NeoStore'):
            from app import main
        store = MongoStore()
        store.db = mongomock.MongoClient().test
        with patch.object(main,'mongo',store), patch('app.extraction.get_llm_provider') as provider:
            provider.return_value.extract.return_value = None
            client = TestClient(main.app)
            response = client.post('/api/upload',data={'case_id':'CASE-TEST','source_type':'FIR','investigation_type':'Organized Crime'},files={'file':('report.txt',b'Barack Obama visited London. Phone 9876543210.','text/plain')})
            self.assertEqual(response.status_code,200)
            self.assertTrue(response.json()['storage']['saved'])
            document_id=response.json()['documentId']
            self.assertTrue(response.json()['fileStorage']['saved'])
            documents=client.get('/api/cases/CASE-TEST/documents').json()['documents']
            self.assertEqual(documents[0]['documentId'],document_id)
            self.assertEqual(documents[0]['processingStatus'],'completed')
            self.assertEqual(documents[0]['sourceType'],'FIR')
            self.assertEqual(documents[0]['investigationType'],'Organized Crime')
            downloaded=client.get(f'/api/cases/CASE-TEST/documents/{document_id}/download')
            self.assertEqual(downloaded.content,b'Barack Obama visited London. Phone 9876543210.')
            self.assertEqual(client.get(f'/api/cases/OTHER/documents/{document_id}/download').status_code,404)
            self.assertEqual(store.db.mentions.find_one({})['documentId'],document_id)
            entities = client.get('/api/cases/CASE-TEST/entities').json()['entities']
            self.assertTrue(any(e['type']=='Person' for e in entities))
            self.assertEqual(client.get('/api/cases/OTHER/entities').json()['entities'],[])
            self.assertEqual(client.post('/api/upload',data={'case_id':'invalid id'},files={'file':('a.txt',b'Phone 9876543210.')}).status_code,422)

    def test_failed_parsing_keeps_original_and_missing_db_rejects_upload(self):
        from fastapi.testclient import TestClient
        with patch('app.neo_store.NeoStore'):
            from app import main
        store=MongoStore()
        store.db=mongomock.MongoClient().test
        with patch.object(main,'mongo',store):
            client=TestClient(main.app)
            response=client.post('/api/upload',data={'case_id':'CASE-FAILED'},files={'file':('broken.pdf',b'not a PDF')})
            self.assertEqual(response.status_code,422)
            document_id=response.json()['detail']['documentId']
            self.assertEqual(store.documents_for_case('CASE-FAILED')[0]['processingStatus'],'failed')
            self.assertEqual(store.original_document('CASE-FAILED',document_id)[1],b'not a PDF')
            store.db=None
            response=client.post('/api/upload',files={'file':('a.txt',b'Phone 9876543210.')})
            self.assertEqual(response.status_code,503)

if __name__ == '__main__':
    unittest.main()

