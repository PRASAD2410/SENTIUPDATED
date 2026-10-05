import unittest
from unittest.mock import patch
import mongomock
from mongomock.gridfs import enable_gridfs_integration
from fastapi.testclient import TestClient
from app.mongo_store import MongoStore

enable_gridfs_integration()


class UploadDeduplicationTests(unittest.TestCase):
    def setUp(self):
        with patch('app.neo_store.NeoStore'):
            from app import main
        self.main=main
        self.store=MongoStore(); self.store.db=mongomock.MongoClient().dedup
        self.patch=patch.object(main,'mongo',self.store)
        self.patch.start(); self.addCleanup(self.patch.stop)
        self.client=TestClient(main.app)

    def upload(self,content,name='record.txt',case='ONE'):
        return self.client.post('/api/upload',data={'case_id':case},files={'file':(name,content)})

    def test_same_contents_renamed_reuses_every_record(self):
        body=b'Barack Obama called Joe Biden. Phone 9876543210.'
        first=self.upload(body).json()
        collections=['documents','fs.files','fs.chunks','entities','mentions','reports','relationships']
        counts={c:self.store.db[c].count_documents({}) for c in collections}
        with patch.object(self.main,'process',side_effect=AssertionError('Duplicate must not extract again')):
            second=self.upload(body,'renamed.txt').json()
        self.assertTrue(second['duplicate'])
        self.assertTrue(second['fileStorage']['reused'])
        self.assertEqual(first['documentId'],second['documentId'])
        self.assertEqual(first['reportId'],second['reportId'])
        self.assertEqual(counts,{c:self.store.db[c].count_documents({}) for c in collections})

    def test_same_filename_changed_contents_and_case_isolation(self):
        a=self.upload(b'Barack Obama contacted Joe Biden.').json()
        b=self.upload(b'Barack Obama contacted Joe Biden. Phone 9876543210.').json()
        c=self.upload(b'Barack Obama contacted Joe Biden.',case='TWO').json()
        self.assertNotEqual(a['documentId'],b['documentId'])
        self.assertNotEqual(a['documentId'],c['documentId'])
        self.assertEqual(self.store.db.documents.count_documents({}),3)
        one_people=list(self.store.db.entities.find({'caseId':'ONE','type':'Person'}))
        self.assertEqual(len(one_people),2)
        self.assertTrue(all(len(p['reportIds'])==2 for p in one_people))
        self.assertEqual(one_people[0]['identityStatus'],'unverified-name-group')

    def test_failed_or_pending_upload_does_not_create_second_file(self):
        first=self.upload(b'invalid PDF content','broken.pdf')
        self.assertEqual(first.status_code,422)
        second=self.upload(b'invalid PDF content','broken.pdf')
        self.assertEqual(second.status_code,409)
        self.assertEqual(self.store.db.documents.count_documents({}),1)
        self.assertEqual(self.store.db['fs.files'].count_documents({}),1)

    def test_historical_duplicate_name_nodes_display_as_one_group(self):
        for n in [1,2]:
            self.store.db.entities.insert_one({'id':f'p{n}','caseId':'ONE','type':'Person',
                'label':'Example Name','normalizedValue':'example name','reportIds':[f'r{n}']})
        self.store.db.entities.insert_one({'id':'target','caseId':'ONE','type':'Person',
            'label':'Other Name','normalizedValue':'other name','reportIds':['r1']})
        for n in [1,2]:
            self.store.db.relationships.insert_one({'id':f'e{n}','caseId':'ONE','source':f'p{n}',
                'target':'target','type':'CONTACTED','reportId':f'r{n}'})
        view=self.client.get('/api/cases/ONE/workspace').json()
        self.assertEqual(len(view['network']['nodes']),2)
        self.assertEqual(len(view['network']['edges']),2)
        self.assertEqual({e['source'] for e in view['network']['edges']},{'p1'})
        self.assertEqual(self.store.db.entities.count_documents({}),3)

    def test_old_duplicate_automatically_updates_call_mapping(self):
        content=b'CALLER_ID,RECEIVER_ID,DURATION_SEC\n9000010001,9000010002,120\n'
        first=self.upload(content,'calls.csv').json()
        self.store.db.documents.update_one({'documentId':first['documentId']}, {'$unset':{'extractionVersion':''}})
        self.store.db.relationships.delete_many({'reportId':first['reportId']})
        second=self.upload(content,'calls.csv').json()
        self.assertTrue(second['reanalyzed'])
        self.assertEqual(second['documentId'],first['documentId'])
        self.assertEqual(second['reportId'],first['reportId'])
        self.assertEqual(len(second['relationships']),1)
        self.assertEqual(self.store.db.documents.count_documents({}),1)
        self.assertEqual(self.store.db['fs.files'].count_documents({}),1)
        third=self.upload(content,'calls.csv').json()
        self.assertFalse(third['reanalyzed'])
        self.assertEqual(len(third['relationships']),1)

    def test_multiple_sources_share_case_and_produce_visible_graph_edges(self):
        calls=b'CALLER_ID,RECEIVER_ID,DURATION_SEC\n9000010001,9000010002,120\n'
        for name, content in [('calls.csv',calls),('calls2.tsv',b'Caller\tReceiver\n9000010002\t9000010003\n'),
                              ('note.txt',b'At 09:00, phone 9000010001 called phone 9000010003.')]:
            response=self.upload(content,name)
            self.assertEqual(response.status_code,200,response.text)
            self.assertTrue(response.json()['storage']['saved'])
            self.assertEqual(len(response.json()['relationships']),1)
        workspace=self.client.get('/api/cases/ONE/workspace').json()
        self.assertEqual(len(workspace['documents']),3)
        self.assertEqual(len(workspace['network']['edges']),3)
        self.assertTrue(all(d['relationshipCount']==1 for d in workspace['documents']))
        self.assertEqual(self.client.get('/api/cases/TWO/workspace').json()['network']['edges'],[])

if __name__=='__main__':
    unittest.main()
