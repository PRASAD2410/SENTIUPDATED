import unittest
from unittest.mock import patch
import mongomock
from mongomock.gridfs import enable_gridfs_integration
from gridfs import GridFS
from fastapi.testclient import TestClient
from app.mongo_store import MongoStore

enable_gridfs_integration()


class CaseManagementTests(unittest.TestCase):
    def setUp(self):
        with patch('app.neo_store.NeoStore'):
            from app import main
        self.main=main
        self.store=MongoStore();self.store.db=mongomock.MongoClient().management
        self.patches=[patch.object(main,'mongo',self.store),patch.object(main,'reports',[]),
                      patch.object(main,'edges',[]),patch.object(main,'nodes',{})]
        for p in self.patches:
            p.start();self.addCleanup(p.stop)
        self.client=TestClient(main.app)

    def seed(self,case):
        self.store.db.cases.insert_one({'_id':case,'id':case,'title':f'Title {case}',
                                      'summary':'Retain this summary','classification':'Internal'})
        doc=self.store.save_document(case,'source.txt',f'Original {case}'.encode())
        result={'entities':[{'id':'shared-org','label':'Example Company','type':'Organization'}],
                'mentions':[{'entityId':'shared-org','unitIndex':0,'start':0,'end':7}],
                'relationships':[{'id':case+'-edge','source':'shared-org','target':'shared-org','type':'ASSOCIATED_WITH'}]}
        report={'id':case+'-report','title':'Test','date':'2026-10-05','source':'Test','documentId':doc['documentId']}
        self.store.save_extraction(case,report,result)
        self.store.document_status(case,doc['documentId'],'completed',reportId=report['id'])
        self.main.reports.append({**report,'caseId':case})
        self.main.edges.append({'id':case+'-edge','source':'shared-org','target':'shared-org','reportId':report['id']})
        self.main.nodes['shared-org']={'id':'shared-org'}
        return doc

    def act(self,case,delete=False,confirmation=None):
        return self.client.request('DELETE',f'/api/cases/{case}'+('' if delete else '/data'),
                                   json={'confirm_case_id':confirmation or case})

    def test_clear_removes_only_selected_case_data_and_retains_details(self):
        a=self.seed('ONE');b=self.seed('TWO')
        response=self.act('ONE')
        self.assertEqual(response.status_code,200)
        self.assertFalse(response.json()['deleted'])
        self.assertNotIn('_reportIds',response.json())
        for name in ['documents','entities','mentions','relationships','reports']:
            self.assertEqual(self.store.db[name].count_documents({'caseId':'ONE'}),0)
            self.assertEqual(self.store.db[name].count_documents({'caseId':'TWO'}),1)
        self.assertFalse(GridFS(self.store.db).exists(a['documentId']))
        self.assertEqual(self.store.original_document('TWO',b['documentId'])[1],b'Original TWO')
        self.assertEqual(self.store.db.cases.find_one({'id':'ONE'})['summary'],'Retain this summary')
        self.assertEqual(len(self.main.reports),1)
        self.assertEqual(len(self.main.edges),1)
        self.assertIn('shared-org',self.main.nodes)
        self.assertEqual(self.act('ONE').status_code,200)

    def test_delete_case_removes_metadata_originals_and_orphan_files(self):
        self.seed('ONE')
        orphan=GridFS(self.store.db).put(b'Orphan bytes',metadata={'caseId':'ONE'})
        response=self.act('ONE',delete=True)
        self.assertEqual(response.status_code,200)
        self.assertIsNone(self.store.db.cases.find_one({'id':'ONE'}))
        self.assertFalse(GridFS(self.store.db).exists(orphan))
        self.assertEqual(self.store.db['fs.chunks'].count_documents({}),0)
        self.assertEqual(self.main.reports,[])
        self.assertEqual(self.main.nodes,{})
        self.assertEqual(self.act('ONE',delete=True).status_code,404)

    def test_confirmation_required_and_wrong_case_is_untouched(self):
        doc=self.seed('ONE')
        self.assertEqual(self.act('ONE',confirmation='TWO').status_code,422)
        self.assertEqual(self.client.delete('/api/cases/ONE').status_code,422)
        self.assertEqual(self.act('UNKNOWN').status_code,404)
        self.assertTrue(GridFS(self.store.db).exists(doc['documentId']))

    def test_legacy_case_remains_visible_after_clear(self):
        doc=self.store.save_document('default','legacy.txt',b'Legacy original')
        self.store.document_status('default',doc['documentId'],'completed')
        self.assertEqual(self.act('default').status_code,200)
        self.assertEqual(self.store.list_cases()[0]['title'],'Case 1')

    def test_file_ownership_mismatch_aborts_before_removing_data(self):
        a=self.seed('ONE');b=self.seed('TWO')
        self.store.db.documents.update_one({'caseId':'ONE'},{'$set':{'gridfsFileId':b['documentId']}})
        self.assertEqual(self.act('ONE').status_code,503)
        self.assertTrue(GridFS(self.store.db).exists(a['documentId']))
        self.assertTrue(GridFS(self.store.db).exists(b['documentId']))
        self.assertEqual(self.store.db.entities.count_documents({'caseId':'ONE'}),1)

    def test_missing_database_reports_failure_without_claiming_success(self):
        self.store.db=None
        self.assertEqual(self.act('ONE').status_code,503)

    def test_processing_file_blocks_removal(self):
        doc=self.seed('ONE')
        self.store.document_status('ONE',doc['documentId'],'processing')
        self.assertEqual(self.act('ONE').status_code,409)
        self.assertTrue(GridFS(self.store.db).exists(doc['documentId']))
        self.assertEqual(self.store.db.entities.count_documents({'caseId':'ONE'}),1)

    def test_orphan_findings_are_discoverable_and_can_be_completely_cleared(self):
        self.store.db.entities.insert_one({'id':'leftover','label':'Legacy name',
            'type':'Person','caseId':'default'})
        self.store.db.relationships.insert_one({'id':'leftover-edge','caseId':'default',
            'source':'leftover','target':'leftover','type':'CONTACTED'})
        self.store.db.mentions.insert_one({'entityId':'leftover','caseId':'default','reportId':'orphan-report'})
        self.main.edges.append({'id':'cached-orphan','reportId':'orphan-report'})
        self.assertEqual(self.client.get('/api/cases').json()['cases'][0]['id'],'default')
        self.assertEqual(self.act('default').status_code,200)
        view=self.client.get('/api/cases/default/workspace').json()
        self.assertEqual(view['overview'],{'nodes':0,'edges':0,'reports':0,'leads':0})
        self.assertEqual(self.store.db.mentions.count_documents({}),0)
        self.assertEqual(self.main.edges,[])
        self.assertEqual(self.store.list_cases()[0]['title'],'Case 1')

    def test_orphan_original_is_discoverable_and_deletable(self):
        file_id=GridFS(self.store.db).put(b'Legacy original only',metadata={'caseId':'ORPHAN'})
        self.assertEqual(self.store.list_cases()[0]['id'],'ORPHAN')
        self.assertEqual(self.act('ORPHAN',delete=True).status_code,200)
        self.assertFalse(GridFS(self.store.db).exists(file_id))
        self.assertEqual(self.store.list_cases(),[])

if __name__=='__main__':
    unittest.main()
