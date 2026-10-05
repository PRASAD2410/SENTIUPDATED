"""Plan exact source passages for relationship extraction without rewriting text.

Compact context keeps entity-bearing sentences and their immediate neighbours.
Each passage retains its own source offsets; separate passages must be labelled
separately by the provider, never presented as one continuous source quotation.
"""
import bisect
import re

from .relations import sentences


MARKER_CHARS = 80
CHUNK_BOUNDARY = re.compile(r'[.!?](?:\s+|$)|\n\s*\n')


def _chunks(text, chunk_size, overlap):
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        clipped = False
        if end < len(text):
            boundaries = [match.end() for match in CHUNK_BOUNDARY.finditer(
                text, max(start + 1, end - overlap), end)]
            if boundaries:
                end = boundaries[-1]
            else:
                clipped = True
        yield start, end, clipped
        if end == len(text):
            break
        start = max(start + 1, end - overlap)


def _contained(anchors, start, end):
    return [anchor for anchor in anchors
            if start <= anchor['start'] and anchor['end'] <= end]


def _ids(segments):
    return {anchor['entityId'] for segment in segments
            for anchor in segment['anchors']}


def _segment(unit_index, text, anchors, start, end, clipped=False):
    return {'unitIndex': unit_index, 'start': start, 'end': end,
            'text': text[start:end], 'anchors': _contained(anchors, start, end),
            'clipped': clipped}


def _windows(text, anchors):
    bounds = list(sentences(text))
    if not bounds:
        return []
    starts = [start for start, _ in bounds]
    ends = [end for _, end in bounds]
    selected = set()
    for anchor in anchors:
        # Include every sentence crossed by a mention, not just the sentence
        # containing its first character. This preserves wrapped PDF names.
        first = bisect.bisect_right(ends, anchor['start'])
        last = bisect.bisect_left(starts, anchor['end']) - 1
        for index in range(max(0, first - 1), min(len(bounds), last + 2)):
            selected.add(index)
    ranges = []
    for index in sorted(selected):
        start, end = bounds[index]
        if ranges and start <= ranges[-1][1]:
            ranges[-1] = (ranges[-1][0], max(ranges[-1][1], end))
        else:
            ranges.append((start, end))
    return ranges


def _pack(segments, budget, marker_chars):
    batches, current, size = [], [], 0
    for segment in segments:
        cost = len(segment['text']) + marker_chars
        if current and size + cost > budget:
            batches.append(current)
            current, size = [], 0
        current.append(segment)
        size += cost
    if current:
        batches.append(current)
    return batches


def plan_context(units, anchors_by_unit, *, chunk_size=10000, overlap=1000, compact=True):
    """Return bounded batches of independently anchored, unmodified passages.

    The baseline is the previous eligible full-source chunks (at least two
    existing IDs). Compact planning never increases that request count. When
    passage markers or sentence boundaries would expand it, the exact original
    chunks are retained instead. No document/request cap is applied here.
    """
    if not isinstance(chunk_size, int) or isinstance(chunk_size, bool) or chunk_size < 2:
        raise ValueError('chunk_size must be an integer of at least 2')
    if not isinstance(overlap, int) or isinstance(overlap, bool) or overlap < 0:
        raise ValueError('overlap must be a non-negative integer')
    overlap = min(overlap, chunk_size - 1)
    originals = []
    eligible_units = {}
    for unit_index, unit in enumerate(units):
        if unit.get('kind') == 'row':
            continue
        text = unit.get('text', '')
        if not isinstance(text, str) or not text.strip():
            continue
        anchors = anchors_by_unit.get(unit_index, [])
        found = False
        for start, end, clipped in _chunks(text, chunk_size, overlap):
            segment = _segment(unit_index, text, anchors, start, end, clipped)
            if len(_ids([segment])) >= 2:
                originals.append([segment])
                found = True
        if found:
            eligible_units[unit_index] = (text, anchors)

    original_chars = sum(len(segment['text']) for request in originals for segment in request)
    requests, warnings, mode = originals, [], 'full-context'
    if compact and originals:
        # Leave room for passage labels without changing source text. Small
        # test/configured windows receive a proportionally smaller allowance.
        marker_chars = min(MARKER_CHARS, max(1, chunk_size // 10))
        passage_size = chunk_size - marker_chars
        passage_overlap = min(overlap, passage_size - 1)
        segments = []
        retained_ranges = {}
        for unit_index, (text, anchors) in eligible_units.items():
            windows = _windows(text, anchors)
            retained_ranges[unit_index] = windows
            for left, right in windows:
                for start, end, clipped in _chunks(text[left:right], passage_size, passage_overlap):
                    segments.append(_segment(unit_index, text, anchors,
                                             left + start, left + end, clipped))
        batches = _pack(segments, chunk_size, marker_chars)
        eligible_batches = [batch for batch in batches if len(_ids(batch)) >= 2]
        sent_chars = sum(len(segment['text']) for batch in eligible_batches for segment in batch)
        if (not eligible_batches or len(eligible_batches) < len(batches) or
                len(eligible_batches) > len(originals) or
                sent_chars > original_chars):
            warnings.append('Compact context would expand requests or omit entity context; '
                            'the original source chunks were retained.')
        else:
            requests, mode = eligible_batches, 'entity-context'
            trimmed = any(sum(right - left for left, right in retained_ranges[index]) < len(text)
                          for index, (text, _) in eligible_units.items())
            if trimmed:
                warnings.append('Compact context keeps entity sentences and neighbouring sentences. '
                                'Relationships requiring more distant context may be missed; '
                                'use full-context analysis when needed.')
    metrics = {'originalChars': original_chars,
               'sentChars': sum(len(segment['text']) for request in requests for segment in request),
               'originalRequests': len(originals), 'plannedRequests': len(requests),
               'passageCount': sum(len(request) for request in requests), 'mode': mode}
    return {'requests': requests, 'metrics': metrics, 'warnings': warnings}
