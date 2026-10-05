"""Evidence-checked Gemini relationships between already extracted entities.

This module never creates entities. Source-unit offsets and quotes are checked
locally before a model proposal can become a stored relationship.
"""
import hashlib
import os
import re

from .llm import RELATIONSHIP_TYPES
from .relations import sentences
from .relationship_context import plan_context

VERSION = 'gemini-relations-v2'
CHUNK_SIZE = 10000
CHUNK_OVERLAP = 1000
LOCATION_FIELDS = ('page_number', 'block_number', 'row_number', 'line_number', 'sheet')
NEGATED = re.compile(
    r"\b(?:not|never|denied|denies|didn't|doesn't|wasn't|weren't|isn't|aren't|"
    r"cannot|can't|couldn't|hasn't|haven't|hadn't|won't|wouldn't)\b|"
    r'\bno\s+(?:evidence|connection|contact|relationship|meeting|call)\b', re.I)
UNCERTAIN = re.compile(
    r'\b(?:might|could|whether|if|unclear|uncertain|unconfirmed|unverified|disputed)\b|'
    r'\bmay\s+(?:have|be|call|contact|meet|use|own|transfer|live|work|travel)\b', re.I)
ATTRIBUTED = re.compile(
    r'\b(?:said|says|claimed|claims|stated|submitted|reported|alleged|allegedly|'
    r'testified|testifies|according\s+to)\b', re.I)
RELATED_CONTEXT = re.compile(
    r'\b(?:this|that|the)\s+(?:claim|allegation|statement|account|report|assertion|call|meeting|contact|relationship)\b', re.I)
SOURCE_PREFIX = re.compile(
    r'^\s*According\s+to\b[^.!?]{0,180}\b(?:statement|testimony|report|complaint|account)\s*[.:]?\s*$', re.I)


def _normalized_with_offsets(text):
    """Collapse only whitespace, retaining every source character's offset."""
    characters, offsets = [], []
    previous_end = 0
    for token in re.finditer(r'\S+', text):
        if characters:
            characters.append(' ')
            offsets.append(previous_end)
        characters.extend(token.group())
        offsets.extend(range(token.start(), token.end()))
        previous_end = token.end()
    return ''.join(characters), offsets


def _chunks(text):
    """Yield bounded source slices, overlapping to retain boundary relations."""
    start = 0
    while start < len(text):
        end = min(start + CHUNK_SIZE, len(text))
        clipped_sentence = False
        if end < len(text):
            # Prefer a complete sentence near the size limit. A single very
            # long sentence still needs bounded slices and an explicit warning.
            boundaries = [m.end() for m in re.compile(
                r'[.!?](?:\s+|$)|\n\s*\n').finditer(text,
                max(start + 1, end - CHUNK_OVERLAP), end)]
            if boundaries:
                end = boundaries[-1]
            else:
                clipped_sentence = True
        yield start, end, clipped_sentence
        if end == len(text):
            break
        start = max(start + 1, end - CHUNK_OVERLAP)


def _context(text, start, end):
    bounds = list(sentences(text))
    covered = [index for index, (left, right) in enumerate(bounds)
               if left < end and start < right]
    if not covered:
        return text[start:end]
    left, right = covered[0], covered[-1]
    # Keep adjacent qualifiers that explicitly refer back to this statement.
    # An unrelated neighbouring denial must not erase an affirmative event.
    if left:
        previous = text[bounds[left - 1][0]:bounds[left - 1][1]]
        if RELATED_CONTEXT.search(previous) or SOURCE_PREFIX.fullmatch(previous):
            left -= 1
    if right + 1 < len(bounds):
        following = text[bounds[right + 1][0]:bounds[right + 1][1]]
        if RELATED_CONTEXT.search(following):
            right += 1
    return text[bounds[left][0]:bounds[right][1]].strip()


def _valid_mentions(mentions, unit_index, text_length, known):
    result, stale = [], 0
    for item in mentions:
        if (not isinstance(item, dict) or item.get('unitIndex') != unit_index or
                not isinstance(item.get('entityId'), str) or item['entityId'] not in known):
            continue
        start, end = item.get('start'), item.get('end')
        if (isinstance(start, int) and not isinstance(start, bool) and
                isinstance(end, int) and not isinstance(end, bool) and
                0 <= start < end <= text_length):
            result.append(item)
        else:
            stale += 1
    return result, stale


