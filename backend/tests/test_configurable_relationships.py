import json
import unittest
from pathlib import Path
from unittest.mock import patch
from app import relations


def run(text, source, target, source_type='Person', target_type='Person'):
    mentions=[]
    for index,(label,kind) in enumerate([(source,source_type),(target,target_type)]):
        start=text.index(label)
        mentions.append({'entityId':f'entity-{index}','type':kind,'start':start,
                         'end':start+len(label),'unitIndex':0,'location':{'page_number':1}})
    return relations.extract_relationships([{'kind':'page','text':text}],mentions)


class ConfigurableRulesTests(unittest.TestCase):
    def test_names_are_not_part_of_rules(self):
        for a,b in [('Alex Example','Morgan Test'),('Another Name','Different Name')]:
            result=run(f'{a} contacted {b}.',a,b)
            self.assertEqual(len(result),1)
            self.assertEqual(result[0]['type'],'CONTACTED')
            self.assertEqual(result[0]['source'],'entity-0')
            self.assertEqual(result[0]['target'],'entity-1')

    def test_wildcard_supports_different_entity_types(self):
        result=run('Example Company is associated with Other Group.',
                   'Example Company','Other Group','Organization','Organization')
        self.assertEqual(result[0]['type'],'ASSOCIATED_WITH')

    def test_pdf_line_wrap_and_abbreviations_preserve_evidence(self):
        text='Alex Example is the son\nof Dr. Morgan Test.'
        result=run(text,'Alex Example','Dr. Morgan Test')
        self.assertEqual(result[0]['type'],'CHILD_OF')
        self.assertEqual(result[0]['evidenceText'],text[:-1])

    def test_new_rule_can_be_added_without_changing_extractor(self):
        config=json.dumps([{'id':'custom','type':'SUPPLIED_TO',
            'sourceTypes':'*','targetTypes':'*','pattern':r'\s+supplied equipment to\s+'}])
        with patch.object(Path,'read_text',return_value=config):
            result=run('Example Company supplied equipment to Other Group.',
                       'Example Company','Other Group','Organization','Organization')
        self.assertEqual(result[0]['type'],'SUPPLIED_TO')
        self.assertEqual(result[0]['ruleId'],'custom')

    def test_cooccurrence_and_negation_do_not_create_edges(self):
        for text in ['Alex Example did not contact Morgan Test.',
                     'Alex Example and Morgan Test appear in this report.']:
            self.assertEqual(run(text,'Alex Example','Morgan Test'),[])

    def test_type_constraints_are_optional_but_respected(self):
        self.assertEqual(run('Example Company is the son of Other Group.',
            'Example Company','Other Group','Organization','Organization'),[])

    def test_embedded_family_and_reported_context(self):
        text='The witness stated that Alex Example s/o Morgan Test was present.'
        result=run(text,'Alex Example','Morgan Test')
        self.assertEqual(result[0]['type'],'CHILD_OF')
        self.assertEqual(result[0]['origin'],'reported')
        self.assertEqual(result[0]['evidenceText'],'Alex Example s/o Morgan Test')
        self.assertEqual(result[0]['sentenceContext'],text)
        self.assertEqual(run('The witness denied Alex Example is the son of Morgan Test.',
                             'Alex Example','Morgan Test'),[])

    def test_temporal_adjuncts_keep_explicit_calls(self):
        for prefix in ['On 18 September 2026, ', 'At 09:00, ',
                       'On 5 May 2026, ', 'Yesterday, ', 'During the evening, ']:
            text = prefix + 'Phone 9876543210 called phone 9123456789.'
            with self.subTest(prefix=prefix):
                result = run(text, '9876543210', '9123456789', 'Phone', 'Phone')
                self.assertEqual(len(result), 1)
                self.assertEqual(result[0]['evidenceText'],
                                 '9876543210 called phone 9123456789')

    def test_generic_attribution_preserves_reported_origin(self):
        for prefix in ['The witness stated that ', 'The records show that ',
                       'According to call records, ']:
            with self.subTest(prefix=prefix):
                result = run(prefix + 'Alex Example contacted Morgan Test.',
                             'Alex Example', 'Morgan Test')
                self.assertEqual(len(result), 1)
                self.assertEqual(result[0]['origin'], 'reported')
        self.assertEqual(run('Alex Example said Morgan Test contacted Another Person.',
                             'Morgan Test', 'Another Person'), [])
        from app.extraction import extract
        result = extract('The FIR states that phone 9876543210 called phone 9123456789.')
        self.assertEqual(len(result['relationships']), 1)
        self.assertEqual(result['relationships'][0]['origin'], 'reported')

    def test_unrelated_clause_does_not_negate_explicit_connection(self):
        result = run('Alex Example contacted Morgan Test and did not contact anyone else.',
                     'Alex Example', 'Morgan Test')
        self.assertEqual(len(result), 1)
        for text in ['If Alex Example contacted Morgan Test, investigate.',
                     'Alex Example never contacted Morgan Test.',
                     'Alex Example contacted Morgan Test allegedly.',
                     'The witness denied Alex Example contacted Morgan Test.',
                     'Alex Example contacted Morgan Test, but this is unconfirmed.',
                     'Alex Example contacted Morgan Test and denied it.']:
            with self.subTest(text=text):
                self.assertEqual(run(text, 'Alex Example', 'Morgan Test'), [])

    def test_identifier_no_label_is_not_negative_no(self):
        result = run('Phone no. 9876543210 called phone no. 9123456789.',
                     '9876543210', '9123456789', 'Phone', 'Phone')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['evidenceText'],
                         '9876543210 called phone no. 9123456789')

    def test_named_or_coordinated_prefix_remains_unsupported(self):
        for text in ['Another Person said Alex Example contacted Morgan Test.',
                     'Another Person and Alex Example contacted Morgan Test.',
                     'On Monday, Another Person and Alex Example contacted Morgan Test.']:
            with self.subTest(text=text):
                self.assertEqual(run(text, 'Alex Example', 'Morgan Test'), [])

    def test_whitespace_normalization_retains_original_name_offsets(self):
        from app.extraction import extract
        text='Barack\nObama is the son of Joe  Biden.'
        result=extract(text,scope='offset-test')
        self.assertTrue(result['relationships'])
        for m in result['mentions']:
            self.assertEqual(text[m['start']:m['end']],m['label'])

    def test_reanalysis_reuses_original_and_preserves_superseded_edges(self):
        import mongomock
        from mongomock.gridfs import enable_gridfs_integration
        from fastapi.testclient import TestClient
        from app.mongo_store import MongoStore
        enable_gridfs_integration()
        with patch('app.neo_store.NeoStore'):
            from app import main
        store=MongoStore(); store.db=mongomock.MongoClient().reanalysis
        with patch.object(main,'mongo',store), patch.dict('os.environ',{'ENABLE_LLM_EXTRACTION':'false'}):
            client=TestClient(main.app)
            with patch.object(relations,'load_rules',return_value=[]):
                original=client.post('/api/upload',data={'case_id':'CASE'},files={
                    'file':('test.txt',b'Barack Obama is the son of Joe Biden.')}).json()
            path=f'/api/cases/CASE/documents/{original["documentId"]}/reanalyze'
            counts=[store.db.entities.count_documents({}),store.db.mentions.count_documents({})]
            for _ in range(2):
                response=client.post(path)
                self.assertEqual(response.status_code,200)
                self.assertEqual(response.json()['relationshipCount'],1)
                self.assertEqual(response.json()['reportId'],original['reportId'])
            self.assertEqual(store.db.documents.count_documents({}),1)
            self.assertEqual(store.db.relationships.count_documents({}),1)
            self.assertEqual(counts,[store.db.entities.count_documents({}),store.db.mentions.count_documents({})])
            self.assertEqual(client.post(path.replace('/CASE/','/OTHER/')).status_code,404)
            with patch.object(relations,'load_rules',return_value=[]):
                self.assertEqual(client.post(path).json()['relationshipCount'],0)
            self.assertEqual(store.relationships_for_case('CASE'),[])
            self.assertEqual(store.db.relationships.count_documents({}),1)

if __name__=='__main__':
    unittest.main()
