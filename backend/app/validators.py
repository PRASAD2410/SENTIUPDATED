"""Deterministic validators and normalizers for canonical investigation identifiers."""
import re
from typing import Optional, Tuple


def luhn_checksum_valid(number_str: str) -> bool:
    """Validate 15-digit IMEI or card number using the standard Luhn (mod-10) algorithm."""
    digits = [c for c in number_str if c.isdigit()]
    if len(digits) != 15:
        # If not 15 digits, check length; for 15-digit IMEIs specifically:
        if len(digits) < 13 or len(digits) > 19:
            return False
    # Luhn calculation
    total = 0
    reverse_digits = [int(d) for d in reversed(digits)]
    for i, d in enumerate(reverse_digits):
        if i % 2 == 1:
            doubled = d * 2
            total += (doubled - 9) if doubled > 9 else doubled
        else:
            total += d
    return total % 10 == 0


def normalize_phone(raw: str) -> Optional[str]:
    """Normalize Indian and standard international phone numbers to E.164 (+91XXXXXXXXXX)."""
    if not raw or not isinstance(raw, str):
        return None
    cleaned = re.sub(r'[\s\-().]', '', raw.strip())
    # Match +91 or 0 prefix on 10-digit Indian numbers starting with 6-9
    m = re.match(r'^(?:\+91|91|0)?([6-9]\d{9})$', cleaned)
    if m:
        return f'+91{m.group(1)}'
    # International format +<country_code><number> (7 to 15 digits)
    if re.match(r'^\+[1-9]\d{6,14}$', cleaned):
        return cleaned
    return None


def normalize_vehicle(raw: str) -> Optional[str]:
    """Normalize Indian vehicle registration number (e.g. DL 8C AB 1234 -> DL8CAB1234)."""
    if not raw or not isinstance(raw, str):
        return None
    cleaned = re.sub(r'[\s\-]', '', raw.strip().upper())
    # State code (2 letters) + District (1-2 digits) + Series (1-3 letters) + Number (4 digits)
    if re.match(r'^[A-Z]{2}\d{1,2}[A-Z]{1,3}\d{4}$', cleaned):
        return cleaned
    # Old format / BH series: 22BH1234AA
    if re.match(r'^\d{2}BH\d{4}[A-Z]{1,2}$', cleaned):
        return cleaned
    return None


def normalize_upi(raw: str) -> Optional[str]:
    """Validate and normalize Virtual Payment Address (e.g. name@okhdfcbank)."""
    if not raw or not isinstance(raw, str):
        return None
    cleaned = raw.strip().lower()
    if re.match(r'^[a-z0-9.\-_]{2,64}@[a-z]{2,32}$', cleaned):
        return cleaned
    return None


def normalize_account(raw: str) -> Optional[str]:
    """Normalize bank account number (9 to 18 digits)."""
    if not raw or not isinstance(raw, str):
        return None
    cleaned = re.sub(r'[\s\-]', '', raw.strip())
    if re.match(r'^\d{9,18}$', cleaned):
        return cleaned
    # Alphanumeric account references (e.g., PAT/2029)
    if re.match(r'^[A-Z0-9/_\-]{4,20}$', raw.strip().upper()) and any(c.isdigit() for c in raw):
        return raw.strip().upper()
    return None


def normalize_ifsc(raw: str) -> Optional[str]:
    """Validate 11-character Indian Financial System Code (e.g. HDFC0001234)."""
    if not raw or not isinstance(raw, str):
        return None
    cleaned = raw.strip().upper()
    if re.match(r'^[A-Z]{4}0[A-Z0-9]{6}$', cleaned):
        return cleaned
    return None
