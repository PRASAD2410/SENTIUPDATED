"""Entity mentions from source units; identifiers use rules, narrative uses NER."""
import hashlib
import os
import re
import unicodedata
from .nlp import NLP, NLP_WARNING, nlp_status
from .llm import get_llm_provider
from .relations import extract_relationships, VERSION as RELATIONSHIP_VERSION
from .structured_calls import extract_calls, VERSION as CALL_VERSION

def get_extraction_version():
    from .gemini_relations import VERSION as GEMINI_VERSION
    mode = os.getenv('RELATIONSHIP_EXTRACTOR', 'regex').strip().lower()
    model = os.getenv('GEMINI_MODEL', 'default') if mode == 'gemini' else ''
    compact = os.getenv('GEMINI_COMPACT_CONTEXT', 'true').strip().lower() not in {'false', '0', 'no', 'off'}
    return f'source-v3:spacy-entities:{RELATIONSHIP_VERSION}:{CALL_VERSION}:{GEMINI_VERSION}:{mode}:{model}:compact={compact}'


EXTRACTION_VERSION = get_extraction_version()


class RelationshipExtractionError(RuntimeError):
    """Retryable relationship provider failure; existing findings stay intact."""


def build_relationships(units, entities, mentions, provider=None):
    mode = os.getenv('RELATIONSHIP_EXTRACTOR', 'regex').strip().lower()
    if mode not in {'regex', 'gemini'}:
        raise ValueError('RELATIONSHIP_EXTRACTOR must be regex or gemini.')
    calls = extract_calls(units, entity)
    warnings = list(calls['warnings'])
    status = {'mode': mode, 'attempted': 0, 'succeeded': 0, 'complete': True}
    relationships = list(calls['relationships'])
    if mode == 'gemini':
        from .gemini_relations import extract_gemini_relationships
        result = extract_gemini_relationships(units, entities, mentions, provider or get_llm_provider())
        relationships.extend(result['relationships'])
        warnings.extend(result['warnings'])
        status.update(attempted=result['attempted'], succeeded=result['succeeded'], complete=not result.get('failed', False))
        if result.get('input') is not None:
            status['input'] = result['input']
    else:
        relationships.extend(extract_relationships(units, mentions))
    return {'relationships': relationships, 'warnings': warnings, 'relationshipStatus': status}


PATTERNS = [
    ('Phone', r'(?<!\w)(?:\+91[- ]?|0)?[6-9]\d{9}\b'),
    ('Vehicle', r'\b[A-Z]{2}[- ]?\d{1,2}[- ]?[A-Z]{1,3}[- ]?\d{4}\b'),
    ('Account', r'(?i)\b(?:account(?:\s*(?:number|no\.?))?|a/c)\s*[:#-]?\s*(\d{9,18})\b'),
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
    clean = label.strip().strip('â€¢-*_~`#()[]{}|/\\:;,."\'')
    if not clean:
        return False
    if kind in {'Phone', 'Vehicle', 'Account', 'IMEI'}:
        return len(clean) >= 4
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
        words = clean.split()
        if len(words) == 1 and (len(clean) < 3 or clean.islower()):
            if clean_lower in BOILERPLATE or clean_lower in STOPWORDS:
                return False
    if kind == 'Organization':
        if len(clean) < 2 or clean_lower in BOILERPLATE:
            return False
    return True

def normalized(label, kind):
    value = unicodedata.normalize('NFKC', label).strip()
    if kind in {'Phone', 'Account', 'IMEI'}:
        value = re.sub(r'\D', '', value)
        if kind == 'Phone':
            if len(value) == 12 and value.startswith('91'):
                value = value[2:]
            elif len(value) == 11 and value.startswith('0'):
                value = value[1:]
        return value
    if kind == 'Vehicle':
        return re.sub(r'[^A-Z0-9]', '', value.upper())
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
    calls = extract_calls(units, lambda label, kind: entity(label, kind, scope=scope))
    entities.update({e['id']: e for e in calls['entities']})
    mentions.extend(calls['mentions'])
    warnings.extend(calls['warnings'])
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
        if index in calls['handled']:
            continue
        unit_text = ' | '.join(unit['cells']) if unit['kind'] == 'row' else unit['text']
        location = {k: unit[k] for k in ('page_number', 'block_number', 'row_number', 'line_number', 'sheet') if k in unit}
        for kind, pattern in PATTERNS:
            for match in re.finditer(pattern, unit_text, re.I):
                group = 1 if match.lastindex else 0
                add(match.group(group), kind, 'identifier-rule', index, location,
                    *match.span(group))
        # Process a bounded chunk at a time for long text. Offsets are local to
        # the complete source unit, not the chunk.
        clean_text, offset_map = nlp_text_with_offsets(unit_text)
        for offset in range(0, len(clean_text), 50000):
            for found in NLP(clean_text[offset:offset + 50000]).ents:
                kind = KINDS.get(found.label_)
                if kind:
                    start = offset_map[found.start_char + offset]
                    end = offset_map[found.end_char + offset - 1] + 1
                    raw_ent = unit_text[start:end]
                    add(raw_ent, kind, 'spacy-ner', index, location, start, end)
    # Entity extraction ends here. Gemini receives these fixed IDs and cannot
    # create or reclassify entities.
    mentions = list({(m['entityId'], m['unitIndex'], m['start'], m['end'], m['method']): m for m in mentions}.values())
    relation_result = build_relationships(units, list(entities.values()), mentions)
    relations = relation_result['relationships']
    warnings.extend(relation_result['warnings'])
    if not relations and relation_result['relationshipStatus']['complete']:
        warnings.append('Entities extracted; no explicit relationships validated. Co-occurrence does not establish a relationship.')
    if parsed_document and parsed_document['kind'] == 'table' and any(u['kind'] == 'row' and i not in calls['handled'] for i, u in enumerate(units)):
        warnings.append('Unrecognized table columns need a source mapping; automatic call mapping requires caller and receiver phone columns.')
    # Duplicate methods may detect the same occurrence; keep methods separate.
    mentions = list({(m['entityId'], m['unitIndex'], m['start'], m['end'], m['method']): m for m in mentions}.values())
    return {'entities': list(entities.values()), 'mentions': mentions,
            'extractionVersion': get_extraction_version(),
            'relationships': relations, 'warnings': list(dict.fromkeys(warnings)), 'nlp': nlp_status(),
            'relationshipStatus': relation_result['relationshipStatus'],
            'engine': ('spaCy + ' if not NLP_WARNING else '') + 'identifier rules; ' + relation_result['relationshipStatus']['mode'] + ' relationships and structured call columns',
            'llmUsed': relation_result['relationshipStatus']['attempted'] > 0}
