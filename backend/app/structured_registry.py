"""Header-driven mapper for Stage-B structured DB collections.

Supported CSV types (auto-detected from column headers):
  accounts, kyc, company_registry, company_directors, vehicles,
  vehicle_events, locations, cyber_events, emails, ip_events, domains
"""
import hashlib
import re
from typing import Any, Dict, List, Set

VERSION = 'structured-registry-v1'

_SCHEMAS: Dict[str, Dict[str, Set[str]]] = {
    'accounts': {
        'account_id':     {'account_id', 'accid', 'acc_id'},
        'account_number': {'account_number', 'accountnumber', 'accountno', 'accno', 'accountnum'},
        'holder_id':      {'holder_id', 'holderid', 'person_id', 'personid', 'owner_id', 'ownerid'},
        'holder_type':    {'holder_type', 'holdertype'},
        'upi_id':         {'upi_id', 'upiid', 'vpa'},
        'bank_id':        {'bank_id', 'bankid', 'bank'},
        'account_type':   {'account_type', 'accounttype'},
    },
    'kyc': {
        'person_id':  {'person_id', 'personid'},
        'name':       {'name_as_reported', 'name', 'full_name', 'fullname'},
        'phone':      {'phone_as_reported', 'phone', 'mobile', 'phonenumber'},
        'email':      {'email_as_reported', 'email', 'emailid'},
        'national_id':{'national_id', 'nationalid', 'aadhaar', 'aadhaarnumber'},
        'dob':        {'date_of_birth', 'dob', 'dateofbirth'},
        'address':    {'address_as_reported', 'address'},
    },
    'company_registry': {
        'company_id':      {'company_id', 'companyid'},
        'company_name':    {'company_name', 'companyname', 'name'},
        'reg_number':      {'registration_number', 'registrationnumber', 'regno', 'cin'},
        'company_type':    {'company_type', 'companytype', 'type'},
        'bank_account_id': {'primary_bank_account_id', 'bankaccountid', 'accountid'},
        'address_id':      {'registered_address_id', 'addressid', 'address_id'},
    },
    'company_directors': {
        'company_id': {'company_id', 'companyid'},
        'person_id':  {'person_id', 'personid'},
        'role':       {'role', 'designation', 'position'},
        'start_date': {'start_date', 'startdate', 'appointment_date'},
    },
    'vehicles': {
        'vehicle_id':   {'vehicle_id', 'vehicleid'},
        'reg_number':   {'registration_number', 'registrationnumber', 'plate', 'vehicleplate', 'licenseplate'},
        'owner_id':     {'owner_person_id', 'owner_id', 'ownerid', 'ownerpersonid'},
        'vehicle_type': {'vehicle_type', 'vehicletype', 'type'},
        'make':         {'make', 'brand'},
        'model':        {'model'},
        'year':         {'year', 'manufacture_year'},
    },
    'vehicle_events': {
        'event_id':   {'event_id', 'eventid'},
        'vehicle_id': {'vehicle_id', 'vehicleid'},
        'timestamp':  {'timestamp', 'datetime', 'event_time', 'eventtime'},
        'location_id':{'location_id', 'locationid', 'loc_id'},
        'event_type': {'event_type', 'eventtype'},
        'source_id':  {'source_id', 'sourceid'},
    },
    'locations': {
        'location_id': {'location_id', 'locationid', 'loc_id'},
        'name':        {'name'},
        'city':        {'city'},
        'state':       {'state'},
        'country':     {'country'},
        'lat':         {'latitude', 'lat'},
        'lon':         {'longitude', 'lon', 'lng'},
        'address':     {'address_text', 'address'},
        'loc_type':    {'location_type', 'locationtype'},
    },
    'cyber_events': {
        'event_id':         {'event_id', 'eventid'},
        'timestamp':        {'timestamp', 'datetime', 'event_time'},
        'event_type':       {'event_type', 'eventtype'},
        'source_entity_id': {'source_entity_id', 'sourceentityid', 'person_id', 'personid'},
        'target_entity_id': {'target_entity_id', 'targetentityid'},
        'ip_address':       {'ip_address', 'ipaddress', 'ip'},
        'device_id':        {'device_id', 'deviceid'},
        'domain_name':      {'domain_name', 'domain', 'domainname'},
        'outcome':          {'outcome', 'result'},
    },
    'emails': {
        'event_id': {'email_event_id', 'eventid', 'event_id', 'emaileventid'},
        'timestamp':{'timestamp', 'datetime', 'event_time'},
        'sender':   {'sender_email', 'sender', 'from_email', 'fromemail'},
        'receiver': {'receiver_email', 'receiver', 'to_email', 'toemail', 'recipient'},
        'domain':   {'domain'},
        'ip_address':{'ip_address', 'ipaddress', 'ip'},
    },
    'ip_events': {
        'ip_event_id':{'ip_event_id', 'ipeventid', 'event_id'},
        'timestamp':  {'timestamp', 'datetime', 'event_time'},
        'ip_address': {'ip_address', 'ipaddress', 'ip'},
        'person_id':  {'person_id', 'personid'},
        'device_id':  {'device_id', 'deviceid'},
        'event_type': {'event_type', 'eventtype'},
    },
    'domains': {
        'domain_id': {'domain_id', 'domainid'},
        'domain':    {'domain', 'domain_name', 'domainname'},
        'registrar': {'registrar'},
        'status':    {'status'},
    },
}

