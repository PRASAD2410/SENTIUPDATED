import unittest
from unittest.mock import patch
import mongomock
from app.extraction import extract
from app.mongo_store import MongoStore

class RelationshipTests(unittest.TestCase):
    def test_upload_api_saves_and_returns_relationships(self):
        from fastapi.testclient import TestClient
        from mongomock.gridfs import enable_gridfs_integration
        enable_gridfs_integration()
        with patch('app.neo_store.NeoStore'):
            from app import main
        store=MongoStore();store.db=mongomock.MongoClient().test
        with patch.object(main,'mongo',store), patch.dict('os.environ',{'ENABLE_LLM_EXTRACTION':'false'}):
            client=TestClient(main.app)
            response=client.post('/api/upload',data={'case_id':'RULE-TEST'},files={'file':('calls.txt',b'Phone 9876543210 called phone 9123456789.')})
            self.assertEqual(response.status_code,200)
            payload=response.json()
            self.assertEqual(payload['storage']['relationships'],1)
            fetched=client.get('/api/cases/RULE-TEST/relationships').json()['relationships']
            self.assertEqual(fetched[0]['documentId'],payload['documentId'])
            self.assertEqual(fetched[0]['type'],'CALLED')
            self.assertEqual(client.get('/api/cases/OTHER/relationships').json()['relationships'],[])

    def test_calls_transfers_and_source_evidence(self):
        text='Phone 9876543210 called phone 9123456789. Account 001234567890 transferred INR 5,000.00 to account 009876543210.'
        result=extract(text,{'kind':'text','units':[{'kind':'page','page_number':3,'text':text}]},scope='TEST')
        self.assertEqual({r['type'] for r in result['relationships']},{'CALLED','TRANSFERRED_TO'})
        for r in result['relationships']:
            self.assertEqual(r['evidenceText'],text[r['start']:r['end']])
            self.assertEqual(r['location']['page_number'],3)
            self.assertEqual(r['origin'],'asserted')
        transfer=next(r for r in result['relationships'] if r['type']=='TRANSFERRED_TO')
        self.assertEqual(transfer['amount'],'5000.00')

    def test_person_use_and_registration(self):
        result=extract('Barack Obama used vehicle DL8CAB1234. Vehicle DL8CAB1234 was registered to Barack Obama.',scope='TEST')
        self.assertEqual({r['type'] for r in result['relationships']},{'USES','REGISTERED_TO'})
        use=next(r for r in result['relationships'] if r['type']=='USES')
        registration=next(r for r in result['relationships'] if r['type']=='REGISTERED_TO')
        self.assertEqual(use['source'],registration['target'])
        self.assertEqual(use['target'],registration['source'])

    def test_negated_uncertain_and_coordinated_sentences_rejected(self):
        examples=[
            'Phone 9876543210 did not call phone 9123456789.',
            'Phone 9876543210 never called phone 9123456789.',
            'If phone 9876543210 called phone 9123456789, investigate.',
            'Barack Obama said Joe Biden used vehicle DL8CAB1234.',
            'Barack Obama and Joe Biden used vehicle DL8CAB1234.',
            'Barack Obama may have used vehicle DL8CAB1234.',
            'Barack Obama visited London. Vehicle DL8CAB1234 was nearby.',
        ]
        for text in examples:
            with self.subTest(text=text):
                self.assertEqual(extract(text,scope='TEST')['relationships'],[])

    def test_no_cross_page_or_table_relationships(self):
        parsed={'kind':'text','units':[{'kind':'page','page_number':1,'text':'Phone 9876543210 called'}, {'kind':'page','page_number':2,'text':'phone 9123456789.'}]}
        self.assertEqual(extract('',parsed)['relationships'],[])
        parsed={'kind':'table','units':[{'kind':'row','row_number':1,'cells':['Phone 9876543210 called phone 9123456789.']}]}
        self.assertEqual(extract('',parsed)['relationships'],[])

    def test_repeated_calls_keep_distinct_evidence(self):
        result=extract('Phone 9876543210 called phone 9123456789. Phone 9876543210 called phone 9123456789.')
        self.assertEqual(len(result['relationships']),2)
        self.assertEqual(len({r['id'] for r in result['relationships']}),2)

    def test_rules_do_not_call_gemini(self):
        with patch.dict('os.environ',{'ENABLE_LLM_EXTRACTION':'false'}), patch('app.extraction.get_llm_provider') as provider:
            self.assertEqual(len(extract('Phone 9876543210 called phone 9123456789.')['relationships']),1)
            provider.assert_not_called()

    def test_mongo_relationships_are_case_scoped_and_retry_safe(self):
        store=MongoStore();store.db=mongomock.MongoClient().test
        result=extract('Phone 9876543210 called phone 9123456789.')
        report={'id':'R1','title':'Calls','date':'2026-10-05','source':'Test','documentId':'D1'}
        for _ in range(2):
            self.assertTrue(store.save_extraction('CASE-1',report,result)['saved'])
        self.assertEqual(store.db.relationships.count_documents({}),1)
        stored=store.relationships_for_case('CASE-1')[0]
        self.assertEqual(stored['documentId'],'D1')
        self.assertEqual(stored['evidenceText'],'9876543210 called phone 9123456789')
        self.assertEqual(store.relationships_for_case('CASE-OTHER'),[])

if __name__=='__main__': unittest.main()
