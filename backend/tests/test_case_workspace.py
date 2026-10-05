import unittest
from unittest.mock import patch
import mongomock
from fastapi.testclient import TestClient
from app.mongo_store import MongoStore

class CaseWorkspaceTests(unittest.TestCase):
    def setUp(self):
        with patch('app.neo_store.NeoStore'):
            from app import main
        self.main = main
        self.store = MongoStore()
        self.store.db = mongomock.MongoClient().workspace
        self.patcher = patch.object(main, 'mongo', self.store)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.client = TestClient(main.app)

    def test_case_creation_and_legacy_discovery(self):
        a = self.client.post('/api/cases', json={'title':'Test investigation'}).json()
        b = self.client.post('/api/cases', json={'title':'Test investigation'}).json()
        self.assertNotEqual(a['id'], b['id'])
        self.store.db.documents.insert_one({'caseId':'LEGACY'})
        cases = self.client.get('/api/cases').json()['cases']
        self.assertEqual({c['id'] for c in cases}, {a['id'],b['id'],'LEGACY'})
        self.assertEqual(self.client.post('/api/cases', json={'title':'   '}).status_code,422)

    def test_workspace_isolation_and_evidence_supported_leads(self):
        for case in ['ONE','TWO']:
            for n in range(4):
                self.store.db.entities.insert_one({'id':f'{case}-{n}','label':f'Entity {n}','type':'Phone','caseId':case})
            for n in range(1,4):
                self.store.db.relationships.insert_one({'id':f'{case}-r{n}','source':f'{case}-0','target':f'{case}-{n}','caseId':case,'reportId':case,'type':'CALLED','evidenceText':'Source statement'})
        self.store.db.relationships.insert_one({'id':'dangling','caseId':'ONE','source':'ONE-0','target':'TWO-1'})
        result = self.client.get('/api/cases/ONE/workspace').json()
        self.assertEqual(result['overview']['nodes'],4)
        self.assertEqual(result['overview']['edges'],3)
        self.assertEqual(len(result['leads']),1)
        self.assertEqual(result['leads'][0]['sources'],['ONE'])
        self.assertEqual(len(result['leads'][0]['evidence']),3)
        self.assertTrue(all(e['id'].startswith('ONE') for e in result['network']['nodes']))
        self.assertEqual(self.client.get('/api/cases/EMPTY/workspace').json()['overview']['nodes'],0)

    def test_missing_storage_returns_visible_error(self):
        self.store.db=None
        self.assertEqual(self.client.get('/api/cases').status_code,503)
        self.assertEqual(self.client.get('/api/cases/ONE/workspace').status_code,503)

if __name__=='__main__':
    unittest.main()
