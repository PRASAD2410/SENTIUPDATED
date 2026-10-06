"""Header-driven bank statement and transaction parser."""
import re
from typing import Dict, List, Any
from .validators import normalize_account, normalize_upi

VERSION = 'structured-bank-v1'

BANK_ALIASES = {
    'from_account': {'fromaccount', 'fromaccountno', 'senderaccount', 'sourceaccount', 'debitaccount', 'fromacc', 'payeraccount'},
    'to_account': {'toaccount', 'toaccountno', 'beneficiaryaccount', 'receiveraccount', 'creditaccount', 'toacc', 'payeeaccount', 'beneficiary'},
    'amount': {'amount', 'txnamount', 'transactionamount', 'debitamount', 'creditamount', 'value'},
    'currency': {'currency', 'curr', 'ccy'},
    'timestamp': {'timestamp', 'datetime', 'txndate', 'transactiondate', 'date', 'valuedate'},
    'txn_type': {'type', 'txntype', 'paymentmode', 'method', 'channel', 'mode'},
    'reference': {'utr', 'refno', 'referencenumber', 'txnid', 'transactionid', 'chequeno'}
}


def extract_bank_transactions(units: List[Dict[str, Any]], make_entity) -> Dict[str, Any]:
    """Parse rows in bank transaction CSV/TSV/table records."""
    entities = {}
    mentions = []
    relationships = []
    handled = set()
    warnings = []
    headers = {}

    for index, unit in enumerate(units):
        if unit.get('kind') != 'row':
            headers.clear()
            continue
        group = unit.get('sheet', '')
        if 'block_number' in unit:
            group = f'docx-table:{unit["block_number"]}'
        cells = [str(c) for c in unit['cells']]
        names = [re.sub(r'[^a-z0-9]', '', c.casefold()) for c in cells]
        
        mapping = {role: next((i for i, name in enumerate(names) if name in aliases), None)
                   for role, aliases in BANK_ALIASES.items()}
        
        if mapping['from_account'] is not None and mapping['to_account'] is not None:
            headers[group] = mapping
            handled.add(index)
            continue
        
        # Check if this row is under an active bank header mapping
        if group in headers:
            mapping = headers[group]
            from_raw = cells[mapping['from_account']].strip() if mapping['from_account'] < len(cells) else ''
            to_raw = cells[mapping['to_account']].strip() if mapping['to_account'] < len(cells) else ''
            
            if not from_raw or not to_raw or from_raw.lower() == 'from' or to_raw.lower() == 'to':
                continue
            
            amount_val = cells[mapping['amount']].strip() if mapping['amount'] is not None and mapping['amount'] < len(cells) else None
            date_val = cells[mapping['timestamp']].strip() if mapping['timestamp'] is not None and mapping['timestamp'] < len(cells) else None
            mode_val = cells[mapping['txn_type']].strip().upper() if mapping['txn_type'] is not None and mapping['txn_type'] < len(cells) else 'TRANSFER'
            
            from_ent = make_entity(from_raw, 'Account')
            to_ent = make_entity(to_raw, 'Account')
            
            entities[from_ent['id']] = from_ent
            entities[to_ent['id']] = to_ent
            
            rel_type = 'SENT_UPI' if 'UPI' in mode_val else 'TRANSFERRED_TO'
            rel_id = f'rel:tx-{index}'
            
            evidence_str = f'Transferred {amount_val or ""} from {from_raw} to {to_raw}'
            if date_val:
                evidence_str += f' on {date_val}'
                
            relationships.append({
                'id': rel_id,
                'source': from_ent['id'],
                'target': to_ent['id'],
                'type': rel_type,
                'confidence': 0.95,
                'method': 'bank-row-mapper',
                'origin': 'observed',
                'amount': amount_val,
                'timestamp': date_val,
                'paymentMethod': mode_val,
                'evidenceText': evidence_str,
                'ruleId': 'structured-bank-row',
                'unitIndex': index
            })
            handled.add(index)

    return {
        'entities': list(entities.values()),
        'mentions': mentions,
        'relationships': relationships,
        'handled': handled,
        'warnings': warnings
    }
