"""T+ V5 strict two-provider FT verifier.

No approval by fuzzy name; requires locally approved two-provider identities.
Results feed is separate from real pre-match freezes, experimental forecasts and ticket ROI.
Never guesses missing scores. Network errors never become a zero score.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.request
from typing import Callable

from tplus_predict.runner import ROOT, UTC, atomic_json, load_json, safe_slug, evaluate, parse_aware

SCHEMA = 'TPlusDualSourceV5.1'
OPENLIGA = 'https://api.openligadb.de/getmatchdata/'
FOOTBALL = 'https://api.football-data.org/v4/matches/'
MAX_MATCHES = 12


def _positive_int(x):
    return isinstance(x, int) and not isinstance(x, bool) and x > 0


def _nonnegative_score(x):
    return isinstance(x, int) and not isinstance(x, bool) and 0 <= x <= 40


def _id(x):
    if not (_positive_int(x) or (isinstance(x, str) and re.fullmatch(r'[1-9][0-9]{0,11}', x))):
        raise ValueError('INVALID_PROVIDER_ID')
    return int(x)


def fetch_json(url: str, token: str | None = None):
    headers={'User-Agent':'TPlusResultV5/1.0 (read-only verification)', 'Accept':'application/json'}
    if token: headers['X-Auth-Token']=token
    request=urllib.request.Request(url,headers=headers)
    with urllib.request.urlopen(request,timeout=18) as response:
        if response.status != 200:
            raise RuntimeError('SOURCE_HTTP_ERROR')
        raw=response.read(150_001)
    if len(raw)>150_000:raise ValueError('SOURCE_RESPONSE_TOO_LARGE')
    return json.loads(raw)


def _official_ids(cfg):
    if cfg.get('approved') is not True:
        raise ValueError('NOT_APPROVED')
    t_id=cfg.get('t_match_id')
    for field in ('home','away'):
        if not isinstance(cfg.get(field),str) or not cfg[field].strip():
            raise ValueError('APPROVED_TEAM_NAME_REQUIRED')
    if not isinstance(t_id,str) or not re.fullmatch(r't:[0-9]{4}-[0-9]{2}-[0-9]{2}:[^/\\\x00-\x1f]{1,32}',t_id):
        raise ValueError('INVALID_T_MATCH_ID')
    kick=parse_aware(cfg.get('kickoff_utc'))
    if not kick:raise ValueError('INVALID_APPROVED_KICKOFF')
    official_urls=cfg.get('identity_evidence_urls') or []
    if not (isinstance(official_urls,list) and official_urls and all(isinstance(u,str) and u.startswith('https://') and len(u)<1000 for u in official_urls)):
        raise ValueError('OFFICIAL_IDENTITY_EVIDENCE_REQUIRED')
    providers={}
    for p in ('openligadb','football_data'):
        x=cfg.get(p)
        if not isinstance(x,dict):raise ValueError('MISSING_'+p.upper()+'_LINK')
        providers[p]={k:_id(x.get(k)) for k in ('match_id','home_team_id','away_team_id')}
        if providers[p]['home_team_id']==providers[p]['away_team_id']:
            raise ValueError('SAME_TEAM_ID')
    return t_id,kick,providers


def _match_timestamp(raw):
    return parse_aware(raw)


def normalize_openligadb(d):
    if not isinstance(d,dict):raise ValueError('OPENLIGA_BAD_RESPONSE')
    ft=None
    for r in d.get('matchResults') or []:
        # OpenLigaDB uses 1=halftime, 2=full-time. Never use array's last entry.
        if not isinstance(r,dict):continue
        if r.get('resultTypeID')==2 and _nonnegative_score(r.get('pointsTeam1')) and _nonnegative_score(r.get('pointsTeam2')):
            if ft is not None:raise ValueError('OPENLIGA_DUPLICATE_FT')
            ft=(r['pointsTeam1'],r['pointsTeam2'])
    return {'id':d.get('matchID'),'kick':_match_timestamp(d.get('matchDateTimeUTC')),
        'home_id':(d.get('team1') or {}).get('teamId'),'away_id':(d.get('team2') or {}).get('teamId'),
        'finished':d.get('matchIsFinished') is True,'score':ft}


def normalize_football_data(d):
    if not isinstance(d,dict):raise ValueError('FOOTBALL_DATA_BAD_RESPONSE')
    score=(d.get('score') or {}).get('fullTime') or {}
    ft=(score.get('home'),score.get('away'))
    if not all(_nonnegative_score(x) for x in ft):ft=None
    return {'id':d.get('id'),'kick':_match_timestamp(d.get('utcDate')),
        'home_id':(d.get('homeTeam') or {}).get('id'),'away_id':(d.get('awayTeam') or {}).get('id'),
        'finished':d.get('status')=='FINISHED','score':ft}


def _validate_observation(ob, approved, kickoff):
    if not isinstance(ob,dict):return 'INVALID_OBSERVATION'
    if ob.get('id')!=approved['match_id']:return 'MATCH_ID_CONFLICT'
    if ob.get('home_id')!=approved['home_team_id'] or ob.get('away_id')!=approved['away_team_id']:
        return 'TEAM_ID_OR_HOME_AWAY_CONFLICT'
    when=ob.get('kick')
    if when is None or abs((when-kickoff).total_seconds())>600:
        return 'KICKOFF_CONFLICT'
    if not ob.get('finished') or ob.get('score') is None:
        return 'NOT_FINISHED'
    return None


def _known_prematch(root,t_id,kickoff,home,away):
    """Require a real pre-kickoff forecast record as the approved fixture anchor."""
    p=root/'predictions'/'records'/safe_slug(t_id)
    candidates=list(p.glob('*.json')) if p.is_dir() else []
    freeze=root/'predictions'/'freezes'/(safe_slug(t_id)+'.json')
    if freeze.is_file():candidates.append(freeze)
    for path in candidates[:150]:
        row=load_json(path)
        if not isinstance(row,dict) or row.get('t_match_id')!=t_id:continue
        if row.get('home')!=home or row.get('away')!=away:continue
        rec_kick=parse_aware(row.get('kickoff_utc'))
        captured=parse_aware(row.get('forecast_recorded_at_utc'))
        if rec_kick and captured and abs((kickoff-rec_kick).total_seconds())<=600 and captured < rec_kick:
            return True
    return False


def _can_approve_result(now,kickoff):
    return now>kickoff+dt.timedelta(minutes=90)


def verify_one(root:Path,cfg:dict,now:dt.datetime,token:str,fetcher:Callable=fetch_json):
    t_id,kickoff,providers=_official_ids(cfg)
    outcome={'t_match_id':t_id,'status':'AWAITING_CHECK','source_ids':{
        'openligadb':providers['openligadb']['match_id'],
        'football_data':providers['football_data']['match_id']}}
    if not _known_prematch(root,t_id,kickoff,cfg['home'],cfg['away']):
        outcome['status']='NO_MATCHING_PREMATCH_PREDICTION';return outcome,None
    if not _can_approve_result(now,kickoff):
        outcome['status']='AWAITING_FINAL_WHISTLE';return outcome,None
    if not token:
        outcome['status']='FOOTBALL_DATA_API_KEY_NOT_CONFIGURED';return outcome,None
    # Never use a URL from the approval file as a request destination.
    urls={k:(OPENLIGA if k=='openligadb' else FOOTBALL)+str(v['match_id']) for k,v in providers.items()}
    try:
        o=normalize_openligadb(fetcher(urls['openligadb'],None))
        f=normalize_football_data(fetcher(urls['football_data'],token))
    except (ValueError,RuntimeError,TypeError,KeyError,urllib.error.HTTPError,urllib.error.URLError,TimeoutError,OSError) as e:
        outcome['status']='SOURCE_FETCH_OR_FORMAT_ERROR'
        outcome['error_type']=type(e).__name__
        return outcome,None
    err1=_validate_observation(o,providers['openligadb'],kickoff)
    err2=_validate_observation(f,providers['football_data'],kickoff)
    if err1 or err2:
        outcome['status']='IDENTITY_OR_FINISH_CONFLICT' if (err1 and err1!='NOT_FINISHED') or (err2 and err2!='NOT_FINISHED') else 'AWAITING_BOTH_FINISHED'
        outcome['source_checks']={'openligadb':err1 or 'PASS','football_data':err2 or 'PASS'}
        return outcome,None
    if o['score']!=f['score']:
        outcome['status']='FULLTIME_SCORE_CONFLICT';return outcome,None
    h,a=o['score']
    outcome['status']='DUAL_SOURCE_VERIFIED'
    outcome['full_time']=[h,a]
    result={'t_match_id':t_id,'status':'FT','home_goals':h,'away_goals':a,
       'verified_at_utc':now.isoformat(),'kickoff_utc':kickoff.isoformat(),
       'source_url':urls['openligadb'],'verification_method':'TPlusDualSourceV5',
       'identity_approved':True,'source_count_verified_ft':2,'sources':[
         {'provider':'openligadb','match_id':providers['openligadb']['match_id'],'source_url':urls['openligadb']},
         {'provider':'football_data','match_id':providers['football_data']['match_id'],'source_url':urls['football_data']}
       ]}
    return outcome,result


def _trusted_old(row):
    return (isinstance(row,dict) and row.get('verification_method')=='TPlusDualSourceV5'
        and row.get('identity_approved') is True and row.get('source_count_verified_ft')==2
        and isinstance(row.get('sources'),list) and len(row['sources'])==2
        and {x.get('provider') for x in row['sources'] if isinstance(x,dict)}=={'openligadb','football_data'}
        and all(isinstance(x.get('source_url'),str) and x['source_url'].startswith('https://') for x in row['sources']))


def execute(root:Path=ROOT,now:dt.datetime|None=None,token:str|None=None,fetcher:Callable=fetch_json):
    now=(now or dt.datetime.now(UTC)).astimezone(UTC)
    token=os.environ.get('FOOTBALL_DATA_API_KEY','') if token is None else token
    approved=load_json(root/'predictions'/'result_links_approved.json',{}) or {}
    links=approved.get('links',[]) if isinstance(approved,dict) else []
    if not isinstance(links,list):raise ValueError('APPROVED_LINKS_NOT_ARRAY')
    if len(links)>MAX_MATCHES:raise ValueError('TOO_MANY_APPROVED_LINKS_MAX_12')
    old=load_json(root/'predictions'/'results_verified.json',{}) or {}
    current={}
    for row in old.get('results',[]) if isinstance(old,dict) else []:
        if _trusted_old(row) and isinstance(row.get('t_match_id'),str):
            current[row['t_match_id']]=row
    checks=[];seen=set();quarantined=set()
    for raw in links:
        if not isinstance(raw,dict):checks.append({'status':'INVALID_LINK_ENTRY'});continue
        tid=raw.get('t_match_id')
        if not isinstance(tid,str) or tid in seen:
            checks.append({'t_match_id':str(tid)[:80],'status':'DUPLICATE_OR_INVALID_ID'});continue
        seen.add(tid)
        try:
            outcome,cert=verify_one(root,raw,now,token,fetcher)
        except (ValueError,KeyError,TypeError) as e:
            checks.append({'t_match_id':tid,'status':'INVALID_APPROVAL','error_type':type(e).__name__});continue
        checks.append(outcome)
        if outcome['status'] in ('FULLTIME_SCORE_CONFLICT','IDENTITY_OR_FINISH_CONFLICT','AWAITING_BOTH_FINISHED'):
            if tid in current:del current[tid];quarantined.add(tid)
        elif cert is not None:
            prev=current.get(tid)
            if prev and (prev.get('home_goals'),prev.get('away_goals'))!=(cert['home_goals'],cert['away_goals']):
                checks[-1]['status']='PREVIOUSLY_VERIFIED_RESULT_CHANGED_REVIEW_REQUIRED'
                del current[tid];quarantined.add(tid)
            elif prev:
                # Keep first verified-at timestamp, ensuring historical records do not get backdated.
                current[tid]=prev
            else:current[tid]=cert
    ordered=[current[k] for k in sorted(current)]
    verified={'schema_version':SCHEMA,'results':ordered,'verified_count':len(ordered)}
    atomic_json(root/'predictions'/'results_verified.json',verified)
    ev=evaluate(root,now)
    status={'schema_version':SCHEMA,'checked_at_utc':now.isoformat(),
       'approved_links':len(links),'checked_links':len(checks),
       'dual_source_verified_results':len(ordered),'eligible_formal_pre_match_evaluations':ev['verified_completed_count'],
       'api_key_configured':bool(token),'checks':checks,'quarantined_match_ids':sorted(quarantined),
       'note_cn':'双来源比分一致只是比赛结果核验；只有赛前15分钟内真实冻结且核验合法的预测才计入正式模型准确率。票据现金返奖需独立核对。'}
    atomic_json(root/'docs'/'data'/'results'/'status.json',status)
    print(json.dumps(status,ensure_ascii=False,indent=2))
    return status


if __name__=='__main__':
    execute()
