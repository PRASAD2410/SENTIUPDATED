"""Optional Neo4j persistence adapter. The app remains usable in demo-memory mode."""
import os
from neo4j import GraphDatabase

class NeoStore:
    def __init__(self):
        self.driver = None
        password = os.getenv('NEO4J_PASSWORD')
        user = os.getenv('NEO4J_USER', 'neo4j')
        uris_to_try = [
            os.getenv('NEO4J_URI', '').strip(),
            'bolt://localhost:7687',
            'bolt://127.0.0.1:7687',
            'bolt://neo4j:7687'
        ]
        if password:
            for uri in dict.fromkeys(filter(None, uris_to_try)):
                try:
                    driver = GraphDatabase.driver(uri, auth=(user, password))
                    driver.verify_connectivity()
                    self.driver = driver
                    break
                except Exception:
                    self.driver = None
    @property
    def available(self): return self.driver is not None
    def seed(self, nodes, edges):
        if not self.driver: return
        with self.driver.session() as s:
            s.run('CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (n:Entity) REQUIRE n.id IS UNIQUE')
            for n in nodes.values():
                s.run('MERGE (n:Entity {id:$id}) SET n.label=$label,n.type=$type,n.risk=$risk', **n)
            for e in edges:
                s.run('MATCH (a:Entity {id:$source}),(b:Entity {id:$target}) MERGE (a)-[r:RELATED {kind:$label, reportId:$reportId}]->(b) SET r.provenance=$reportId', **e)
    def add_extraction(self, entities, relationships, report_id):
        if not self.driver: return
        with self.driver.session() as s:
            for n in entities:
                params = {
                    'id': n.get('id', ''),
                    'label': n.get('label', ''),
                    'type': n.get('type', 'Entity'),
                    'confidence': float(n.get('confidence') or 1.0)
                }
                s.run('MERGE (n:Entity {id:$id}) SET n.label=$label, n.type=$type, n.confidence=$confidence', **params)
            for rel in relationships:
                params = {
                    'source': rel.get('source', ''),
                    'target': rel.get('target', ''),
                    'type': rel.get('type', 'RELATED'),
                    'confidence': float(rel.get('confidence') or 1.0),
                    'reportId': report_id
                }
                s.run('MATCH (a:Entity {id:$source}),(b:Entity {id:$target}) CREATE (a)-[r:RELATED {kind:$type, reportId:$reportId, confidence:$confidence}]->(b) SET r.provenance=$reportId', **params)
