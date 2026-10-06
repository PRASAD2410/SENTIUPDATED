import unittest
from app.validators import (
    luhn_checksum_valid,
    normalize_phone,
    normalize_vehicle,
    normalize_upi,
    normalize_account
)
from app.fir_parser import extract_fir_structure
from app.structured_bank import extract_bank_transactions


class ValidatorTests(unittest.TestCase):
    def test_luhn_checksum_imei(self):
        # Valid 15-digit IMEI examples
        self.assertTrue(luhn_checksum_valid('860945041234563'))
        self.assertTrue(luhn_checksum_valid('352099001761481'))
        # Invalid IMEIs (wrong check digit)
        self.assertFalse(luhn_checksum_valid('860945041234569'))
        self.assertFalse(luhn_checksum_valid('123456789012345'))
        # Bad lengths
        self.assertFalse(luhn_checksum_valid('12345'))

    def test_phone_normalization(self):
        self.assertEqual(normalize_phone('9876543210'), '+919876543210')
        self.assertEqual(normalize_phone('+91 98765-43210'), '+919876543210')
        self.assertEqual(normalize_phone('09876543210'), '+919876543210')
        self.assertIsNone(normalize_phone('12345'))
        self.assertIsNone(normalize_phone('5551234567'))

    def test_vehicle_normalization(self):
        self.assertEqual(normalize_vehicle('dl 8c ab 1234'), 'DL8CAB1234')
        self.assertEqual(normalize_vehicle('MH-12-DE-1433'), 'MH12DE1433')
        self.assertEqual(normalize_vehicle('UP16Z9999'), 'UP16Z9999')
        self.assertIsNone(normalize_vehicle('INVALID123'))

    def test_upi_normalization(self):
        self.assertEqual(normalize_upi('user.name@okhdfcbank'), 'user.name@okhdfcbank')
        self.assertEqual(normalize_upi('9876543210@paytm'), '9876543210@paytm')
        self.assertIsNone(normalize_upi('not-a-upi'))

    def test_account_normalization(self):
        self.assertEqual(normalize_account('001234567890'), '001234567890')
        self.assertEqual(normalize_account('PAT/2029'), 'PAT/2029')


class FirAndBankParserTests(unittest.TestCase):
    def test_fir_structure_extraction(self):
        text = """
        FIR Number: FIR-104-SYN
        Police Station: Central District
        Investigating Officer: Inspector A. Verma

        Persons Mentioned:
        ENT-001    Rahul Sharma    Primary accused
        ENT-002    Rajesh Bindal   Frequent associate
        ORG-001    Bindal Exports  Shell company

        Repeated calls among Rahul Sharma and Rajesh Bindal.
        """
        result = extract_fir_structure(text, scope='case:test')
        entities = {e['label']: e for e in result['entities']}
        self.assertIn('FIR FIR-104-SYN', entities)
        self.assertIn('A. Verma', entities)
        self.assertIn('Rahul Sharma', entities)
        self.assertIn('Rajesh Bindal', entities)
        self.assertIn('Bindal Exports', entities)

        rel_types = {r['type'] for r in result['relationships']}
        self.assertIn('ACCUSED_IN', rel_types)
        self.assertIn('MENTIONED_IN', rel_types)
        self.assertIn('INVESTIGATED', rel_types)
        self.assertIn('CONTACTED', rel_types)

    def test_bank_transaction_extraction(self):
        units = [
            {'kind': 'row', 'cells': ['From Account', 'To Account', 'Amount', 'Date', 'Type']},
            {'kind': 'row', 'cells': ['ACC10001', 'ACC10002', '50000', '2026-10-01', 'NEFT']},
            {'kind': 'row', 'cells': ['ACC10002', 'ACC10003', '48000', '2026-10-02', 'UPI']}
        ]
        result = extract_bank_transactions(units, lambda label, kind: {'id': f'{kind.lower()}:{label}', 'label': label, 'type': kind})
        self.assertEqual(len(result['relationships']), 2)
        self.assertEqual(result['relationships'][0]['type'], 'TRANSFERRED_TO')
        self.assertEqual(result['relationships'][1]['type'], 'SENT_UPI')
