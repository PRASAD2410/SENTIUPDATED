"""Apply editable language rules to all extracted entity spans, never fixed names."""
import hashlib
import json
import re
from pathlib import Path

VERSION = 'regex-relations-v3'
RULES_PATH = Path(__file__).with_name('relationship_rules.json')
UNSAFE = re.compile(r"\b(?:not|never|no|denied|denies|alleged|allegedly|might|may|could|if|said|says|claimed|claims|whether|didn't|doesn't|wasn't|isn't|cannot|can't)\b", re.I)
ATTRIBUTION = re.compile(r'\b(?:said|says|claimed|claims|stated|submitted|reported|alleged|allegedly)\b', re.I)
NEGATED = re.compile(r"\b(?:not|never|denied|denies|might|may|could|if|whether|didn't|doesn't|wasn't|isn't|cannot|can't)\b", re.I)
ASSET = r'(?:the\s+)?(?:mobile\s+|telephone\s+)?(?:phone|vehicle|account|a/c|IMEI)(?:\s+(?:number|no\.?))?\s*[:#-]?\s*'
ABBREVIATIONS = {'mr', 'mrs', 'ms', 'dr', 'shri', 'smt', 'rs', 'no', 'vs', 'v', 'st', 'prof'}
MONTH_DAY = r'(?:january|february|march|april|may|june|july|august|september|october|november|december|monday|tuesday|wednesday|thursday|friday|saturday|sunday|today|yesterday|morning|afternoon|evening|night|noon|midnight)'
TIME_TOKEN = rf'(?:\d{{1,4}}(?:[-/.]\d{{1,4}}){{0,2}}|\d{{1,2}}:\d{{2}}(?::\d{{2}})?|am|pm|{MONTH_DAY}|the|of)'
TEMPORAL_PREFIX = re.compile(rf'(?:on|at|during|in|before|after)\s+{TIME_TOKEN}(?:\s+{TIME_TOKEN})*\s*[,;:]?\s+', re.I)
DAY_PREFIX = re.compile(r'(?:today|yesterday|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s*[,;:]\s+', re.I)
SOURCE_NOUN = r'(?:records?|call\s+(?:logs?|records?)|reports?|witness|complainant|investigator|officer|statement|FIR|evidence|document)'
REPORT_PREFIX = re.compile(rf'(?:(?:the\s+)?{SOURCE_NOUN}\s+(?:show(?:ed|s)?|indicate(?:d|s)?|state(?:d|s)?|report(?:ed|s)?|record(?:ed|s)?|confirm(?:ed|s)?|say|says|said|claimed|claims|submitted)\s+(?:that\s+)?|according\s+to\s+(?:the\s+)?{SOURCE_NOUN}\s*[,;:]?\s+)', re.I)
ROLE_PREFIX = re.compile(r'(?:the\s+)?(?:accused|suspect|witness|victim|complainant|officer)\s+', re.I)
CLAUSE_BOUNDARY = re.compile(r';|,\s*(?:and|but|while|whereas)\s+', re.I)
FOLLOWING_CLAUSE = re.compile(r';|,?\s+(?:and|but|while|whereas)\b', re.I)
FOLLOWING_QUALIFIER = re.compile(r'\s*[,;]?\s*(?:and|but)\s+(?:(?:this|that|it|the\s+(?:call|contact|meeting|statement))\b|(?:allegedly|may|might|could|denied|denies)\b)', re.I)
UNCONFIRMED = re.compile(r'\b(?:unconfirmed|unverified|disputed|uncertain|false)\b', re.I)
IDENTIFIER_LABEL = re.compile(r'\b((?:mobile\s+|telephone\s+)?(?:phone|vehicle|account|a/c|IMEI))\s+(?:number|no\.?)\s*[:#-]?\s*', re.I)


def prefix_context(prefix, earlier_mentions, prefix_start=0):
    """Recognize limited adjuncts; never discard an earlier named subject.

    Dates and source-attribution boilerplate often precede a real subject in
    FIRs. Treating all such prefixes as nested clauses hid otherwise explicit
    connectors. A second person/asset before the subject still needs parsing.
    """
    remaining, reported = prefix, False
    for _ in range(4):
        match = TEMPORAL_PREFIX.match(remaining) or DAY_PREFIX.match(remaining) or REPORT_PREFIX.match(remaining) or ROLE_PREFIX.match(remaining)
        if not match:
            break
        reported |= bool(REPORT_PREFIX.fullmatch(match.group()))
        remaining = remaining[match.end():]
    safe = not remaining.strip() or bool(re.fullmatch(ASSET, remaining.strip(), re.I))
    # NER may call "FIR" an organization or a weekday a person. Those spans
    # were already consumed by an explicit boilerplate grammar. Named or
    # coordinated subjects outside that grammar must still be rejected.
    consumed_end = prefix_start + len(prefix) - len(remaining)
    safe &= not any(m['type'] not in {'Date', 'Time'} and m['end'] > consumed_end
                    for m in earlier_mentions)
    return safe, reported