_REQUIRED: Dict[str, Set[str]] = {
    'accounts':          {'account_number', 'holder_id'},
    'kyc':               {'person_id', 'name'},
    'company_registry':  {'company_id', 'company_name'},
    'company_directors': {'company_id', 'person_id', 'role'},
    'vehicles':          {'vehicle_id', 'reg_number', 'owner_id'},
    'vehicle_events':    {'vehicle_id', 'event_type', 'location_id'},
    'locations':         {'location_id', 'city'},
    'cyber_events':      {'source_entity_id', 'event_type', 'ip_address'},
    'emails':            {'sender', 'receiver'},
    'ip_events':         {'ip_address', 'person_id', 'event_type'},
    'domains':           {'domain'},
}


def _norm_header(h: str) -> str:
    return re.sub(r'[^a-z0-9]', '', h.casefold())


def _detect_schema(names):
    for schema_name, roles in _SCHEMAS.items():
        mapping = {}
        for role, aliases in roles.items():
            norm_aliases = {_norm_header(a) for a in aliases}
            mapping[role] = next((i for i, n in enumerate(names) if n in norm_aliases), None)
        required = _REQUIRED[schema_name]
        if all(mapping.get(r) is not None for r in required):
            return schema_name, mapping
    return None, {}


def _val(cells, mapping, role):
    idx = mapping.get(role)
    if idx is None or idx >= len(cells):
        return ''
    return cells[idx].strip()


def _rel(rel_type, src, dst, index, **meta):
    key = f'{rel_type}:{src}:{dst}:{index}'
    return {'id': 'reg:' + hashlib.sha256(key.encode()).hexdigest()[:24],
            'source': src, 'target': dst, 'type': rel_type,
            'confidence': 0.98, 'method': 'registry-row-mapper',
            'origin': 'recorded', 'unitIndex': index,
            'ruleId': f'registry-{rel_type.lower()}', **meta}


def _proc_accounts(cells, mapping, idx, make_entity):
    entities, rels = {}, []
    acc_num = _val(cells, mapping, 'account_number')
    holder_id = _val(cells, mapping, 'holder_id')
    upi = _val(cells, mapping, 'upi_id')
    if not acc_num:
        return entities, rels
    acc_ent = make_entity(acc_num, 'Account')
    acc_ent['externalId'] = _val(cells, mapping, 'account_id')
    acc_ent['bank'] = _val(cells, mapping, 'bank_id')
    acc_ent['accountType'] = _val(cells, mapping, 'account_type')
    entities[acc_ent['id']] = acc_ent
    if holder_id:
        p = make_entity(holder_id, 'ExternalRef')
        p['externalId'] = holder_id
        entities[p['id']] = p
        rels.append(_rel('HOLDER_OF', p['id'], acc_ent['id'], idx,
                         evidenceText=f'{holder_id} holds account {acc_num}'))
    if upi:
        u = make_entity(upi, 'UPI')
        entities[u['id']] = u
        rels.append(_rel('HAS_UPI', acc_ent['id'], u['id'], idx,
                         evidenceText=f'Account {acc_num} linked to UPI {upi}'))
    return entities, rels


def _proc_kyc(cells, mapping, idx, make_entity):
    entities, rels = {}, []
    person_id = _val(cells, mapping, 'person_id')
    name = _val(cells, mapping, 'name')
    phone = _val(cells, mapping, 'phone')
    if not name:
        return entities, rels
    p = make_entity(name, 'Person')
    p['externalId'] = person_id
    p['nationalId'] = _val(cells, mapping, 'national_id')
    p['dob'] = _val(cells, mapping, 'dob')
    p['address'] = _val(cells, mapping, 'address')
    email_v = _val(cells, mapping, 'email')
    if email_v:
        p['email'] = email_v
    entities[p['id']] = p
    if phone:
        ph = make_entity(phone, 'Phone')
        entities[ph['id']] = ph
        rels.append(_rel('HAS_PHONE', p['id'], ph['id'], idx,
                         evidenceText=f'KYC: {name} has phone {phone}'))
    return entities, rels


