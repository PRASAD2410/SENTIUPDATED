"""Header-driven call evidence; column roles, never particular phone values."""
import hashlib
import re

VERSION = 'structured-calls-v2'
ALIASES = {
    'caller': {'callerid', 'caller', 'callernumber', 'callerphone', 'from', 'fromnumber', 'source', 'sourcenumber', 'anumber'},
    'receiver': {'receiverid', 'receiver', 'receivernumber', 'receiverphone', 'callee', 'calleenumber', 'to', 'tonumber', 'destination', 'destinationnumber', 'bnumber'},
    'timestamp': {'timestamp', 'datetime', 'calltime', 'calldatetime'},
    'duration': {'durationsec', 'durationseconds', 'duration', 'callduration'},
    'callType': {'calltype', 'direction'},
    'cellTower': {'celltower', 'towerid', 'celltowerid'},
    'sourceCaseId': {'caseid', 'case'},
    'callId': {'callid', 'recordid'},
}


def extract_calls(units, make_entity):
    entities, mentions, relationships, handled, warnings = {}, [], [], set(), []
    headers = {}
    for index, unit in enumerate(units):
        if unit['kind'] != 'row':
            headers.clear()
            continue
        group = unit.get('sheet', '')
        if 'block_number' in unit:
            group = f'docx-table:{unit["block_number"]}'
        cells = [str(c) for c in unit['cells']]
        names = [re.sub(r'[^a-z0-9]', '', c.casefold()) for c in cells]
        mapping = {role: next((i for i, name in enumerate(names) if name in aliases), None)
                   for role, aliases in ALIASES.items()}
        if mapping['caller'] is not None and mapping['receiver'] is not None:
            # Generic FROM/TO also occur in transfers. Only infer a call schema
            # from explicit caller/callee roles or corroborating call columns.
            source_name, target_name = names[mapping['caller']], names[mapping['receiver']]
            explicit = source_name.startswith('caller') and target_name.startswith(('receiver', 'callee'))
            call_columns = any(mapping[r] is not None for r in ('duration', 'callType', 'cellTower')) or 'callid' in names
            if explicit or call_columns:
                headers[group] = mapping
                handled.add(index)
            else:
                headers.pop(group, None)
            continue
        mapping = headers.get(group)
        if not mapping:
            continue
        handled.add(index)
        text = ' | '.join(cells)
        location = {k: unit[k] for k in ('sheet', 'row_number', 'line_number', 'block_number') if k in unit}

        def value(role):
            column = mapping.get(role)
            return cells[column].strip() if column is not None and column < len(cells) else ''

        phones = [value('caller'), value('receiver')]
        # Explicit phone columns permit international numbers. Preserve strings;
        # reject missing values, scientific notation and arbitrary identifiers.
        if any(not re.fullmatch(r'\+?[\d ()-]+', p) or not 7 <= len(re.sub(r'\D', '', p)) <= 15 for p in phones):
            warnings.append(f'Call row {index + 1} skipped: caller or receiver is not a valid phone number.')
            continue
        endpoints = []
        for role, phone in zip(('caller', 'receiver'), phones):
            item = make_entity(phone, 'Phone')
            entities[item['id']] = item
            endpoints.append(item['id'])
            column = mapping[role]
            start = sum(len(c) + 3 for c in cells[:column]) + len(cells[column]) - len(cells[column].lstrip())
            mentions.append({'entityId': item['id'], 'label': phone, 'type': 'Phone',
                'method': 'structured-column', 'unitIndex': index,
                'location': {**location, 'column_number': column + 1, 'columnRole': role},
                'start': start, 'end': start + len(phone), 'snippetStart': 0, 'snippet': text,
                'modelVersion': VERSION})
        metadata = {role: value(role) for role in ALIASES if role not in {'caller', 'receiver'} and value(role)}
        if 'duration' in metadata:
            raw = metadata.pop('duration')
            if re.fullmatch(r'\d+(?:\.\d+)?', raw):
                metadata['durationSeconds'] = float(raw)
            else:
                metadata['durationRaw'] = raw
                warnings.append(f'Call row {index + 1}: duration is not a nonnegative number of seconds.')
        key = f'{group}:{index}:{text}'
        relationships.append({'id': 'call:' + hashlib.sha256(key.encode()).hexdigest()[:24],
            'source': endpoints[0], 'target': endpoints[1], 'type': 'CALLED',
            'origin': 'recorded', 'reviewStatus': 'pending', 'method': 'structured-column',
            'extractorVersion': VERSION, 'ruleId': 'call-log-columns', 'unitIndex': index,
            'location': location, 'start': 0, 'end': len(text), 'evidenceText': text,
            'sentenceContext': text, 'event': metadata})
    return {'entities': list(entities.values()), 'mentions': mentions,
            'relationships': relationships, 'handled': handled, 'warnings': warnings}
