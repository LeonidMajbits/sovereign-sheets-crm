"""Locally monotonic ULIDs; identity only, never business causality."""
import secrets, time, threading
ALPHABET = '0123456789ABCDEFGHJKMNPQRSTVWXYZ'
_lock = threading.Lock()
_last = 0

def encode(n: int) -> str:
    if not 0 <= n < 2**128:
        raise OverflowError('ULID exhausted')
    out = []
    for _ in range(26):
        out.append(ALPHABET[n & 31]); n >>= 5
    return ''.join(reversed(out))

def new_id() -> str:
    global _last
    with _lock:
        n = (time.time_ns()//1_000_000 << 80) | secrets.randbits(80)
        _last = max(n, _last+1)
        return encode(_last)

def durable_id(conn) -> str:
    row = conn.execute("SELECT value FROM runtime_state WHERE key='ulid_highwater'").fetchone()
    old = int(row[0]) if row else 0
    n = max((time.time_ns()//1_000_000 << 80) | secrets.randbits(80), old+1)
    value = encode(n)
    conn.execute("INSERT INTO runtime_state(key,value) VALUES('ulid_highwater',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(n),))
    return value