def _proc_company_registry(cells, mapping, idx, make_entity):
    entities, rels = {}, []
    company_id = _val(cells, mapping, 'company_id')
    name = _val(cells, mapping, 'company_name')
    reg_num = _val(cells, mapping, 'reg_number')
    bank_acc = _val(cells, mapping, 'bank_account_id')
    if not name:
        return entities, rels
    label = f'{name} ({reg_num})' if reg_num else name
    org = make_entity(label, 'Organization')
    org['externalId'] = company_id
    org['registrationNumber'] = reg_num
    org['companyType'] = _val(cells, mapping, 'company_type')
    entities[org['id']] = org
    if bank_acc:
        acc = make_entity(bank_acc, 'Account')
        acc['externalId'] = bank_acc
        entities[acc['id']] = acc
        rels.append(_rel('OPERATES_ACCOUNT', org['id'], acc['id'], idx,
                         evidenceText=f'{name} operates account {bank_acc}'))
    return entities, rels


def _proc_company_directors(cells, mapping, idx, make_entity):
    entities, rels = {}, []
    company_id = _val(cells, mapping, 'company_id')
    person_id = _val(cells, mapping, 'person_id')
    role = _val(cells, mapping, 'role') or 'Director'
    if not company_id or not person_id:
        return entities, rels
    p = make_entity(person_id, 'ExternalRef')
    p['externalId'] = person_id
    o = make_entity(company_id, 'ExternalRef')
    o['externalId'] = company_id
    entities[p['id']] = p
    entities[o['id']] = o
    rels.append(_rel('DIRECTOR_OF', p['id'], o['id'], idx,
                     role=role, startDate=_val(cells, mapping, 'start_date'),
                     evidenceText=f'{person_id} is {role} of {company_id}'))
    return entities, rels


def _proc_vehicles(cells, mapping, idx, make_entity):
    entities, rels = {}, []
    vehicle_id = _val(cells, mapping, 'vehicle_id')
    reg = _val(cells, mapping, 'reg_number')
    owner_id = _val(cells, mapping, 'owner_id')
    if not reg:
        return entities, rels
    v = make_entity(reg, 'Vehicle')
    v['externalId'] = vehicle_id
    v['vehicleType'] = _val(cells, mapping, 'vehicle_type')
    v['make'] = _val(cells, mapping, 'make')
    v['model'] = _val(cells, mapping, 'model')
    v['year'] = _val(cells, mapping, 'year')
    entities[v['id']] = v
    if owner_id:
        o = make_entity(owner_id, 'ExternalRef')
        o['externalId'] = owner_id
        entities[o['id']] = o
        rels.append(_rel('OWNS_VEHICLE', o['id'], v['id'], idx,
                         evidenceText=f'{owner_id} owns vehicle {reg}'))
    return entities, rels


def _proc_vehicle_events(cells, mapping, idx, make_entity):
    entities, rels = {}, []
    vehicle_id = _val(cells, mapping, 'vehicle_id')
    location_id = _val(cells, mapping, 'location_id')
    if not vehicle_id or not location_id:
        return entities, rels
    v = make_entity(vehicle_id, 'ExternalRef')
    v['externalId'] = vehicle_id
    l = make_entity(location_id, 'ExternalRef')
    l['externalId'] = location_id
    entities[v['id']] = v
    entities[l['id']] = l
    ts = _val(cells, mapping, 'timestamp')
    ev_type = _val(cells, mapping, 'event_type') or 'seen_at'
    rels.append(_rel('VEHICLE_SEEN_AT', v['id'], l['id'], idx,
                     timestamp=ts, eventType=ev_type,
                     eventId=_val(cells, mapping, 'event_id'),
                     evidenceText=f'Vehicle {vehicle_id} {ev_type} at {location_id} on {ts}'))
    return entities, rels


def _proc_locations(cells, mapping, idx, make_entity):
    entities, rels = {}, []
    loc_id = _val(cells, mapping, 'location_id')
    city = _val(cells, mapping, 'city')
    name = _val(cells, mapping, 'name') or city
    if not loc_id:
        return entities, rels
    label = f'{name}, {city}' if name and city and name != city else (name or city)
    loc = make_entity(label, 'Location')
    loc['externalId'] = loc_id
    loc['city'] = city
    loc['state'] = _val(cells, mapping, 'state')
    loc['country'] = _val(cells, mapping, 'country')
    loc['latitude'] = _val(cells, mapping, 'lat')
    loc['longitude'] = _val(cells, mapping, 'lon')
    loc['address'] = _val(cells, mapping, 'address')
    loc['locationType'] = _val(cells, mapping, 'loc_type')
    entities[loc['id']] = loc
    return entities, rels