def extract_gemini_relationships(units, entities, mentions, provider):
    """Return only existing-ID relationships supported by an actual quote.

    ``failed`` covers incomplete provider/chunk processing. Callers can preserve
    a previous saved analysis rather than replace it with a partial result.
    Validation rejections are visible warnings, not silently accepted facts.
    """
    known = {item['id']: item for item in entities
             if isinstance(item, dict) and isinstance(item.get('id'), str) and item['id']}
    output = {'relationships': [], 'warnings': [], 'attempted': 0, 'succeeded': 0, 'failed': False}
    try:
        maximum = int(os.getenv('GEMINI_MAX_RELATIONSHIP_CHUNKS', '40'))
        if maximum < 1:
            raise ValueError
    except (TypeError, ValueError):
        maximum = 40
        output['warnings'].append('Invalid GEMINI_MAX_RELATIONSHIP_CHUNKS; using the default limit of 40.')
    relationships = {}
    rejected = 0

    def finish():
        output['relationships'] = list(relationships.values())
        if rejected:
            output['warnings'].append(f'{rejected} Gemini relationship proposals were rejected by source-evidence validation.')
        return output

    # A relationship quote must point to the actual locally extracted mention,
    # not merely to a plausible offset in a reparsed document. Check every
    # narrative anchor before sending any chunk so stale stored spans cannot
    # produce wrong existing-ID edges or replace a prior saved analysis.
    anchors_by_unit = {}
    stale_units = set()
    invalid_unit_index = False
    for mention in mentions:
        if (not isinstance(mention, dict) or not isinstance(mention.get('entityId'), str) or
                mention['entityId'] not in known):
            continue
        index = mention.get('unitIndex')
        if (not isinstance(index, int) or isinstance(index, bool) or
                not 0 <= index < len(units)):
            invalid_unit_index = True
    for unit_index, unit in enumerate(units):
        if unit.get('kind') == 'row':
            continue
        text = unit.get('text', '')
        if not isinstance(text, str):
            text = ''
        candidates, stale = _valid_mentions(mentions, unit_index, len(text), known)
        anchors = []
        for anchor in candidates:
            label = anchor.get('label')
            source_label = text[anchor['start']:anchor['end']]
            if (not isinstance(label, str) or not label.strip() or
                    ' '.join(source_label.split()) != ' '.join(label.split())):
                stale += 1
            else:
                anchors.append(anchor)
        anchors_by_unit[unit_index] = anchors
        if stale:
            stale_units.add(unit_index)
    if invalid_unit_index or stale_units:
        output['failed'] = True
        source_detail = (' in source units ' + ', '.join(str(index + 1) for index in sorted(stale_units)[:5])) if stale_units else ''
        output['warnings'].append(
            'Stored entity mentions no longer match the source text' + source_detail + '. '
            'Relationship analysis is incomplete. Re-extract the original document to refresh entity mentions before retrying.')
        return finish()

    compact = os.getenv('GEMINI_COMPACT_CONTEXT', 'true').strip().lower() not in {'false', '0', 'no', 'off'}
    plan = plan_context(units, anchors_by_unit, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP, compact=compact)
    output['input'] = plan['metrics']
    output['input']['sentChars'] = sum(len(' '.join(passage['text'].split()))
                                     for batch in plan['requests'] for passage in batch)
    output['warnings'].extend(plan['warnings'])
    if any(passage['clipped'] for batch in plan['requests'] for passage in batch):
        output['warnings'].append('A source sentence is longer than the chunk window; '
                                  'overlap is retained, but distant relationships in that sentence may be missed.')
    for batch_number, passages in enumerate(plan['requests'], 1):
        if getattr(provider, 'available', None) is False:
            output['failed'] = True
            output['warnings'].append(
                'Gemini relationship extraction is not configured: the API key is missing. '
                'Set GEMINI_API_KEY before analyzing narrative relationships.')
            return finish()
        if output['attempted'] >= maximum:
            output['failed'] = True
            output['warnings'].append(
                f'Gemini relationship analysis is incomplete: the limit of {maximum} requests was reached. '
                'Increase GEMINI_MAX_RELATIONSHIP_CHUNKS to analyze the remaining source text.')
            return finish()
        local = [anchor for passage in passages for anchor in passage['anchors']]
        local_ids = {anchor['entityId'] for anchor in local}
        supplied = []
        for entity_id in sorted(local_ids):
            item = known[entity_id]
            supplied.append({'id': entity_id, 'label': item.get('label', ''),
                             'type': item.get('type', ''),
                             'aliases': sorted({anchor.get('label', '') for anchor in local
                                                if anchor['entityId'] == entity_id and anchor.get('label')})})
        # Disjoint excerpts are visibly separated. A model quote must match one
        # original contiguous passage below, never a synthetic join across gaps.
        source = '\n\n'.join(
            (f'[PASSAGE {passage["unitIndex"] + 1}:{passage["start"]}]\n' if len(passages) > 1 else '')
            + ' '.join(passage['text'].split()) for passage in passages)
        output['attempted'] += 1
        unexpected_exception = False
        try:
            answer = provider.extract_relationships(source, supplied)
        except Exception:
            answer = None
            unexpected_exception = True
        if not isinstance(answer, dict) or not isinstance(answer.get('relationships'), list):
            output['failed'] = True
            first_unit = passages[0]['unitIndex'] + 1
            warning = (f'Gemini relationship extraction failed for request {batch_number} '
                       f'(starting at source unit {first_unit}). '
                       'Check the Gemini configuration or retry; this analysis is incomplete.')
            detail = getattr(provider, 'last_error', None)
            if not unexpected_exception and isinstance(detail, str) and detail.strip():
                warning += ' ' + detail.strip()[:280]
            output['warnings'].append(warning)
            return finish()
        output['succeeded'] += 1
        for proposal in answer['relationships']:
            if not isinstance(proposal, dict):
                rejected += 1
                continue
            source, target, kind = proposal.get('source'), proposal.get('target'), proposal.get('type')
            quote, origin = proposal.get('evidenceText'), proposal.get('origin', 'asserted')
            if (not isinstance(source, str) or not isinstance(target, str) or
                    source not in local_ids or target not in local_ids or source == target or
                    not isinstance(kind, str) or kind not in RELATIONSHIP_TYPES or
                    not isinstance(origin, str) or origin not in {'asserted', 'reported'} or
                    not isinstance(quote, str) or not quote.strip()):
                rejected += 1
                continue
            normalized_quote = ' '.join(quote.split())
            validated = []
            for passage in passages:
                unit_index, chunk_start = passage['unitIndex'], passage['start']
                text = units[unit_index]['text']
                anchors = passage['anchors']
                normalized, offsets = _normalized_with_offsets(passage['text'])
                for match in re.finditer(re.escape(normalized_quote), normalized):
                    start = chunk_start + offsets[match.start()]
                    end = chunk_start + offsets[match.end() - 1] + 1
                    covered = {anchor['entityId'] for anchor in anchors
                               if start <= anchor['start'] and anchor['end'] <= end}
                    if source not in covered or target not in covered:
                        continue
                    context = _context(text, start, end)
                    safety_context = context.replace('\u2019', "'").replace('\u2018', "'")
                    if NEGATED.search(safety_context) or UNCERTAIN.search(safety_context):
                        continue
                    source_anchor = min((anchor for anchor in anchors
                                         if anchor['entityId'] == source and start <= anchor['start'] and anchor['end'] <= end),
                                        key=lambda anchor: (anchor['start'], anchor['end']))
                    target_anchor = min((anchor for anchor in anchors
                                         if anchor['entityId'] == target and start <= anchor['start'] and anchor['end'] <= end),
                                        key=lambda anchor: (anchor['start'], anchor['end']))
                    validated.append((unit_index, start, end, context, source_anchor, target_anchor))
            if not validated:
                rejected += 1
                continue
            for unit_index, start, end, context, source_anchor, target_anchor in validated:
                text, unit = units[unit_index]['text'], units[unit_index]
                key = (f'{unit_index}:{source_anchor["start"]}:{source_anchor["end"]}:'
                       f'{target_anchor["start"]}:{target_anchor["end"]}:{kind}:{source}:{target}')
                reported = (origin == 'reported' or ATTRIBUTED.search(context) or
                            relationships.get(key, {}).get('origin') == 'reported')
                previous = relationships.get(key)
                if previous and (previous['end'] - previous['start'], previous['start']) <= (end - start, start):
                    if reported:
                        previous['origin'] = 'reported'
                    continue
                relationships[key] = {
                    'id': 'rel:' + hashlib.sha256(key.encode()).hexdigest()[:24],
                    'source': source, 'target': target, 'type': kind,
                    'origin': 'reported' if reported else 'asserted',
                    'reviewStatus': 'pending', 'method': 'gemini-relationship',
                    'extractorVersion': VERSION, 'modelVersion': getattr(provider, 'model', None),
                    'unitIndex': unit_index,
                    'location': {key: unit[key] for key in LOCATION_FIELDS if key in unit},
                    'start': start, 'end': end, 'evidenceText': text[start:end], 'sentenceContext': context,
                }
    return finish()
