#!/usr/bin/env python3
"""Poll official MiMo Token Plan quota from the server; no inference requests."""
import json
import math
import time
import urllib.error
import urllib.request
from pathlib import Path

from server_codex_quota import save_private, request_json, PUSH_URL, PUSH_TOKEN_FILE
import mimo_session
from renewal_policy import collect_with_renewal as recover_auth

AUTH = Path('/var/lib/phone-controller/quota/mimo-auth.json')
CACHE = Path('/var/lib/phone-controller/quota/mimo.json')
BASE = 'https://platform.xiaomimimo.com/api/v1/tokenPlan/'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def collect():
    auth = json.loads(AUTH.read_text())
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect)
    responses = {}
    for name in ('usage', 'detail'):
        req = urllib.request.Request(BASE + name, headers={
            'Cookie': auth['cookie_header'], 'Accept': 'application/json'})
        try:
            with op.open(req, timeout=18) as res:
                raw = res.read(1024 * 1024 + 1)
                if len(raw) > 1024 * 1024:
                    raise RuntimeError('response_too_large')
                body = json.loads(raw)
        except urllib.error.HTTPError as exc:
            raise RuntimeError('http_' + str(exc.code)) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise RuntimeError('network_unavailable') from None
        if body.get('code') in (401, 403, '401', '403', 'session_expired') or body.get('error') == 'session_expired':
            raise RuntimeError('session_expired')
        if type(body.get('code')) is not int or body['code'] != 0:
            raise RuntimeError('upstream_rejected')
        responses[name] = body['data']
    usage, detail = responses['usage'], responses['detail']
    items = usage.get('monthUsage', {}).get('items')
    if not isinstance(items, list) or not items:
        raise RuntimeError('quota_items_missing')
    rows = []
    for item in items:
        if not isinstance(item.get('name'), str):
            raise RuntimeError('quota_item_invalid')
        used, limit = item.get('used'), item.get('limit')
        if type(used) is not int or type(limit) is not int or used < 0 or limit <= 0:
            raise RuntimeError('quota_numbers_invalid')
        remaining = max(0, limit - used)
        rows.append({'name': item['name'], 'remaining': remaining, 'limit': limit,
                     'remainingPercent': round(remaining / limit * 100, 4)})
    if type(detail.get('expired')) is not bool or not detail.get('planCode'):
        raise RuntimeError('plan_details_missing')
    now = int(time.time())
    accounts = [{'n': 'MiMo-' + detail['planCode'] + '-' + row['name'],
                 'rem': f"剩余 {row['remaining']:,} credits（{row['remainingPercent']:.2f}%）",
                 'ts': now} for row in rows]
    return {'plan': detail['planCode'], 'expired': detail['expired'],
            'periodEndUTC': detail.get('currentPeriodEnd'), 'items': rows,
            'observedAt': now, 'source': 'mimo_official_api', 'accounts': accounts}


def collect_with_renewal():
    """Recover once on auth failures; network errors never rotate login state."""
    def report(status):
        save_private(CACHE.parent / 'mimo-renewal.json', status)
    return recover_auth(collect, mimo_session.renew, report=report)


def main():
    try:
        data = collect_with_renewal()
        save_private(CACHE, data)
        if PUSH_URL:
            key = PUSH_TOKEN_FILE.read_text().strip()
            result = request_json(PUSH_URL, {'Authorization': 'Bearer ' + key,
                                  'Content-Type': 'application/json'},
                                  json.dumps({'source': 'mimo', 'accounts': data['accounts']}).encode())
            if result.get('ok') is not True:
                raise RuntimeError('push_rejected')
        print(json.dumps({'ok': True, 'observedAt': data['observedAt'], 'expired': data['expired']}))
        return 0
    except Exception as exc:
        error = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
        try:
            old = json.loads(CACHE.read_text())
        except (OSError, ValueError):
            old = {}
        old.update(lastCheckAt=int(time.time()), lastError=error)
        save_private(CACHE, old)
        print(json.dumps({'ok': False, 'error': error}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
