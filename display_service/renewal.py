"""Bounded auth recovery for the existing server-side MiMo quota collector."""
import time

AUTH_ERRORS=frozenset(('http_401','http_403','session_expired'))


def collect_with_renewal(fetch,renew,report=None):
    try:
        return fetch()
    except RuntimeError as exc:
        if str(exc) not in AUTH_ERRORS:
            raise
    try:
        renew()
    except Exception as exc:
        if report:report({'state':'renew_failed','at':int(time.time()),'error':type(exc).__name__})
        raise RuntimeError('renew_failed:'+type(exc).__name__) from None
    try:
        data=fetch()
    except Exception:
        if report:report({'state':'renew_rejected','at':int(time.time())})
        raise
    if report:report({'state':'renewed','at':int(time.time())})
    return data
