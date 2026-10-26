"""Normalize public/provider-supplied football matches and produce as-of research.

Principles: provenance; no synthetic linkage; no post-match leakage; two-source
score agreement needed before marking a result as verified. No dependencies.
"""
from __future__ import annotations
import datetime as dt
import json
from collections import defaultdict

UTC = dt.timezone.utc


class ContractError(ValueError):
    pass


def timestamp(value):
    if not isinstance(value, str):
        raise ContractError('TIMESTAMP_MISSING')
    try:
        z = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ContractError('TIMESTAMP_INVALID') from exc
    if z.tzinfo is None:
        raise ContractError('TIMESTAMP_WITHOUT_TIMEZONE')
    return z.astimezone(UTC)


def utcnow():
    return dt.datetime.now(UTC).isoformat()


def _pair(scores):
    if not isinstance(scores, dict):
        return None
    a, b = scores.get('home'), scores.get('away')
    if a is None or b is None:
        return None
    if isinstance(a, bool) or isinstance(b, bool) or not isinstance(a, int) or not isinstance(b, int):
        return None
    if min(a, b) < 0 or max(a, b) > 99:
        return None
    return [a, b]


def normalize_fd(payload, observed_at=None):
    """football-data.org v4 /competitions/{code}/matches shape."""
    observed_at = observed_at or utcnow()
    timestamp(observed_at)
    records = payload.get('matches', [])
    if not isinstance(records, list):
        raise ContractError('MATCHES_NOT_LIST')
    out = []
    for m in records:
        if not isinstance(m, dict) or m.get('id') is None:
            continue
        try:
            kickoff = timestamp(m['utcDate']).isoformat()
        except (KeyError, ContractError):
            continue
        h = m.get('homeTeam') or {}
        a = m.get('awayTeam') or {}
        score = m.get('score') or {}
        # Extra-time/shootout games require separate regulation-time verification.
        duration = score.get('duration')
        extra = _pair(score.get('extraTime'))
        finished = (m.get('status') == 'FINISHED' and duration in (None,'REGULAR')
                    and extra is None)
        full = _pair(score.get('fullTime')) if finished else None
        half = _pair(score.get('halfTime')) if finished else None
        out.append({
            'provider':'football_data', 'provider_match_id':str(m['id']),
            'home_provider_id':str(h['id']) if h.get('id') is not None else None,
            'away_provider_id':str(a['id']) if a.get('id') is not None else None,
            'home':h.get('name'), 'away':a.get('name'),
            'competition':(m.get('competition') or payload.get('competition') or {}).get('name'),
            'kickoff_utc':kickoff, 'finished':finished and full is not None,
            'full_time':full, 'half_time':half,
            'source_url':f"https://api.football-data.org/v4/matches/{m['id']}",
            'observed_at_utc':observed_at,
            'source_last_updated':m.get('lastUpdated'),
        })
    return out


def _openliga_result(match, result_type_id):
    rows = match.get('matchResults') or []
    valid = [r for r in rows if r.get('resultTypeID') == result_type_id]
    if not valid:
        return None
    return _pair({'home':valid[-1].get('pointsTeam1'), 'away':valid[-1].get('pointsTeam2')})


def normalize_openliga(payload, observed_at=None):
    """OpenLigaDB GET /getmatchdata/{shortcut}/{season} response."""
    observed_at = observed_at or utcnow()
    timestamp(observed_at)
    if not isinstance(payload, list):
        raise ContractError('OPENLIGA_MATCHES_NOT_LIST')
    out = []
    for m in payload:
        if not isinstance(m, dict) or m.get('matchID') is None:
            continue
        kickoff_raw = m.get('matchDateTimeUTC')
        if not kickoff_raw:
            # dateTime (without UTC marker) is not acceptable for strict matching.
            continue
        try:
            kickoff = timestamp(kickoff_raw + 'Z' if '+' not in kickoff_raw and not kickoff_raw.endswith('Z') else kickoff_raw).isoformat()
        except ContractError:
            continue
        h, a = m.get('team1') or {}, m.get('team2') or {}
        finished = m.get('matchIsFinished') is True
        full = _openliga_result(m, 2) if finished else None
        half = _openliga_result(m, 1) if finished else None
        mid = str(m['matchID'])
        out.append({
            'provider':'openligadb', 'provider_match_id':mid,
            'home_provider_id':str(h['teamId']) if h.get('teamId') is not None else None,
            'away_provider_id':str(a['teamId']) if a.get('teamId') is not None else None,
            'home':h.get('teamName'), 'away':a.get('teamName'),
            'competition':(m.get('leagueName') or (m.get('group') or {}).get('groupName')),
            'kickoff_utc':kickoff, 'finished':finished and full is not None,
            'full_time':full, 'half_time':half,
            'source_url':f'https://api.openligadb.de/getmatchdata/{mid}',
            'observed_at_utc':observed_at,
            'source_last_updated':m.get('lastUpdateDateTime'),
        })
    return out


