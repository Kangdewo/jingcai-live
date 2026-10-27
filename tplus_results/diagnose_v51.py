"""T+ v5.1 read-only diagnostics for result providers.

This is NOT a result-certification engine: it NEVER updates results_verified.json,
predictions/evaluation.json, formal forecasts, or ticket settlement.
Only fixed allowlisted API origins; API tokens are never emitted to JSON or logs.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import urllib.error
import urllib.request

UTC = dt.timezone.utc
OPENLIGA = 'https://api.openligadb.de/getmatchdata/'
FOOTBALL = 'https://api.football-data.org/v4/matches/'
ESPN = 'https://site.api.espn.com/apis/site/v2/sports/soccer/esp.1/summary?event='
SCHEMA = 'TPlusResultDiagnostics.v5.1'
MAX_DIAGNOSTIC_MATCHES = 2  # Limit extra calls on rate-limited APIs.


def timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        out = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
        return out if out.tzinfo else None
    except ValueError:
        return None


def http_get_json(url: str, token: str | None = None):
    # All URLs must be constructed by this module, not loaded from user JSON.
    if not any(url.startswith(u) for u in (OPENLIGA, FOOTBALL, ESPN)):
        raise ValueError('NON_ALLOWLISTED_SOURCE')
    headers = {'Accept': 'application/json', 'User-Agent': 'TPlus-ResultDiagnostics/5.1'}
    if token:
        headers['X-Auth-Token'] = token
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=14) as response:
        if response.status != 200:
            raise RuntimeError('UNEXPECTED_HTTP_STATUS')
        raw = response.read(180_001)
    if len(raw) > 180_000:
        raise ValueError('SOURCE_RESPONSE_TOO_LARGE')
    return json.loads(raw)


def error_info(exc):
    if isinstance(exc, urllib.error.HTTPError):
        return {'state': 'HTTP_ERROR', 'http_status': int(exc.code),
                'hint': {400: 'REQUEST_INVALID', 401: 'AUTH_INVALID',
                         403: 'ACCESS_RESTRICTED', 404: 'MATCH_ID_NOT_FOUND',
                         429: 'RATE_LIMIT'}.get(int(exc.code), 'REMOTE_HTTP_ERROR')}
    # Do not serialize exception text: a URL/query or other private material may appear.
    return {'state': 'FETCH_OR_FORMAT_ERROR', 'error_type': type(exc).__name__}


def score_pair(home, away):
    if all(type(v) is int and 0 <= v <= 40 for v in (home, away)):
        return [home, away]
    return None


def parse_openliga(raw):
    if not isinstance(raw, dict):
        raise ValueError('INVALID_OPENLIGA_SHAPE')
    scores = [score_pair(x.get('pointsTeam1'), x.get('pointsTeam2'))
              for x in raw.get('matchResults', []) if isinstance(x, dict) and x.get('resultTypeID') == 2]
    scores = [s for s in scores if s is not None]
    if len(scores) > 1:
        raise ValueError('MULTIPLE_OPENLIGA_FINAL_SCORES')
    return {'id': raw.get('matchID'), 'home_id': (raw.get('team1') or {}).get('teamId'),
            'away_id': (raw.get('team2') or {}).get('teamId'),
            'kickoff': raw.get('matchDateTimeUTC'),
            'finished': raw.get('matchIsFinished') is True,
            'score': scores[0] if scores else None,
            'last_updated': raw.get('lastUpdateDateTime')}


def parse_football_data(raw):
    if not isinstance(raw, dict):
        raise ValueError('INVALID_FOOTBALL_DATA_SHAPE')
    s = ((raw.get('score') or {}).get('fullTime') or {})
    return {'id': raw.get('id'), 'home_id': (raw.get('homeTeam') or {}).get('id'),
            'away_id': (raw.get('awayTeam') or {}).get('id'),
            'kickoff': raw.get('utcDate'), 'finished': raw.get('status') == 'FINISHED',
            'score': score_pair(s.get('home'), s.get('away')),
            'last_updated': raw.get('lastUpdated')}


def inspect_observation(obs, mapping, approved_kickoff, now):
    required = ('match_id', 'home_team_id', 'away_team_id')
    if not isinstance(mapping, dict) or not all(type(mapping.get(k)) is int and mapping[k] > 0 for k in required):
        return {'state': 'INVALID_APPROVAL'}
    if obs['id'] != mapping['match_id']:
        return {'state': 'IDENTITY_MISMATCH', 'detail': 'MATCH_ID'}
    if obs['home_id'] != mapping['home_team_id'] or obs['away_id'] != mapping['away_team_id']:
        return {'state': 'IDENTITY_MISMATCH', 'detail': 'TEAM_OR_HOME_AWAY'}
    kick = timestamp(obs['kickoff'])
    if not kick or not approved_kickoff or abs((kick - approved_kickoff).total_seconds()) > 600:
        return {'state': 'IDENTITY_MISMATCH', 'detail': 'KICKOFF'}
    result = {'state': 'FINISHED_CONFIRMED' if obs['finished'] and obs['score'] is not None else 'SOURCE_NOT_FINISHED',
              'finished': obs['finished'], 'score': obs['score'], 'last_updated': obs.get('last_updated')}
    updated = timestamp(obs.get('last_updated'))
    # OpenLigaDB may publish lastUpdateDateTime without a timezone. Only flag
    # staleness for >48h in that case; any plausible timezone cannot change it.
    naive_update = False
    if updated is None and isinstance(obs.get('last_updated'), str):
        try:
            raw_dt = dt.datetime.fromisoformat(obs['last_updated'])
            if raw_dt.tzinfo is None:
                updated = raw_dt.replace(tzinfo=UTC)
                naive_update = True
        except ValueError:
            pass
    age = (now - updated.astimezone(UTC)).total_seconds() if updated else 0
    cutoff = 48 * 3600 if naive_update else 24 * 3600
    if updated and age > cutoff and now > approved_kickoff + dt.timedelta(hours=2) and result['state'] == 'SOURCE_NOT_FINISHED':
        result['state'] = 'SOURCE_STALE_NOT_FINISHED'
        result['age_hours_approx'] = round(age / 3600, 1)
        if naive_update:
            result['updated_timezone'] = 'UNSPECIFIED__AGE_APPROXIMATE'
    return result


def _extract_espn_candidate(raw, candidate):
    """Review-only. ESPN's undocumented response may change; never auto-promote.

    Summary endpoint returns a header.competitions array. Require explicit
    event ID, the correct two ESPN team IDs if supplied, kickoff and final flag.
    """
    hdr = raw.get('header', {}) if isinstance(raw, dict) else {}
    comps = hdr.get('competitions') or []
    if len(comps) != 1 or not isinstance(comps[0], dict):
        return {'state': 'ALT_SCHEMA_UNSUPPORTED'}
    comp = comps[0]
    event_id = str(hdr.get('id') or comp.get('id') or '')
    if event_id != str(candidate['event_id']):
        return {'state': 'ALT_ID_MISMATCH'}
    start = timestamp(comp.get('date'))
    expected = timestamp(candidate['kickoff_utc'])
    if not start or not expected or abs((start - expected).total_seconds()) > 600:
        return {'state': 'ALT_KICKOFF_MISMATCH'}
    sides = {x.get('homeAway'): x for x in comp.get('competitors') or [] if isinstance(x, dict)}
    if set(sides) != {'home', 'away'}:
        return {'state': 'ALT_TEAMS_MISSING'}
    for side in ('home', 'away'):
        if str((sides[side].get('team') or {}).get('id')) != str(candidate[f'{side}_team_id']):
            return {'state': 'ALT_TEAM_ID_MISMATCH'}
    state = (comp.get('status') or {}).get('type') or {}
    if state.get('completed') is not True:
        return {'state': 'ALT_NOT_FINISHED'}
    try:
        s = score_pair(int(sides['home']['score']), int(sides['away']['score']))
    except (ValueError, TypeError, KeyError):
        s = None
    return {'state': 'ALT_CANDIDATE_REVIEW_ONLY', 'score': s, 'event_id': event_id} if s else {'state': 'ALT_NO_SCORE'}


def _probe_provider(source, cfg, now, token, fetcher):
    match = cfg.get(source)
    if not isinstance(match, dict) or type(match.get('match_id')) is not int:
        return {'state': 'INVALID_APPROVAL'}
    kickoff = timestamp(cfg.get('kickoff_utc'))
    if not kickoff:
        return {'state': 'INVALID_APPROVED_KICKOFF'}
    prefix = OPENLIGA if source == 'openligadb' else FOOTBALL
    url = prefix + str(match['match_id'])
    try:
        raw = fetcher(url, None if source == 'openligadb' else token)
        obs = parse_openliga(raw) if source == 'openligadb' else parse_football_data(raw)
        return inspect_observation(obs, match, kickoff, now)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError,
            RuntimeError, ValueError, TypeError, KeyError, OSError, json.JSONDecodeError) as exc:
        return error_info(exc)


def diagnose(root: Path, *, now=None, token=None, fetcher=http_get_json):
    now = (now or dt.datetime.now(UTC)).astimezone(UTC)
    token = os.environ.get('FOOTBALL_DATA_API_KEY', '') if token is None else token
    approval_path = root / 'predictions' / 'result_links_approved.json'
    approved = json.loads(approval_path.read_text(encoding='utf-8')) if approval_path.exists() else {}
    links = approved.get('links', [])
    if not isinstance(links, list):
        raise ValueError('APPROVAL_LINKS_NOT_ARRAY')
    alt_path = root / 'predictions' / 'alternative_sources_candidates.json'
    alt = json.loads(alt_path.read_text(encoding='utf-8')) if alt_path.exists() else {'candidates': []}
    alt_links = {x.get('t_match_id'): x for x in alt.get('candidates', []) if isinstance(x, dict)}
    rows = []
    for cfg in links[:MAX_DIAGNOSTIC_MATCHES]:
        if not isinstance(cfg, dict) or cfg.get('approved') is not True:
            continue
        row = {'t_match_id': str(cfg.get('t_match_id', ''))[:90], 'sources': {}}
        for source in ('openligadb', 'football_data'):
            if source == 'football_data' and not token:
                row['sources'][source] = {'state': 'SECRET_MISSING'}
            else:
                row['sources'][source] = _probe_provider(source, cfg, now, token, fetcher)
        item = alt_links.get(cfg.get('t_match_id'))
        # Alternative provider is queryable only after manually verifying exact IDs.
        if item:
            if item.get('approved_for_diagnostic') is not True:
                row['alternative'] = {'state': 'ALT_ID_REVIEW_REQUIRED'}
            elif (str(item.get('event_id', '')).isdigit() and all(str(item.get(k, '')).isdigit()
                  for k in ('home_team_id', 'away_team_id')) and timestamp(item.get('kickoff_utc'))):
                try:
                    row['alternative'] = _extract_espn_candidate(
                        fetcher(ESPN + str(item['event_id']), None), item)
                except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError,
                        RuntimeError, ValueError, TypeError, KeyError, OSError) as exc:
                    row['alternative'] = error_info(exc)
            else:
                row['alternative'] = {'state': 'ALT_APPROVAL_INCOMPLETE'}
        else:
            row['alternative'] = {'state': 'NO_ALT_CANDIDATE'}
        row['automatic_result_certified_by_this_module'] = False
        rows.append(row)
    result = {'schema_version': SCHEMA, 'checked_at_utc': now.isoformat(),
              'api_secret_present': bool(token), 'approved_links': len(links),
              'probed_links': len(rows), 'matches': rows,
              'certification_policy': 'DIAGNOSTIC_ONLY_NO_FORMAL_RESULT_PROMOTION',
              'note_cn': '仅诊断外部接口，独立源候选不等于正式双源核验；此文件不改变预测、返奖或正式赛果。'}
    output = root / 'docs' / 'data' / 'results' / 'diagnostics.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    tmp.replace(output)
    return result


if __name__ == '__main__':
    # GitHub checkout cwd is the repo root.
    summary = diagnose(Path.cwd())
    print(json.dumps(summary, ensure_ascii=False, indent=2))
