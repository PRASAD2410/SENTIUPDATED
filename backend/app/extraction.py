"""Entity mentions from source units; identifiers use rules, narrative uses NER."""
import hashlib
import os
import re
import unicodedata
from .nlp import NLP, NLP_WARNING, nlp_status
from .llm import get_llm_provider
from .relations import extract_relationships, VERSION as RELATIONSHIP_VERSION
from .structured_calls import extract_calls, VERSION as CALL_VERSION
from .validators import luhn_checksum_valid, normalize_phone, normalize_vehicle, normalize_upi, normalize_account, normalize_ifsc
from .fir_parser import extract_fir_structure
from .structured_bank import extract_bank_transactions
from .structured_registry import extract_registry, VERSION as REGISTRY_VERSION

def get_extraction_version():
    from .gemini_relations import VERSION as GEMINI_VERSION
    mode = os.getenv('RELATIONSHIP_EXTRACTOR', 'regex').strip().lower()
    model = os.getenv('GEMINI_MODEL', 'default') if mode == 'gemini' else ''
    compact = os.getenv('GEMINI_COMPACT_CONTEXT', 'true').strip().lower() not in {'false', '0', 'no', 'off'}
    return f'source-v3:spacy-entities:{RELATIONSHIP_VERSION}:{CALL_VERSION}:{REGISTRY_VERSION}:{GEMINI_VERSION}:{mode}:{model}:compact={compact}'


EXTRACTION_VERSION = get_extraction_version()


class RelationshipExtractionError(RuntimeError):
    """Retryable relationship provider failure; existing findings stay intact."""


def build_relationships(units, entities, mentions, provider=None, call_relationships=None):
    mode = os.getenv('RELATIONSHIP_EXTRACTOR', 'regex').strip().lower()
    if mode not in {'regex', 'gemini'}:
        mode = 'regex'
    warnings = []
    status = {'mode': mode, 'attempted': 0, 'succeeded': 0, 'complete': True}
    relationships = list(call_relationships) if call_relationships is not None else []
    if mode == 'gemini':
        llm = provider or get_llm_provider()
        if not llm.available:
            warnings.append('Gemini API key is not configured; using offline rule-based relationship extractor.')
            relationships.extend(extract_relationships(units, mentions))
            status.update(mode='regex (fallback)', complete=True)
        else:
            from .gemini_relations import extract_gemini_relationships
            result = extract_gemini_relationships(units, entities, mentions, llm)
            relationships.extend(result['relationships'])
            warnings.extend(result['warnings'])
            status.update(attempted=result['attempted'], succeeded=result['succeeded'], complete=not result.get('failed', False))
            if result.get('input') is not None:
                status['input'] = result['input']
            if result.get('failed', False):
                warnings.append('Gemini extraction failed; supplemented with rule-based relationships.')
                relationships.extend(extract_relationships(units, mentions))
    else:
        relationships.extend(extract_relationships(units, mentions))
    return {'relationships': relationships, 'warnings': warnings, 'relationshipStatus': status}


PATTERNS = [
    ('Phone', r'(?<!\w)(?:\+91[- ]?|0)?[6-9]\d{9}\b'),
    ('Vehicle', r'\b[A-Z]{2}[- ]?\d{1,2}[- ]?[A-Z]{1,3}[- ]?\d{4}\b'),
    ('Account', r'(?i)\b(?:account(?:\s*(?:number|no\.?))?|a/c)\s*[:#-]?\s*(\d{9,18})\b'),
    ('UPI', r'\b[a-zA-Z0-9.\-_]{2,64}@[a-zA-Z]{2,32}\b'),
    ('IMEI', r'(?i)\bIMEI\s*[:#-]?\s*(\d{15})\b')
]
KINDS = {'PERSON': 'Person', 'ORG': 'Organization', 'GPE': 'Location', 'LOC': 'Location', 'FAC': 'Location'}

HONORIFICS = re.compile(r'^(?:mr|mrs|ms|dr|shri|smt|prof|adv|inspector|constable|si|asi|acp|dcp|dsp|hc|officer)\.?\s+', re.I)

STOPWORDS = {
    'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by',
    'from', 'up', 'about', 'into', 'over', 'after', 'beneath', 'under', 'above', 'this', 'that',
    'these', 'those', 'it', 'its', 'they', 'them', 'their', 'we', 'us', 'our', 'you', 'your',
    'he', 'him', 'his', 'she', 'her', 'who', 'whom', 'which', 'what', 'where', 'when', 'why',
    'how', 'all', 'any', 'both', 'each', 'few', 'more', 'most', 'other', 'some', 'such', 'no',
    'nor', 'not', 'only', 'own', 'same', 'so', 'than', 'too', 'very', 'can', 'will', 'just',
    'should', 'now', 'also', 'then', 'there', 'here'
}