def read_normalized(data):
    """Input wrapper written by CLI fetch. Accepts no unauthenticated naked records."""
    if not isinstance(data, dict) or data.get('schema_version') != 'TPlusRealData.0.6':
        raise ContractError('BAD_SCHEMA')
    if data.get('provider') not in ('openligadb','football_data'):
        raise ContractError('UNKNOWN_PROVIDER')
    rows = data.get('matches')
    if not isinstance(rows, list):
        raise ContractError('BAD_MATCHES')
    for m in rows:
        if m.get('provider') != data['provider']:
            raise ContractError('PROVIDER_MISMATCH')
        timestamp(m['observed_at_utc'])
        timestamp(m['kickoff_utc'])
        m.setdefault('league_code',data.get('league_code'))
        m.setdefault('season',data.get('season'))
    return rows


def _record_key(m):
    return (m['provider'], str(m['provider_match_id']))


def competition_standings_asof(matches, target, asof_utc):
    """Observed, finished games from the *same provider competition and season*.

    This is a provisional table computed from supplied results, not guaranteed
    official standings (points deductions and tiebreakers may be absent).
    """
    cutoff = timestamp(asof_utc)
    league_scope = (target.get('provider'), target.get('league_code'),
                    target.get('season'))
    table = {}
    used = 0
    for m in matches:
        other_scope = (m.get('provider'), m.get('league_code'), m.get('season'))
        if other_scope != league_scope or not m.get('finished') or not m.get('full_time'):
            continue
        if timestamp(m['kickoff_utc']) >= cutoff or timestamp(m['observed_at_utc']) > cutoff:
            continue
        h, a = m.get('home_provider_id'), m.get('away_provider_id')
        if not h or not a:
            continue
        hg, ag = m['full_time']
        used += 1
        for team_id, name, goals_for, goals_against in ((h,m.get('home'),hg,ag),(a,m.get('away'),ag,hg)):
            row=table.setdefault(team_id,{'team_provider_id':team_id,'name':name,
                'played':0,'points':0,'wins':0,'draws':0,'losses':0,'gf':0,'ga':0})
            row['played']+=1
            row['gf']+=goals_for;row['ga']+=goals_against
            outcome='wins' if goals_for>goals_against else 'draws' if goals_for==goals_against else 'losses'
            row[outcome]+=1
            row['points']+=3 if outcome=='wins' else 1 if outcome=='draws' else 0
    sorted_rows=sorted(table.values(),key=lambda r:(-r['points'], -(r['gf']-r['ga']),-r['gf'],r['team_provider_id']))
    for rank, row in enumerate(sorted_rows,1):
        row['provisional_rank']=rank
        row['goal_difference']=row['gf']-row['ga']
    return {'type':'PROVISIONAL_PROVIDER_SUBSET','matched_finished_matches':used,
            'season':target.get('season'),'league_code':target.get('league_code'),
            'scope':'Does not include official point deductions or league-specific tiebreakers',
            'rows':sorted_rows}


