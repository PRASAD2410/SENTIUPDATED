"""MongoDB entity and mention persistence, separate from the demo graph cache."""
import os
import hashlib
from uuid import uuid4
from gridfs import GridFS
from datetime import datetime, timezone
from pymongo import MongoClient
from pymongo.errors import PyMongoError, DuplicateKeyError

class CaseBusyError(RuntimeError):
    pass


class MongoStore:
    def __init__(self):
        self.uri = os.getenv('MONGODB_URI', '').strip()
        self.database_name = os.getenv('MONGODB_DATABASE', 'sentinelgraph')
        self.client = None
        self.db = None
        self.error = None

    def connect(self):
        if not self.uri:
            self.uri = os.getenv('MONGODB_URI', '').strip()
            self.database_name = os.getenv('MONGODB_DATABASE', 'sentinelgraph')
        if not self.uri:
            return
        try:
            self.client = MongoClient(self.uri, serverSelectionTimeoutMS=5000,
                                      connectTimeoutMS=5000, socketTimeoutMS=10000)
            self.client.admin.command('ping')
            self.db = self.client[self.database_name]
            self.db.entities.create_index([('caseId', 1), ('type', 1)])
            self.db.mentions.create_index([('caseId', 1), ('reportId', 1)])
            self.db.reports.create_index([('caseId', 1), ('createdAt', -1)])
            self.db.documents.create_index([('caseId', 1), ('uploadedAt', -1)])
            self.db.documents.create_index([('caseId', 1), ('sha256', 1)])
            self.db.relationships.create_index([('caseId', 1), ('reportId', 1)])
            self.error = None
        except PyMongoError:
            self.db = None
            self.error = 'MongoDB is unreachable. Verify MONGODB_URI and start the database.'

    def status(self):
        connected = self.db is not None
        if connected and self.client is not None:
            try:
                self.client.admin.command('ping', maxTimeMS=3000)
                self.error = None
            except PyMongoError:
                connected = False
                self.error = 'MongoDB connection failed. Check the network and Atlas IP access list; saved records could not be reached.'
        return {'configured': bool(self.uri), 'connected': connected,
                'database': self.database_name, 'warning': self.error}

    def save_document(self, case_id, filename, content, content_type=None):
        """Save original bytes before parsing. Fail explicitly if not durable."""
        if self.db is None:
            raise RuntimeError(self.error or 'MongoDB is not connected; the original file was not saved.')
        digest = hashlib.sha256(content).hexdigest()
        lookup = {'caseId': case_id, 'sha256': digest}
        existing = self.db.documents.find_one({**lookup, 'processingStatus': 'completed'}, sort=[('uploadedAt', 1)])
        if not existing:
            existing = self.db.documents.find_one(lookup, sort=[('uploadedAt', 1)])
        if existing:
            return {**{k: v for k, v in existing.items() if k != '_id'}, 'duplicate': True}
        # Deterministic IDs also prevent concurrent identical uploads from
        # creating two records. Existing legacy UUID documents are reused above.
        document_id = 'DOC-' + hashlib.sha256(f'{case_id}:{digest}'.encode()).hexdigest()
        files = GridFS(self.db)
        uploaded = False
        try:
            record = {'_id': document_id, 'documentId': document_id,
                      'caseId': case_id, 'filename': filename,
                      'gridfsFileId': document_id,
                      'contentType': content_type or 'application/octet-stream',
                      'sizeBytes': len(content), 'sha256': digest,
                      'processingStatus': 'storing', 'uploadedAt': datetime.now(timezone.utc)}
            try:
                self.db.documents.insert_one(record)
            except DuplicateKeyError:
                existing = self.db.documents.find_one({'_id': document_id, 'caseId': case_id})
                return {**{k: v for k, v in existing.items() if k != '_id'}, 'duplicate': True}
            files.put(content, _id=document_id, filename=filename,
                      contentType=content_type or 'application/octet-stream',
                      metadata={'caseId': case_id, 'documentId': document_id})
            uploaded = True
            record['processingStatus'] = 'pending'
            self.document_status(case_id, document_id, 'pending')
            return {k: v for k, v in record.items() if k != '_id'}
        except PyMongoError:
            if uploaded:
                try:
                    files.delete(document_id)
                except PyMongoError:
                    pass
            try:
                self.db.documents.update_one({'_id': document_id, 'caseId': case_id},
                                             {'$set': {'processingStatus': 'storage_failed'}})
            except PyMongoError:
                pass
            raise RuntimeError('Original file storage failed. Check MongoDB and retry.') from None

    def extraction_for_report(self, case_id, report_id):
        if self.db is None:
            return {'entities': [], 'mentions': [], 'relationships': []}
        return {
            'entities': list(self.db.entities.find({'caseId': case_id, 'reportIds': report_id, 'active': {'$ne': False}}, {'_id': 0})),
            'mentions': list(self.db.mentions.find({'caseId': case_id, 'reportId': report_id, 'active': {'$ne': False}}, {'_id': 0})),
            'relationships': list(self.db.relationships.find({'caseId': case_id, 'reportId': report_id,
                'active': {'$ne': False}}, {'_id': 0})),
        }

    def document_status(self, case_id, document_id, status, **details):
        if self.db is None:
            raise RuntimeError('MongoDB is not connected.')
        self.db.documents.update_one({'_id': document_id, 'caseId': case_id}, {
            '$set': {'processingStatus': status, 'updatedAt': datetime.now(timezone.utc), **details}})

    def documents_for_case(self, case_id):
        if self.db is None:
            raise RuntimeError('MongoDB is not connected.')
        documents = list(self.db.documents.find({'caseId': case_id}, {'_id': 0}).sort('uploadedAt', -1).limit(1000))
        report_ids = [d['reportId'] for d in documents if d.get('reportId')]
        counts = {r['_id']: r for r in self.db.reports.find({'caseId': case_id, '_id': {'$in': report_ids}},
                  {'entityCount': 1, 'relationshipCount': 1, 'mentionCount': 1, 'relationshipStatus': 1})}
        for document in documents:
            report = counts.get(document.get('reportId'), {})
            document.update({key: report[key] for key in ('entityCount', 'relationshipCount', 'mentionCount', 'relationshipStatus') if key in report})
        return documents

    def original_document(self, case_id, document_id):
        if self.db is None:
            raise RuntimeError('MongoDB is not connected.')
        record = self.db.documents.find_one({'_id': document_id, 'caseId': case_id})
        if record is None:
            return None
        file = GridFS(self.db).get(record['gridfsFileId'])
        return record, file.read()

    def save_extraction(self, case_id, report, result):
        if self.db is None:
            return {'saved': False, 'warning': self.error or 'MongoDB is not configured; entities remain in the current memory workspace.'}
        now = datetime.now(timezone.utc)
        report_id = report['id']
        try:
            # A completion marker makes interrupted, non-transactional writes
            # visible. Upserts let a future retry safely complete the same run.
            self.db.reports.update_one({'_id': report_id}, {'$set': {
                'caseId': case_id, 'title': report['title'], 'date': report['date'],
                'documentId': report.get('documentId'),
                'source': report['source'], 'status': 'writing', 'updatedAt': now},
                '$setOnInsert': {'createdAt': now}}, upsert=True)
            for entity in result['entities']:
                key = f'{case_id}:{entity["id"]}'
                self.db.entities.update_one({'_id': key}, {
                    '$set': {**entity, 'caseId': case_id, 'active': True, 'updatedAt': now},
                    '$setOnInsert': {'createdAt': now},
                    '$addToSet': {'reportIds': report_id}}, upsert=True)
            for index, mention in enumerate(result['mentions']):
                prefix = 'columns:' if mention.get('method') == 'structured-column' else ''
                self.db.mentions.update_one({'_id': f'{report_id}:{prefix}{index}'}, {
                    '$set': {**mention, 'caseId': case_id, 'reportId': report_id,
                             'active': True, 'documentId': report.get('documentId')}}, upsert=True)
            for relationship in result.get('relationships', []):
                self.db.relationships.update_one({'_id': f'{report_id}:{relationship["id"]}'}, {
                    '$set': {**relationship, 'caseId': case_id, 'reportId': report_id,
                             'documentId': report.get('documentId'), 'updatedAt': now},
                    '$setOnInsert': {'createdAt': now}}, upsert=True)
            self.db.reports.update_one({'_id': report_id}, {'$set': {
                'status': 'complete' if result.get('relationshipStatus', {}).get('complete', True) else 'relationships_pending', 'entityCount': len(result['entities']),
                'relationshipStatus': result.get('relationshipStatus'),
                'extractionVersion': result.get('extractionVersion'),
                'relationshipCount': len(result.get('relationships', [])),
                'mentionCount': len(result['mentions']), 'updatedAt': now}})
            self.error = None
            return {'saved': True, 'entities': len(result['entities']),
                    'mentions': len(result['mentions']), 'relationships': len(result.get('relationships', []))}
        except PyMongoError:
            self.error = 'MongoDB write failed; storage may be incomplete. Check the database before retrying.'
            return {'saved': False, 'warning': self.error}

    def entities_for_case(self, case_id):
        if self.db is None:
            raise RuntimeError(self.error or 'MongoDB is not configured.')
        return list(self.db.entities.find({'caseId': case_id, 'active': {'$ne': False}}, {'_id': 0}).limit(1000))

    def relationships_for_case(self, case_id):
        if self.db is None:
            raise RuntimeError('MongoDB is not connected.')
        return list(self.db.relationships.find({'caseId': case_id, 'active': {'$ne': False}}, {'_id': 0}).limit(1000))

    def reanalyze_relationships(self, case_id, document_id, parsed):
        """Update edges for existing mentions without creating another upload.

        Superseded edges remain in storage for audit, excluded from graph reads.
        """
        if self.db is None:
            raise RuntimeError('MongoDB is not connected.')
        from .relations import extract_relationships, VERSION as REL_VERSION
        record = self.db.documents.find_one({'_id': document_id, 'caseId': case_id})
        report_id = record.get('reportId') if record else None
        if not report_id:
            raise ValueError('The document has no completed extraction to reanalyze.')
        from .structured_calls import extract_calls, VERSION as CALL_VERSION
        from .extraction import entity, extract, build_relationships, get_extraction_version, RelationshipExtractionError
        mapped = extract_calls(parsed['units'], entity)
        mapped_warnings = None
        active_version = REL_VERSION
        if mapped['handled']:
            # Reuse the same report and original file. Keep the older NER
            # mentions as inactive audit records, replacing their graph view.
            result = extract(parsed['text'], parsed, scope=f'case:{case_id}')
            if not result.get('relationshipStatus', {}).get('complete', True):
                raise RelationshipExtractionError(' '.join(result['warnings'][:3]) or 'Gemini relationship extraction failed; existing findings were retained.')
            relationship_status = result.get('relationshipStatus')
            report = self.db.reports.find_one({'_id': report_id, 'caseId': case_id})
            if report is None:
                raise ValueError('The extraction report is missing.')
            old_ids = self.db.entities.distinct('id', {'caseId': case_id, 'reportIds': report_id})
            saved = self.save_extraction(case_id, {**report, 'id': report_id}, result)
            if not saved['saved']:
                raise RuntimeError(saved['warning'])
            active_mentions = [f'{report_id}:{"columns:" if m.get("method") == "structured-column" else ""}{i}'
                               for i, m in enumerate(result['mentions'])]
            self.db.mentions.update_many({'caseId': case_id, 'reportId': report_id,
                '_id': {'$nin': active_mentions}}, {'$set': {'active': False}})
            new_ids = {e['id'] for e in result['entities']}
            for old_id in set(old_ids) - new_ids:
                self.db.entities.update_one({'caseId': case_id, 'id': old_id}, {'$pull': {'reportIds': report_id}})
                self.db.entities.update_one({'caseId': case_id, 'id': old_id, 'reportIds': []}, {'$set': {'active': False}})
            results = result['relationships']
            mapped_warnings = result['warnings']
            active_version = CALL_VERSION
        else:
            mentions = list(self.db.mentions.find({'caseId': case_id, 'reportId': report_id, 'active': {'$ne': False}}))
            entities = self.extraction_for_report(case_id, report_id)['entities']
            relation_result = build_relationships(parsed['units'], entities, mentions)
            if not relation_result['relationshipStatus']['complete']:
                raise RelationshipExtractionError(' '.join(relation_result['warnings'][:3]) or 'Gemini relationship extraction failed; existing findings were retained.')
            results = relation_result['relationships']
            relationship_status = relation_result['relationshipStatus']
            mapped_warnings = relation_result['warnings']
            if relationship_status['mode'] == 'gemini':
                from .gemini_relations import VERSION as GEMINI_VERSION
                active_version = GEMINI_VERSION
        now = datetime.now(timezone.utc)
        # Restore/reuse stable IDs for matches; preserve superseded evidence.
        for relationship in results:
            self.db.relationships.update_one({'_id': f'{report_id}:{relationship["id"]}'}, {
                '$set': {**relationship, 'caseId': case_id, 'reportId': report_id,
                         'documentId': document_id, 'active': True, 'updatedAt': now},
                '$setOnInsert': {'createdAt': now}}, upsert=True)
        ids = [f'{report_id}:{r["id"]}' for r in results]
        self.db.relationships.update_many({'caseId': case_id, 'reportId': report_id,
            '_id': {'$nin': ids}}, {'$set': {'active': False, 'updatedAt': now}})
        self.db.reports.update_one({'_id': report_id, 'caseId': case_id}, {'$set': {
            'status': 'complete',
            'relationshipCount': len(results), 'relationshipExtractorVersion': active_version,
            'extractionVersion': get_extraction_version(), 'relationshipStatus': relationship_status,
            'updatedAt': now}})
        warnings = mapped_warnings if mapped_warnings is not None else [w for w in record.get('warnings', []) if not w.startswith('Entities extracted; no explicit relationships')]
        if not results:
            warnings.append('Entities extracted; no source-supported relationships were found by the current extractor.')
        self.document_status(case_id, document_id, record['processingStatus'],
                             relationshipExtractorVersion=active_version, extractionVersion=get_extraction_version(), relationshipStatus=relationship_status, warnings=warnings)
        return {'caseId': case_id, 'documentId': document_id, 'reportId': report_id,
                'relationships': results, 'relationshipCount': len(results),
                'extractorVersion': active_version, 'extractionVersion': get_extraction_version(), 'relationshipStatus': relationship_status, 'warnings': warnings, 'saved': True}

    def list_cases(self):
        if self.db is None:
            raise RuntimeError('MongoDB is not connected.')
        cases = list(self.db.cases.find({}, {'_id': 0}).sort('createdAt', -1))
        known = {c['id'] for c in cases}
        # Recover legacy/partially cleared cases even when only derived records
        # or original GridFS files remain. Otherwise their management UI vanishes.
        discovered = set()
        for name in ('documents', 'reports', 'entities', 'mentions', 'relationships'):
            discovered.update(self.db[name].distinct('caseId'))
        discovered.update(self.db['fs.files'].distinct('metadata.caseId'))
        for case_id in sorted(c for c in discovered if isinstance(c, str) and c):
            if case_id not in known:
                cases.append({'id': case_id, 'title': 'Default workspace' if case_id == 'default' else case_id,
                              'classification': 'Restricted', 'status': 'Active', 'summary': ''})
        return cases

    def create_case(self, title, classification, summary):
        if self.db is None:
            raise RuntimeError('MongoDB is not connected.')
        case_id = 'CASE-' + uuid4().hex[:12].upper()
        case = {'id': case_id, 'title': title, 'classification': classification,
                'summary': summary, 'status': 'Active', 'createdAt': datetime.now(timezone.utc)}
        self.db.cases.insert_one({'_id': case_id, **case})
        return case

    def clear_case(self, case_id, delete_case=False):
        """Remove only this case's originals and derived records.

        Metadata is removed last so a partial GridFS failure remains retryable.
        This is called only by the explicitly confirmed management endpoints.
        """
        if self.db is None:
            raise RuntimeError('MongoDB is not connected.')
        collections = ('documents', 'entities', 'mentions', 'relationships', 'reports')
        exists = self.db.cases.find_one({'id': case_id}) is not None or any(
            self.db[name].find_one({'caseId': case_id}) is not None for name in collections)
        exists = exists or self.db['fs.files'].find_one({'metadata.caseId': case_id}) is not None
        if not exists:
            raise ValueError('Case not found.')
        if self.db.documents.find_one({'caseId': case_id, 'processingStatus': {
                '$in': ['storing', 'pending', 'processing']}}):
            raise CaseBusyError('A file in this case is still processing. Wait for it to finish before removing case data.')
        report_ids = set(self.db.reports.distinct('_id', {'caseId': case_id}))
        for name in ('documents', 'mentions', 'relationships'):
            report_ids.update(self.db[name].distinct('reportId', {'caseId': case_id}))
        report_ids.discard(None)
        entity_ids = self.db.entities.distinct('id', {'caseId': case_id})
        file_ids = set(self.db.documents.distinct('gridfsFileId', {'caseId': case_id}))
        file_ids.update(self.db['fs.files'].distinct('_id', {'metadata.caseId': case_id}))
        # Validate ownership before changing anything; case files are never shared.
        for file_id in file_ids:
            file_record = self.db['fs.files'].find_one({'_id': file_id})
            if file_record and file_record.get('metadata', {}).get('caseId') != case_id:
                raise RuntimeError('A file ownership mismatch requires review before clearing this case.')
        files = GridFS(self.db)
        for file_id in file_ids:
            files.delete(file_id)
        counts = {name: self.db[name].delete_many({'caseId': case_id}).deleted_count for name in collections}
        if delete_case:
            self.db.cases.delete_many({'id': case_id})
        elif self.db.cases.find_one({'id': case_id}) is None:
            # Keep a legacy/default workspace visible after clearing its records.
            self.db.cases.insert_one({'_id': case_id, 'id': case_id,
                'title': 'Default workspace' if case_id == 'default' else case_id,
                'classification': 'Restricted', 'status': 'Active', 'summary': '',
                'createdAt': datetime.now(timezone.utc)})
        return {'caseId': case_id, 'deleted': delete_case, 'removed': counts,
                'filesRemoved': len(file_ids), '_reportIds': list(report_ids), '_entityIds': entity_ids}

    def close(self):
        if self.client is not None:
            self.client.close()