BOILERPLATE = {
    'draft', 'working', 'working draft', 'problem', 'problem statement', 'context', 'architecture',
    'risk', 'register', 'data plan', 'evaluation plan', 'evaluation', 'formal statement',
    'design principles', 'decision', 'system', 'research claim', 'research', 'claim', 'scope',
    'section', 'table', 'figure', 'annexure', 'item', 'total', 'status', 'summary', 'report',
    'document', 'dataset', 'module', 'study', 'matrix', 'model', 'models', 'method', 'methods',
    'algorithm', 'parameter', 'score', 'scores', 'precision', 'recall', 'baseline', 'framework',
    'analysis', 'intelligence', 'analytics', 'layer', 'layers', 'ontology', 'schema', 'pipeline',
    'ablation', 'loss', 'accuracy', 'node', 'nodes', 'edge', 'edges', 'graph', 'graphs',
    'network', 'networks', 'link', 'links', 'connection', 'connections', 'source', 'sources',
    'target', 'targets', 'evidence', 'hypothesis', 'hypotheses', 'investigator', 'officer',
    'accused', 'suspect', 'witness', 'victim', 'complainant', 'police', 'court', 'judge',
    'lawyer', 'driver', 'hotel', 'family', 'someone', 'anyone', 'none', 'etc', 'case', 'cases',
    'page', 'pages', 'level', 'levels', 'task', 'tasks', 'gap', 'gaps', 'fix', 'gnn', 'lstm',
    'gat', 'graphsage', 'envit', 'cnis', 'firs', 'fir', 'cdrs', 'cdr', 'bns', 'ipc', 'aadhaar',
    'node2vec', 'katz', 'muril', 'indicbert', 'paysim', 'amlsim', 'amlworld', 'elliptic bitcoin'
}

def nlp_text_with_offsets(text):
    """Flatten PDF whitespace for NER while retaining original source offsets."""
    characters, offsets = [], []
    for token in re.finditer(r'\S+', text):
        if characters:
            characters.append(' ')
            offsets.append(token.start() - 1)
        characters.extend(token.group())
        offsets.extend(range(token.start(), token.end()))
    return ''.join(characters), offsets

def is_valid_entity(label, kind):
    """Filter out noise, section numbers, punctuation, and academic/boilerplate words."""
    if not label or not isinstance(label, str):
        return False
    clean = label.strip().strip('•-*_~`#()[]{}|/\\:;,."\'')
    if not clean:
        return False
    if kind == 'IMEI':
        digits = re.sub(r'\D', '', clean)
        return len(digits) == 15 and luhn_checksum_valid(digits)
    if kind == 'Phone':
        return normalize_phone(clean) is not None
    if kind == 'Vehicle':
        return normalize_vehicle(clean) is not None
    if kind == 'UPI':
        return normalize_upi(clean) is not None
    if kind == 'Account':
        return len(re.sub(r'\D', '', clean)) >= 4 or (len(clean) >= 4 and any(c.isdigit() for c in clean))
    if len(clean) < 2:
        return False
    clean_lower = clean.lower()
    if clean_lower in STOPWORDS or clean_lower in BOILERPLATE:
        return False
    if clean_lower.startswith(('section ', 'table ', 'figure ', 'page ', 'annexure ', 'article ', 'clause ', 'item ', 'draft ', 'version ', 'part ', 'chapter ')):
        return False
    # Check if string is purely numeric, ordinals, section numbers or versions (e.g. '1.1', 'v0.1', 'T46')
    if re.fullmatch(r'v?\d+(?:\.\d+)*|[A-Za-z]\d{1,3}|(?:\d+(?:st|nd|rd|th))', clean, re.I):
        return False
    if kind == 'Person':
        # Persons must have letters and cannot be purely numbers or code-like tokens
        if not re.search(r'[A-Za-z]', clean) or re.search(r'\d', clean):
            return False
        if len(clean) > 80:
            return False
        words = clean.split()
        if len(words) == 1 and (len(clean) < 3 or clean.islower()):
            if clean_lower in BOILERPLATE or clean_lower in STOPWORDS:
                return False
    if kind == 'Organization':
        if len(clean) < 2 or len(clean) > 100 or clean_lower in BOILERPLATE:
            return False
    return True

def normalized(label, kind):
    value = unicodedata.normalize('NFKC', label).strip()
    if kind == 'Phone':
        norm = normalize_phone(value)
        return norm if norm else re.sub(r'\D', '', value)
    if kind == 'IMEI':
        return re.sub(r'\D', '', value)
    if kind == 'Vehicle':
        norm = normalize_vehicle(value)
        return norm if norm else re.sub(r'[^A-Z0-9]', '', value.upper())
    if kind == 'UPI':
        norm = normalize_upi(value)
        return norm if norm else value.strip().lower()
    if kind == 'Account':
        norm = normalize_account(value)
        return norm if norm else re.sub(r'\D', '', value)
    if kind == 'Person':
        cleaned = HONORIFICS.sub('', value).strip()
        return ' '.join(cleaned.casefold().split())
    return ' '.join(value.casefold().split())