def asof_match_studies(matches, asof_utc, match_limit=50):
    """Retrospective as-of form/H2H: only games observed and completed BEFORE cutoff.

    This strict gate intentionally excludes an older match retrospectively fetched
    today from a past cutoff (no false historical snapshots).
    """
    cutoff = timestamp(asof_utc)
    records = [m for m in matches if timestamp(m['observed_at_utc']) <= cutoff]
    records.sort(key=lambda m:m['kickoff_utc'])
    out = []
    def team_summary(team, until):
        eligible = [m for m in records if m['finished'] and m['full_time'] is not None
                    and timestamp(m['kickoff_utc']) < until
                    and (m['home_provider_id']==team or m['away_provider_id']==team)]
        chosen = eligible[-10:]
        def stats(part):
            games=part[-5:] if part is chosen else part
            counts={'wins':0,'draws':0,'losses':0,'goals_for':0,'goals_against':0}
            for m in games:
                is_home=m['home_provider_id']==team
                home,away=m['full_time']
                gf,ga = (home,away) if is_home else (away,home)
                counts['goals_for']+=gf;counts['goals_against']+=ga
                counts['wins' if gf>ga else 'draws' if gf==ga else 'losses']+=1
            return {'matches':len(games),**counts}
        return {'last5':stats(chosen[-5:]),'last10':stats(chosen),'coverage':'PROVIDER_CURRENT_COMPETITION_ONLY'}
    for m in records[-match_limit:]:
        kick = timestamp(m['kickoff_utc'])
        if kick <= cutoff:
            continue
        home_id=m.get('home_provider_id');away_id=m.get('away_provider_id')
        if not home_id or not away_id:
            continue
        meetings=[r for r in records if r['finished'] and r['full_time']
                  and timestamp(r['kickoff_utc'])<cutoff
                  and {r.get('home_provider_id'),r.get('away_provider_id')}=={home_id,away_id}]
        out.append({'provider':m['provider'],'provider_match_id':m['provider_match_id'],
                    'match_name':f"{m['home']} vs {m['away']}",'kickoff_utc':m['kickoff_utc'],
                    'information_cutoff_utc':asof_utc,
                    'home_recent':team_summary(home_id,cutoff),
                    'away_recent':team_summary(away_id,cutoff),
                    'head_to_head_count':len(meetings),
                    'provisional_competition_table':competition_standings_asof(records,m,asof_utc),
                    'h2h_last5':[{'kickoff_utc':r['kickoff_utc'],'home':r['home'],'away':r['away'],
                                  'full_time':r['full_time']} for r in meetings[-5:]],
                    'note':'No historical standings, xG, injuries or player values inferred.'})
    return out


def match_results_by_links(provider_rows, links, reconciled_at_utc):
    """Two independent provider reports are required to verify full-time score.

    Explicit mapping is one-to-one per (provider, provider_match_id, t_match_id).
    A single provider yields CANDIDATE_ONLY; differing scores yield CONFLICT.
    """
    checked_at=timestamp(reconciled_at_utc)
    mapped=defaultdict(list)
    seen=set()
    available={_record_key(m):m for m in provider_rows}
    for link in links:
        target=link.get('t_match_id')
        provider=link.get('provider')
        pid=str(link.get('provider_match_id',''))
        key=(provider,pid,target)
        if not target or not provider or not pid or key in seen:
            continue
        seen.add(key)
        if not link.get('evidence_url','').startswith('https://') or link.get('identity_verified') is not True:
            continue
        row=available.get((provider,pid))
        if row:
            mapped[target].append(row)
    records=[];verified=[]
    for match_id,rows in sorted(mapped.items()):
        finished=[m for m in rows if m['finished'] and m.get('full_time') is not None
                  and timestamp(m['kickoff_utc']) < checked_at
                  and timestamp(m['observed_at_utc']) <= checked_at]
        providers={m['provider'] for m in finished}
        kickoff_set={timestamp(m['kickoff_utc']) for m in finished}
        # kickoff variance <= 10 minutes; different matches are not the same match.
        kickoff_agree=not kickoff_set or (max(kickoff_set)-min(kickoff_set))<=dt.timedelta(minutes=10)
        scores={tuple(m['full_time']) for m in finished}
        status=('NOT_FINISHED' if not finished else
                'SOURCE_CONFLICT' if not kickoff_agree or len(scores)!=1 else
                'VERIFIED_TWO_SOURCES' if len(providers)>=2 else 'SINGLE_SOURCE_ONLY')
        halfs={tuple(m['half_time']) for m in finished if m.get('half_time') is not None}
        ht=list(next(iter(halfs))) if len(halfs)==1 else None
        if len(halfs)>1 and status=='VERIFIED_TWO_SOURCES':
            status='HALF_TIME_CONFLICT'
        record={'t_match_id':match_id,'status':status,
                'full_time':list(next(iter(scores))) if len(scores)==1 else None,
                'half_time':ht,'provider_count':len(providers),'source_urls':sorted({m['source_url'] for m in finished}),
                'evaluated_at_utc':checked_at.isoformat()}
        records.append(record)
        if status=='VERIFIED_TWO_SOURCES':
            h,a=record['full_time']
            verified.append({'t_match_id':match_id,'home_goals':h,'away_goals':a,
                 'half_time_home_goals':ht[0] if ht else None,'half_time_away_goals':ht[1] if ht else None,
                 'status':'FT','verified_at_utc':checked_at.isoformat(),
                 'source_url':record['source_urls'][0],
                 'verification_sources':record['source_urls'],'verification_rule':'TWO_SOURCE_AGREEMENT'})
    return {'schema_version':'TPlusResultReconciliation.0.6','checked_at_utc':checked_at.isoformat(),
            'candidates':records,'results':verified,'verified_count':len(verified),
            'warning':'Manual review remains required for mismatched identities, score conflicts and unsupported competitions.'}