def _proc_cyber_events(cells, mapping, idx, make_entity):
    entities, rels = {}, []
    src_id = _val(cells, mapping, 'source_entity_id')
    ip = _val(cells, mapping, 'ip_address')
    ev_type = _val(cells, mapping, 'event_type') or 'cyber_event'
    if not src_id:
        return entities, rels
    p = make_entity(src_id, 'ExternalRef')
    p['externalId'] = src_id
    entities[p['id']] = p
    domain = _val(cells, mapping, 'domain_name')
    dst_label = domain or ip
    if dst_label:
        dst = make_entity(dst_label, 'Domain' if domain else 'Location')
        dst['externalId'] = dst_label
        entities[dst['id']] = dst
        ts = _val(cells, mapping, 'timestamp')
        rels.append(_rel('CYBER_EVENT', p['id'], dst['id'], idx,
                         eventType=ev_type, ipAddress=ip,
                         deviceId=_val(cells, mapping, 'device_id'),
                         outcome=_val(cells, mapping, 'outcome'),
                         timestamp=ts,
                         evidenceText=f'{src_id} {ev_type} on {domain or ip} at {ts}'))
    return entities, rels


def _proc_emails(cells, mapping, idx, make_entity):
    entities, rels = {}, []
    sender = _val(cells, mapping, 'sender')
    receiver = _val(cells, mapping, 'receiver')
    if not sender or not receiver:
        return entities, rels
    s = make_entity(sender, 'Person')
    r = make_entity(receiver, 'Person')
    entities[s['id']] = s
    entities[r['id']] = r
    ts = _val(cells, mapping, 'timestamp')
    rels.append(_rel('EMAILED', s['id'], r['id'], idx,
                     timestamp=ts, ipAddress=_val(cells, mapping, 'ip_address'),
                     domain=_val(cells, mapping, 'domain'),
                     evidenceText=f'{sender} emailed {receiver} at {ts}'))
    return entities, rels


def _proc_ip_events(cells, mapping, idx, make_entity):
    entities, rels = {}, []
    person_id = _val(cells, mapping, 'person_id')
    ip = _val(cells, mapping, 'ip_address')
    ev_type = _val(cells, mapping, 'event_type') or 'ip_activity'
    if not person_id or not ip:
        return entities, rels
    p = make_entity(person_id, 'ExternalRef')
    p['externalId'] = person_id
    i = make_entity(ip, 'Location')
    i['externalId'] = ip
    entities[p['id']] = p
    entities[i['id']] = i
    ts = _val(cells, mapping, 'timestamp')
    rels.append(_rel('IP_ACTIVITY', p['id'], i['id'], idx,
                     eventType=ev_type, deviceId=_val(cells, mapping, 'device_id'),
                     timestamp=ts,
                     evidenceText=f'{person_id} {ev_type} from {ip} at {ts}'))
    return entities, rels


def _proc_domains(cells, mapping, idx, make_entity):
    entities, rels = {}, []
    domain = _val(cells, mapping, 'domain')
    if not domain:
        return entities, rels
    d = make_entity(domain, 'Domain')
    d['externalId'] = _val(cells, mapping, 'domain_id')
    d['registrar'] = _val(cells, mapping, 'registrar')
    d['status'] = _val(cells, mapping, 'status')
    entities[d['id']] = d
    return entities, rels


_PROCESSORS = {
    'accounts':          _proc_accounts,
    'kyc':               _proc_kyc,
    'company_registry':  _proc_company_registry,
    'company_directors': _proc_company_directors,
    'vehicles':          _proc_vehicles,
    'vehicle_events':    _proc_vehicle_events,
    'locations':         _proc_locations,
    'cyber_events':      _proc_cyber_events,
    'emails':            _proc_emails,
    'ip_events':         _proc_ip_events,
    'domains':           _proc_domains,
}


def extract_registry(units, make_entity):
    """Extract entities and relationships from registry / event CSV rows."""
    entities, relationships, handled, warnings = {}, [], set(), []
    active_schema = None
    active_mapping = {}

    for index, unit in enumerate(units):
        if unit.get('kind') != 'row':
            active_schema = None
            active_mapping = {}
            continue

        cells = [str(c) for c in unit['cells']]
        names = [_norm_header(c) for c in cells]

        schema, mapping = _detect_schema(names)
        if schema:
            active_schema = schema
            active_mapping = mapping
            handled.add(index)
            continue

        if not active_schema:
            continue

        try:
            ents, rels = _PROCESSORS[active_schema](cells, active_mapping, index, make_entity)
            entities.update(ents)
            relationships.extend(rels)
            handled.add(index)
        except Exception as exc:
            warnings.append(f'Registry row {index + 1} ({active_schema}): {exc}')

    if not entities and not relationships:
        warnings.append(
            'No registry schema detected. Ensure column headers match expected names '
            '(e.g. account_number/holder_id, person_id/name_as_reported, vehicle_id/registration_number).'
        )

    return {
        'entities': list(entities.values()),
        'mentions': [],
        'relationships': relationships,
        'handled': handled,
        'warnings': warnings,
    }