def connector_variants(gap):
    # "phone no." is an identifier label, not a negation. Keep the exact gap
    # first so custom rules still see the unmodified source wording.
    return gap, IDENTIFIER_LABEL.sub(lambda m: m.group(1) + ' ', gap)


def load_rules(path=None):
    """Reload configuration on each extraction, so edits need no code change."""
    definitions = json.loads(Path(path or RULES_PATH).read_text(encoding='utf-8'))
    rules = []
    for item in definitions:
        if not re.fullmatch(r'[A-Z][A-Z0-9_]*', item['type']):
            raise ValueError('Relationship type must be an uppercase identifier.')
        rules.append({**item, 'compiled': re.compile(item['pattern'], re.I)})
    return rules


def allowed(kind, specification):
    return specification == '*' or kind in specification


def sentences(text):
    # Preserve offsets; ordinary PDF line wraps do not end sentences.
    start = 0
    for boundary in re.finditer(r'[.!?](?=\s|$)|\n\s*\n', text):
        if boundary.group() == '.':
            token = re.search(r'([A-Za-z]+)$', text[:boundary.start()])
            if token and (token.group(1).lower() in ABBREVIATIONS or len(token.group(1)) == 1):
                continue
        yield start, boundary.end()
        start = boundary.end()
    if start < len(text):
        yield start, len(text)


def extract_relationships(units, mentions):
    rules = load_rules()
    relationships = {}
    for index, unit in enumerate(units):
        if unit['kind'] == 'row':
            continue  # Table relationships require explicit column mapping.
        text = unit['text']
        anchors = list({(m['entityId'], m['start'], m['end']): m for m in mentions
                        if m['unitIndex'] == index and m['start'] is not None}.values())
        # Exact identifier rules take precedence over overlapping NER guesses
        # (for example spaCy labelling "Phone 987..." an organization).
        identifiers = [m for m in anchors if m.get('method') == 'identifier-rule']
        anchors = [m for m in anchors if m.get('method') == 'identifier-rule' or not any(
            m['start'] < p['end'] and p['start'] < m['end'] for p in identifiers)]
        for sentence_start, sentence_end in sentences(text):
            sentence_text = text[sentence_start:sentence_end]
            local = sorted((m for m in anchors if sentence_start <= m['start'] and m['end'] <= sentence_end), key=lambda m: m['start'])
            for source in local:
                clause_start = sentence_start
                for boundary in CLAUSE_BOUNDARY.finditer(text, sentence_start, source['start']):
                    clause_start = boundary.end()
                prefix = text[clause_start:source['start']]
                earlier = [m for m in local if clause_start <= m['start'] and m['end'] <= source['start']]
                safe_prefix, reported_prefix = prefix_context(prefix, earlier, clause_start)
                embedded = not safe_prefix
                for target in local:
                    if source['end'] >= target['start'] or source['entityId'] == target['entityId']:
                        continue
                    gap = text[source['end']:target['start']]
                    tail = text[target['end']:sentence_end]
                    next_clause = FOLLOWING_CLAUSE.search(tail)
                    qualifier = bool(next_clause and FOLLOWING_QUALIFIER.match(tail[next_clause.start():]))
                    if next_clause and not qualifier:
                        tail = tail[:next_clause.start()]
                    # Check the relation's clause, not an unrelated later
                    # action. Prefixes we explicitly recognize contain no
                    # negative assertion (May is also a valid month).
                    context = ('' if safe_prefix else prefix) + gap + tail
                    context = IDENTIFIER_LABEL.sub(lambda m: m.group(1) + ' ', context)
                    for rule in rules:
                        if qualifier and UNCONFIRMED.search(tail):
                            continue
                        if rule.get('allowEmbedded', False):
                            if NEGATED.search(context):
                                continue
                        elif embedded or UNSAFE.search(context):
                            continue
                        if not allowed(source['type'], rule.get('sourceTypes', '*')) or not allowed(target['type'], rule.get('targetTypes', '*')):
                            continue
                        match = next((m for variant in connector_variants(gap)
                                      if (m := rule['compiled'].fullmatch(variant))), None)
                        if not match:
                            continue
                        start, end = source['start'], target['end']
                        kind = rule['type']
                        key = f'{index}:{start}:{end}:{kind}:{source["entityId"]}:{target["entityId"]}'
                        relationship = {
                            'id': 'rel:' + hashlib.sha256(key.encode()).hexdigest()[:24],
                            'source': source['entityId'], 'target': target['entityId'],
                            'type': kind, 'origin': 'reported' if reported_prefix or ATTRIBUTION.search(prefix + gap + tail) else 'asserted', 'reviewStatus': 'pending',
                            'method': 'regex-rule', 'extractorVersion': VERSION,
                            'ruleId': rule['id'], 'unitIndex': index,
                            'location': source['location'], 'start': start, 'end': end,
                            'evidenceText': text[start:end],
                            'sentenceContext': sentence_text.strip(),
                            'confidence': 0.85, 'confidenceKind': 'heuristic, not calibrated',
                        }
                        values = match.groupdict()
                        if values.get('amount'):
                            relationship['amount'] = values['amount'].replace(',', '')
                            relationship['currency'] = 'INR'
                        relationships[key] = relationship
    return list(relationships.values())