def entity(label, kind, confidence=None, scope=''):
    value = normalized(label, kind)
    # Names are document-scoped until real identity resolution is available.
    key = f'{scope if kind == "Person" else ""}:{kind}:{value}'
    item = {'id': f'{kind.lower()}:{hashlib.sha256(key.encode()).hexdigest()[:24]}',
            'label': label.strip(), 'type': kind, 'normalizedValue': value,
            'identityStatus': ('unverified-name-group' if scope.startswith('case:') else 'unresolved') if kind == 'Person' else 'normalized'}
    if confidence is not None:
        item['confidence'] = confidence
        item['confidenceKind'] = 'heuristic, not calibrated'
    return item

def extract(text, parsed_document=None, scope=''):
    entities, mentions = {}, []
    warnings = [NLP_WARNING] if NLP_WARNING else []
    units = parsed_document['units'] if parsed_document else [{'kind': 'text', 'text': text}]
    
    # 1. Structured Calls
    calls = extract_calls(units, lambda label, kind: entity(label, kind, scope=scope))
    entities.update({e['id']: e for e in calls['entities']})
    mentions.extend(calls['mentions'])
    warnings.extend(calls['warnings'])
    
    # 2. Structured Bank Transactions
    bank = extract_bank_transactions(units, lambda label, kind: entity(label, kind, scope=scope))
    entities.update({e['id']: e for e in bank['entities']})
    mentions.extend(bank['mentions'])
    warnings.extend(bank['warnings'])
    
    # 3. Structured Registry / Event CSVs (accounts, kyc, vehicles, cyber, emails, etc.)
    registry = extract_registry(units, lambda label, kind: entity(label, kind, scope=scope))
    entities.update({e['id']: e for e in registry['entities']})
    mentions.extend(registry['mentions'])
    warnings.extend(registry['warnings'])

    # 4. Structured FIR Form & Entities
    fir = extract_fir_structure(text, scope=scope)
    entities.update({e['id']: e for e in fir['entities']})
    warnings.extend(fir['warnings'])
    
    combined_handled = calls['handled'].union(bank['handled']).union(registry['handled'])
    
    def add(label, kind, method, unit_index, location, start=None, end=None, confidence=None):
        if not is_valid_entity(label, kind):
            return
        item = entity(label, kind, confidence, scope)
        entities.setdefault(item['id'], item)
        mentions.append({'entityId': item['id'], 'label': label, 'type': kind,
                         'method': method, 'unitIndex': unit_index, 'location': location,
                         'start': start, 'end': end,
                         'snippetStart': max(0, (start or 0) - 100),
                         'snippet': unit_text[max(0, (start or 0) - 100):(end or 0) + 100],
                         'modelVersion': NLP.meta.get('version') if method == 'spacy-ner' else None})
                         
    for index, unit in enumerate(units):
        if index in combined_handled:
            continue
        unit_text = ' | '.join(unit['cells']) if unit['kind'] == 'row' else unit['text']
        location = {k: unit[k] for k in ('page_number', 'block_number', 'row_number', 'line_number', 'sheet') if k in unit}
        for kind, pattern in PATTERNS:
            for match in re.finditer(pattern, unit_text, re.I):
                group = 1 if match.lastindex else 0
                add(match.group(group), kind, 'identifier-rule', index, location,
                    *match.span(group))
        clean_text, offset_map = nlp_text_with_offsets(unit_text)
        for offset in range(0, len(clean_text), 50000):
            for found in NLP(clean_text[offset:offset + 50000]).ents:
                kind = KINDS.get(found.label_)
                if kind:
                    start = offset_map[found.start_char + offset]
                    end = offset_map[found.end_char + offset - 1] + 1
                    raw_ent = unit_text[start:end]
                    add(raw_ent, kind, 'spacy-ner', index, location, start, end)
                    
    mentions = list({(m['entityId'], m['unitIndex'], m['start'], m['end'], m['method']): m for m in mentions}.values())
    accumulated_rels = calls['relationships'] + bank['relationships'] + registry['relationships'] + fir['relationships']
    relation_result = build_relationships(units, list(entities.values()), mentions, call_relationships=accumulated_rels)
    relations = relation_result['relationships']
    warnings.extend(relation_result['warnings'])
    if not relations and relation_result['relationshipStatus']['complete']:
        warnings.append('Entities extracted; no explicit relationships validated. Co-occurrence does not establish a relationship.')
    if parsed_document and parsed_document['kind'] == 'table' and any(u['kind'] == 'row' and i not in combined_handled for i, u in enumerate(units)):
        warnings.append('Unrecognized table columns need a source mapping; automatic call/bank mapping requires standard headers.')
    mentions = list({(m['entityId'], m['unitIndex'], m['start'], m['end'], m['method']): m for m in mentions}.values())
    return {'entities': list(entities.values()), 'mentions': mentions,
            'extractionVersion': get_extraction_version(),
            'relationships': relations, 'warnings': list(dict.fromkeys(warnings)), 'nlp': nlp_status(),
            'relationshipStatus': relation_result['relationshipStatus'],
            'engine': ('spaCy + ' if not NLP_WARNING else '') + 'identifier rules; ' + relation_result['relationshipStatus']['mode'] + ' relationships, FIR parser, and structured column mappers',
            'llmUsed': relation_result['relationshipStatus']['attempted'] > 0}
