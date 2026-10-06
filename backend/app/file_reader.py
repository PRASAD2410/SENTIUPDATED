"""Format-aware file parsing with source locations and a plain text view."""
import csv
from datetime import date, datetime, time
from io import BytesIO, StringIO
from pathlib import Path
from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph
from pypdf import PdfReader
from openpyxl import load_workbook

ALLOWED = {'.txt', '.csv', '.tsv', '.pdf', '.docx', '.xlsx'}

class UnsupportedFormatError(ValueError):
    pass

def _decode(content, warnings):
    if content.startswith((b'\xff\xfe', b'\xfe\xff')):
        return content.decode('utf-16'), 'utf-16'
    try:
        return content.decode('utf-8-sig'), 'utf-8-sig'
    except UnicodeDecodeError:
        warnings.append('Decoded as Windows-1252; verify accented characters.')
        return content.decode('cp1252'), 'cp1252'

def _cell(value):
    if value is None:
        return ''
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    return str(value)

def parse_upload(filename: str, content: bytes) -> dict:
    """Preserve pages and positional rows. Header interpretation is downstream."""
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED:
        raise UnsupportedFormatError('Supported formats: PDF, DOCX, TXT, CSV, TSV, XLSX.')
    result = {'filename': filename, 'format': suffix[1:],
              'kind': 'table' if suffix in {'.csv', '.tsv', '.xlsx'} else 'text',
              'text': '', 'units': [], 'warnings': [], 'metadata': {}}
    units, warnings = result['units'], result['warnings']
    if suffix == '.txt':
        text, encoding = _decode(content, warnings)
        result['metadata']['encoding'] = encoding
        units.append({'kind': 'text', 'text': text})
    elif suffix in {'.csv', '.tsv'}:
        text, encoding = _decode(content, warnings)
        delimiter = '\t' if suffix == '.tsv' else ','
        try:
            delimiter = csv.Sniffer().sniff(text[:8192], delimiters=',;\t|').delimiter
        except csv.Error:
            warnings.append('Delimiter detection inconclusive; used format default.')
        reader = csv.reader(StringIO(text, newline=''), delimiter=delimiter, strict=True)
        previous_line = 0
        for number, cells in enumerate(reader, 1):
            units.append({'kind': 'row', 'row_number': number,
                          'line_number': previous_line + 1, 'cells': cells})
            previous_line = reader.line_num
        result['metadata'].update(encoding=encoding, delimiter=delimiter,
                                  header_policy='Rows preserved; source mapping must identify headers.')
    elif suffix == '.pdf':
        reader = PdfReader(BytesIO(content))
        if reader.is_encrypted and not reader.decrypt(''):
            raise ValueError('Password-protected PDF: upload an unlocked copy.')
        for number, page in enumerate(reader.pages, 1):
            text = ''
            try:
                text = page.extract_text(extraction_mode='layout') or ''
            except Exception:
                text = page.extract_text() or ''
            units.append({'kind': 'page', 'page_number': number, 'text': text})
            if not text.strip():
                warnings.append(f'Page {number} has no extractable text; it may be blank or require OCR.')
        result['metadata']['page_count'] = len(reader.pages)
        warnings.append('PDF layout mode preserved tables and columns.')
    elif suffix == '.docx':
        document = Document(BytesIO(content))
        for number, element in enumerate(document.element.body.iterchildren(), 1):
            if element.tag == qn('w:p'):
                units.append({'kind': 'paragraph', 'block_number': number,
                              'text': Paragraph(element, document).text})
            elif element.tag == qn('w:tbl'):
                for row_number, row in enumerate(Table(element, document).rows, 1):
                    units.append({'kind': 'row', 'block_number': number,
                                  'row_number': row_number,
                                  'cells': [cell.text for cell in row.cells]})
        warnings.append('DOCX body paragraphs and tables extracted; headers, footers, text boxes and images are not extracted.')
    else:
        workbook = load_workbook(BytesIO(content), read_only=True, data_only=False)
        formulas = False
        formatted_numbers = False
        try:
            for sheet in workbook.worksheets:
                for number, row in enumerate(sheet.iter_rows(), 1):
                    cells = []
                    for cell in row:
                        formulas |= cell.data_type == 'f'
                        formatted_numbers |= isinstance(cell.value, (int, float)) and cell.number_format != 'General'
                        cells.append(_cell(cell.value))
                    units.append({'kind': 'row', 'sheet': sheet.title,
                                  'row_number': number, 'cells': cells})
            result['metadata']['sheet_names'] = workbook.sheetnames
        finally:
            workbook.close()
        if formulas:
            warnings.append('Formula expressions are preserved, not evaluated. Export calculated values for analysis.')
        if formatted_numbers:
            warnings.append('Numeric display formatting is not reproduced; store identifiers as text to preserve leading zeros.')
    result['text'] = '\n'.join(' | '.join(u['cells']) if u['kind'] == 'row' else u['text'] for u in units)
    has_content = any(any(c.strip() for c in u['cells']) if u['kind'] == 'row' else bool(u['text'].strip()) for u in units)
    if not has_content:
        result['text'] = ''
        warnings.append('No usable content was extracted.')
    return result

def read_upload(filename: str, content: bytes) -> str:
    """Compatibility wrapper for existing text-only callers."""
    return parse_upload(filename, content)['text']
