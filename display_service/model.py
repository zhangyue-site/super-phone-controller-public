"""Only allowlisted quota fields reach the device; never forward raw snapshots."""
import math


def number(value):
    return value if type(value) in (int,float) and math.isfinite(value) else None


def quota_rows(data, now):
    rows=[]
    def add(label, source, value=None, remaining=None):
        observed=number(source.get('observedAt'))
        age=max(0,now-observed) if observed else None
        status=('error' if source.get('lastError') else 'unavailable' if age is None else
                'stale' if age > (900 if label=='MiMo' else 5400) else 'ok')
        percent=number(remaining)
        if percent is not None:
            percent=max(0,min(100,percent))
            value=f'{percent:.0f}%'
        rows.append({'label':label,'value':value or '--','remaining':percent,'status':status,
                     'age':int(age) if age is not None else None})
    codex=data.get('codex') or {}
    for i,account in enumerate((codex.get('accounts') or [{}])[:2]):
        used=number((account.get('fh') or {}).get('u'))
        add(f'Codex {i+1}',codex,remaining=100-used if used is not None else None)
    cursor=data.get('cursor') or {}
    used=number((cursor.get('percentages') or {}).get('totalPercentUsed'))
    add('Cursor',cursor,remaining=100-used if used is not None else None)
    mimo=data.get('mimo') or {}
    item=(mimo.get('items') or [{}])[0]
    add('MiMo',mimo,remaining=number(item.get('remainingPercent')))
    jev=data.get('jev') or {}
    amount=number((jev.get('bal') or {}).get('amt'))
    currency=str((jev.get('bal') or {}).get('cur',''))[:4]
    add('Jev',jev,value=f'{currency} {amount:.2f}' if amount is not None else None)
    return rows
