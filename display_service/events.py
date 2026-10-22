"""Bounded device operation logs: numeric details only, no user content."""
import fcntl
import json
import re
import threading
import time
from pathlib import Path
from . import control

LOCK = threading.Lock()
EVENTS = frozenset('boot page touch touch_down touch_up action button stop hid mouse upload voice_finish ai_home'.split())


def ingest(device, raw):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', device) or len(raw) > 16384:
        raise ValueError('invalid device or batch')
    lines = raw.decode('utf-8').splitlines()
    if not 1 <= len(lines) <= 64:
        raise ValueError('invalid batch size')
    records = []
    for line in lines:
        obj = json.loads(line)
        if not isinstance(obj, dict) or set(obj) != {'boot', 'seq', 'ms', 'event', 'page', 'a', 'b', 'result'}:
            raise ValueError('invalid fields')
        if obj['event'] not in EVENTS:
            raise ValueError('invalid event')
        for key in ('boot', 'seq', 'ms', 'page', 'a', 'b', 'result'):
            if type(obj[key]) is not int or not -(2**31) <= obj[key] < 2**53:
                raise ValueError('invalid number')
        records.append(obj)
    with LOCK:
        root = control.ROOT / 'events'
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (root / (device + '.lock')).open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            path = root / (device + '.jsonl')
            previous = _read(path)
            known = {(r['boot'], r['seq']) for r in previous}
            fresh = []
            for record in records:
                identity = record['boot'], record['seq']
                if identity not in known:
                    known.add(identity)
                    fresh.append(dict(record, receivedAt=int(time.time())))
            merged = (previous + fresh)[-512:]
            temp = path.with_suffix('.tmp')
            temp.write_text(''.join(json.dumps(r, separators=(',', ':'))+'\n' for r in merged))
            temp.chmod(0o600)
            temp.replace(path)
    return len(fresh)


def _read(path):
    try:
        return [json.loads(line) for line in path.read_text().splitlines()]
    except FileNotFoundError:
        return []


def tail(device):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', device):
        raise ValueError('invalid device')
    with LOCK:
        return _read(control.ROOT / 'events' / (device + '.jsonl'))[-100:]
