"""Structured parser for FIR forms, incident reports, and accused/entity tables."""
import re
from typing import Dict, List, Any


def extract_fir_structure(text: str, scope: str = '') -> Dict[str, Any]:
    """Parse key-value headers, sections, and accused tables from structured FIR/Police reports."""
    entities = {}
    mentions = []
    relationships = []
    warnings = []

    lines = [line.strip() for line in text.split('\n') if line.strip()]

    # 1. Look for FIR Number / Case ID
    fir_no_match = re.search(r'(?i)\b(?:FIR\s*(?:No\.?|Number)|First\s*Information\s*Report\s*No\.?)\s*[:\-\s]+\s*([A-Z0-9\-_/]+)', text)
    fir_entity_id = None
    if fir_no_match:
        fir_label = fir_no_match.group(1).strip()
        fir_entity_id = f'fir:{fir_label.lower()}'
        entities[fir_entity_id] = {
            'id': fir_entity_id,
            'label': f'FIR {fir_label}',
            'type': 'Case',
            'normalizedValue': fir_label.upper(),
            'identityStatus': 'normalized'
        }

    # 2. Investigating Officer / Complainant (single line)
    io_match = re.search(r'(?i)(?:Investigating\s*Officer|I\.?O\.?|Complainant|Informant)\s*[:\-\s]+\s*(?:Inspector|Constable|Sub-Inspector|SI|ASI)?\s*([A-Z][a-zA-Z\. ]{2,30})', text)
    if io_match and fir_entity_id:
        io_name = io_match.group(1).strip()
        if len(io_name) > 2 and not any(w in io_name.lower() for w in ('fictional', 'demonstration', 'synthetic', 'unit')):
            io_id = f'person:{io_name.lower().replace(" ", "-")}'
            entities[io_id] = {'id': io_id, 'label': io_name, 'type': 'Person', 'identityStatus': 'unverified-name-group'}
            relationships.append({
                'id': f'rel:fir-io-{len(relationships)}',
                'source': io_id,
                'target': fir_entity_id,
                'type': 'INVESTIGATED',
                'confidence': 0.95,
                'method': 'fir-form-parser',
                'origin': 'asserted',
                'evidenceText': f'{io_name} Investigating Officer for {entities[fir_entity_id]["label"]}',
                'ruleId': 'fir-officer-assignment'
            })

    # 3. Accused / Mentioned Persons Table (e.g. ENT-001 | Rahul Sharma | Primary person of interest)
    HEADER_KEYWORDS = {'important', 'fir number', 'case id', 'police station', 'investigation type',
                       'classification', 'investigating officer', 'source id', 'date/time', 'date',
                       'field', 'synthetic value', 'source type', 'analyst note', 'first information report',
                       'other contacts', 'synthetic observation', 'evidence references', 'persons mentioned'}
    for line in lines:
        line_clean = line.strip()
        match = re.search(r'^(?:(?:ENT|ACC|PER|ORG|ACCUSED|ID)[-_]?\d*\s+)?([A-Z][a-zA-Z\s\.]{2,35})\s{2,}(.+)$', line_clean)
        if match:
            name, role = match.group(1).strip(), match.group(2).strip()
            if any(hdr in name.lower() for hdr in HEADER_KEYWORDS):
                continue
            if len(name) < 3:
                continue
            
            # Decide type
            kind = 'Organization' if any(org in name.lower() for org in ('exports', 'trust', 'logistics', 'pvt', 'ltd', 'corp', 'bank', 'enterprises')) else 'Person'
            ent_id = f'{kind.lower()}:{name.lower().replace(" ", "-")}'
            entities[ent_id] = {'id': ent_id, 'label': name, 'type': kind, 'identityStatus': 'unverified-name-group'}

            if fir_entity_id:
                rel_type = 'ACCUSED_IN' if any(w in role.lower() for w in ('accused', 'suspect', 'primary')) else 'MENTIONED_IN'
                relationships.append({
                    'id': f'rel:fir-named-{len(relationships)}',
                    'source': ent_id,
                    'target': fir_entity_id,
                    'type': rel_type,
                    'confidence': 0.9,
                    'method': 'fir-form-parser',
                    'origin': 'asserted',
                    'evidenceText': f'{name} ({role}) in {entities[fir_entity_id]["label"]}',
                    'ruleId': 'fir-entity-table'
                })

    # 4. Repeated calls/contacts across entities mentioned in narrative
    # Example: "repeated calls among Rahul Sharma, Rajesh Bindal, Vikram Sethi"
    narrative_calls = re.search(r'(?i)(?:repeated|frequent|multiple)?\s*(?:calls|communications|transfers|meetings)\s*(?:among|between)\s+([A-Z][a-zA-Z\s,]+(?:and\s+[A-Z][a-zA-Z\s]+)?)', text)
    if narrative_calls:
        raw_names = narrative_calls.group(1)
        raw_split = [n.strip() for n in re.split(r',|\band\b', raw_names) if len(n.strip()) > 3]
        name_list = []
        for cand in raw_split:
            cand_clean = cand.split('\n')[0].strip()
            words = cand_clean.split()
            if len(words) >= 2 and all(w[0].isupper() for w in words if w):
                name_list.append(cand_clean)
        matched_ids = []
        for n in name_list:
            cand_id = f'person:{n.lower().replace(" ", "-")}'
            if cand_id in entities:
                matched_ids.append(cand_id)
            else:
                entities[cand_id] = {'id': cand_id, 'label': n, 'type': 'Person', 'identityStatus': 'unverified-name-group'}
                matched_ids.append(cand_id)
        
        # Create mutual CONTACTED relationships among the listed group
        for i in range(len(matched_ids)):
            for j in range(i + 1, len(matched_ids)):
                relationships.append({
                    'id': f'rel:fir-comm-{len(relationships)}',
                    'source': matched_ids[i],
                    'target': matched_ids[j],
                    'type': 'CONTACTED',
                    'confidence': 0.85,
                    'method': 'fir-form-parser',
                    'origin': 'asserted',
                    'evidenceText': f'Repeated communication reported between {entities[matched_ids[i]]["label"]} and {entities[matched_ids[j]]["label"]}',
                    'ruleId': 'fir-narrative-communication'
                })

    return {
        'entities': list(entities.values()),
        'relationships': relationships,
        'warnings': warnings
    }
