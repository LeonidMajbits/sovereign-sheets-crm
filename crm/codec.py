"""Duplicate-aware JSON and RFC8785-compatible *integer-only* protocol profile.

Decimal money/counters are strings. Float-bearing telemetry is not admitted.
Keys sort by UTF-16 code units, not Python's Unicode scalar ordering.
"""
from __future__ import annotations
import hashlib, hmac, json, re, unicodedata
from datetime import datetime, timezone
from .errors import CRMError

ZERO = '0' * 64
ULID_RE = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
HEX_RE = re.compile(r'^[0-9a-f]{64}$')
MAX_I64 = 2**63 - 1

def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')

def timestamp(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z', value):
        raise CRMError('INVALID_TIMESTAMP')
    try:
        datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise CRMError('INVALID_TIMESTAMP') from exc
    return value

def pairs(items):
    obj = {}
    for k, v in items:
        if k in obj:
            raise CRMError('DUPLICATE_JSON_KEY')
        obj[k] = v
    return obj

def _parse_integer(value):
    if value == '-0':
        raise CRMError('NEGATIVE_ZERO_PROFILE')
    return int(value)

def _reject_number(_):
    raise CRMError('NON_INTEGER_JSON_NUMBER', 'This protocol admits only safe integer JSON numbers; counters are strings.')

def loads(raw: bytes | str, limit: int = 65536):
    try:
        if isinstance(raw, str):
            raw = raw.encode('utf-8', 'strict')
        if len(raw) > limit or raw.startswith(b'\xef\xbb\xbf'):
            raise CRMError('JSON_SIZE_OR_BOM')
        obj = json.loads(raw.decode('utf-8', 'strict'), object_pairs_hook=pairs,
                         parse_float=_reject_number, parse_constant=_reject_number, parse_int=_parse_integer)
        validate_tree(obj)
        return obj
    except CRMError:
        raise
    except (ValueError, UnicodeError, RecursionError, TypeError) as exc:
        raise CRMError('INVALID_JSON') from exc

def validate_tree(obj, depth=0):
    if depth > 32:
        raise CRMError('JSON_DEPTH')
    if obj is None or type(obj) is bool:
        return
    if type(obj) is int:
        if abs(obj) > 2**53 - 1:
            raise CRMError('UNSAFE_JSON_INTEGER')
    elif isinstance(obj, str):
        try:
            obj.encode('utf-8', 'strict')
        except UnicodeError as exc:
            raise CRMError('INVALID_UNICODE') from exc
    elif type(obj) is list:
        if len(obj) > 10000:
            raise CRMError('JSON_ARRAY_LIMIT')
        for v in obj:
            validate_tree(v, depth+1)
    elif type(obj) is dict:
        if len(obj) > 10000:
            raise CRMError('JSON_OBJECT_LIMIT')
        for k, v in obj.items():
            if not isinstance(k, str):
                raise CRMError('JSON_KEY_TYPE')
            validate_tree(k, depth+1)
            validate_tree(v, depth+1)
    else:
        raise CRMError('JSON_TYPE')

def jcs(obj) -> bytes:
    validate_tree(obj)
    def ordered(x):
        if type(x) is dict:
            return {k:ordered(x[k]) for k in sorted(x,key=lambda k:k.encode('utf-16be'))}
        if type(x) is list:
            return [ordered(v) for v in x]
        return x
    # Same validated integer-only profile and UTF-16 key order as the v5
    # encoder; the C JSON encoder handles the whole ordered tree in one pass.
    return json.dumps(ordered(obj),ensure_ascii=False,separators=(',', ':'),allow_nan=False).encode('utf-8')


def digest(obj, domain: str = '') -> str:
    data = obj if isinstance(obj, bytes) else jcs(obj)
    return hashlib.sha256((domain.encode('ascii') + b'\n' if domain else b'') + data).hexdigest()

def mac(key: bytes, obj, domain='CRM3:transport:v1') -> str:
    if len(key) < 32:
        raise CRMError('WEAK_KEY', exit_code=4)
    return hmac.new(key, domain.encode()+b'\n'+jcs(obj), hashlib.sha256).hexdigest()

def integer(value, minimum=0) -> int:
    if not isinstance(value, str) or not re.fullmatch(r'0|[1-9][0-9]{0,18}', value):
        raise CRMError('INVALID_DECIMAL_INTEGER')
    n = int(value)
    if not minimum <= n <= MAX_I64:
        raise CRMError('INTEGER_RANGE')
    return n

def ulid(value: str) -> str:
    if not isinstance(value, str) or not ULID_RE.fullmatch(value):
        raise CRMError('INVALID_ULID')
    return value

def text(value, cap=2048, nullable=False):
    if value is None and nullable:
        return None
    if not isinstance(value, str):
        raise CRMError('TEXT_TYPE')
    try:
        raw = value.encode('utf-8', 'strict')
    except UnicodeError as exc:
        raise CRMError('INVALID_UNICODE') from exc
    if len(raw) > cap:
        raise CRMError('TEXT_TOO_LONG')
    if any((unicodedata.category(c) == 'Cc' and c not in '\n\t') or
           c in '\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069' for c in value):
        raise CRMError('TEXT_CONTROL')
    return value

def normalize_name(value: str) -> str:
    return ' '.join(unicodedata.normalize('NFKC', value).casefold().split())

def safe_cell(value: str) -> dict:
    """Explicit stringValue is inert for ALL leading tokens; never strip source text."""
    text(value, 32768)
    return {'userEnteredValue': {'stringValue': value},
            'userEnteredFormat': {'numberFormat': {'type': 'TEXT'}}}

def escape_display(value: str) -> str:
    """Optional lossy export representation, not canonical storage or signed data."""
    return "'" + value if value.lstrip().startswith(('=', '@', '+', '-')) else value

def literal_cell(cell: dict, cap=2048) -> str:
    if not isinstance(cell, dict):
        raise CRMError('CELL_TYPE')
    if any(k in cell for k in ('dataSourceFormula', 'dataSourceTable', 'pivotTable', 'chipRuns', 'textFormatRuns')):
        raise CRMError('NONLITERAL_CELL')
    entered = cell.get('userEnteredValue')
    if not entered:
        if cell.get('effectiveValue'):
            raise CRMError('UNPROVEN_EFFECTIVE_VALUE')
        return ''
    if set(entered) != {'stringValue'}:
        raise CRMError('FORMULA_OR_NONSTRING_CELL')
    value = text(entered['stringValue'], cap)
    if value.lstrip().startswith(('=', '@', '+', '-')):
        raise CRMError('FORMULA_LIKE_DRAFT')
    return value
