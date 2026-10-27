"""T+ v5.2: bounded discovery and manual-gated, independently corroborated FT.

Read-only towards predictions, frozen versions, evaluations and money ledgers.
No guessed provider IDs and no automatic approval. Output two public JSON reports.
ESPN site API is unofficial; failures never count as negative match results.
"""
from __future__ import annotations
import datetime as dt
import json
import hashlib
import os
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from collections import defaultdict

UTC = dt.timezone.utc
ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 'TPlusNonLaLigaV5.2'
FD_BASE = 'https://api.football-data.org/v4/competitions/SA/matches'
ESPN_BASE = 'https://site.api.espn.com/apis/site/v2/sports/soccer/'
PROVIDERS = {'意甲': ('SA', 'ita.1'), '德国杯': (None, 'ger.dfb_pokal'),
             '英联赛杯': (None, 'eng.league_cup')}
MAX_GAMES, MAX_BYTES, MAX_SOURCE_GAMES = 60, 750000, 200
MATCH_TIME_TOLERANCE = dt.timedelta(minutes=10)
# Explicit bilingual whitelist: we never link by fuzzy similarity or odds.
ALIASES = {
'萨索洛': ['Sassuolo','US Sassuolo Calcio'], '拉齐奥':['Lazio','SS Lazio','Lazio Roma'],
'罗马':['Roma','AS Roma','Roma FC'], '卡利亚里':['Cagliari','Cagliari Calcio'],
'都灵':['Torino','Torino FC'], '科莫':['Como','Como 1907'],
'威尼斯':['Venezia','Venezia FC'], '国际米兰':['Internazionale','Internazionale Milano','FC Internazionale Milano','Inter','Inter Milan','FC Internazionale'],
'AC米兰':['AC Milan','Milan'], '博洛尼亚':['Bologna','Bologna FC','Bologna FC 1909'],
'帕尔马':['Parma','Parma Calcio','Parma Calcio 1913'], '乌迪内斯':['Udinese','Udinese Calcio'],
'蒙扎':['Monza','AC Monza'], '那不勒斯':['Napoli','SSC Napoli'],
'热那亚':['Genoa','Genoa CFC'], '尤文图斯':['Juventus','Juventus FC'],
'汉堡':['Hamburg','Hamburger SV','Hamburger SV 1887'], '法兰克福':['Eintracht Frankfurt','Frankfurt'],
'多特蒙德':['Borussia Dortmund','Dortmund','BVB'], '不来梅':['Werder Bremen','SV Werder Bremen'],
'科隆':['FC Cologne','1 FC Köln','1. FC Köln','FC Koln','Cologne'],
'柏林联合':['Union Berlin','1 FC Union Berlin','1. FC Union Berlin'],
'帕德博恩':['SC Paderborn 07','Paderborn','SC Paderborn'],
'斯图加特':['VfB Stuttgart','Stuttgart'],
'桑德兰':['Sunderland','Sunderland AFC'], '布伦特':['Brentford','Brentford FC'],
'伯恩茅斯':['AFC Bournemouth','Bournemouth'], '维拉':['Aston Villa','Aston Villa FC'],
'富勒姆':['Fulham','Fulham FC'], '水晶宫':['Crystal Palace','Crystal Palace FC'],
'利物浦':['Liverpool','Liverpool FC'], '切尔西':['Chelsea','Chelsea FC'],
}

def when(s):
    if not isinstance(s, str):return None
    try:
        x=dt.datetime.fromisoformat(s.replace('Z','+00:00'))
        return x.astimezone(UTC) if x.tzinfo else None
    except ValueError:return None

def key(s):
    if not isinstance(s,str):return ''
    t=unicodedata.normalize('NFKD',s).lower()
    return ''.join(c for c in t if c.isascii() and c.isalnum())

def name_ok(t, observed):
    return t in ALIASES and key(observed) in {key(x) for x in ALIASES[t]}

def safe_id(x):
    return (type(x) is int and x>0) or (isinstance(x,str) and bool(re.fullmatch(r'[1-9][0-9]{0,14}',x)))

def bounded_score(h,a):
    return [h,a] if type(h) is int and type(a) is int and 0<=h<=40 and 0<=a<=40 else None

def parse_fd(x):
    if not isinstance(x,dict):return None
    home,away=x.get('homeTeam') or {}, x.get('awayTeam') or {}
    score=(x.get('score') or {}).get('fullTime') or {}
    return dict(provider='football_data',match_id=x.get('id'),home_id=home.get('id'),away_id=away.get('id'),
                home=home.get('name'),away=away.get('name'),kickoff_utc=x.get('utcDate'),
                status=x.get('status'),finished=x.get('status')=='FINISHED',
                full_time=bounded_score(score.get('home'),score.get('away')) if x.get('status')=='FINISHED' else None)

def parse_espn(x):
    if not isinstance(x,dict):return None
    comps=x.get('competitions') or []
    if len(comps)!=1 or not isinstance(comps[0],dict):return None
    comp=comps[0]
    sides={c.get('homeAway'):c for c in comp.get('competitors',[]) if isinstance(c,dict)}
    if set(sides)!={'home','away'}:return None
    h,a=sides['home'],sides['away']
    typ=(comp.get('status') or x.get('status') or {}).get('type') or {}
    finished=typ.get('completed') is True
    try:
        score=bounded_score(int(h.get('score')),int(a.get('score'))) if finished else None
    except (TypeError,ValueError):score=None
    return dict(provider='espn',match_id=x.get('id'),home_id=(h.get('team') or {}).get('id'),
                away_id=(a.get('team') or {}).get('id'),home=(h.get('team') or {}).get('displayName'),
                away=(a.get('team') or {}).get('displayName'),kickoff_utc=x.get('date') or comp.get('date'),
                status=typ.get('name') or '',finished=finished,full_time=score)

def safe_err(exc):
    if isinstance(exc,urllib.error.HTTPError):
        return dict(state='HTTP_ERROR',http_status=int(exc.code))
    return dict(state='FETCH_OR_FORMAT_ERROR',error_type=type(exc).__name__)

def fetch(url,token=None):
    # Endpoints built internally; no user-supplied URLs allowed.
    if not (url.startswith(FD_BASE+'?') or (url.startswith(ESPN_BASE) and re.fullmatch(
            r'https://site\.api\.espn\.com/apis/site/v2/sports/soccer/(ita\.1|ger\.dfb_pokal|eng\.league_cup)/scoreboard\?dates=[0-9]{8}&limit=100',url))):
        raise ValueError('NON_ALLOWLISTED_URL')
    headers={'Accept':'application/json','User-Agent':'TPlus-NonLaLigaV52/1.0'}
    if token and url.startswith(FD_BASE):headers['X-Auth-Token']=token
    with urllib.request.urlopen(urllib.request.Request(url,headers=headers),timeout=15) as res:
        if res.status!=200:raise RuntimeError('UNEXPECTED_SOURCE_STATUS')
        b=res.read(MAX_BYTES+1)
    if len(b)>MAX_BYTES:raise ValueError('SOURCE_TOO_LARGE')
    return json.loads(b)

def read_json(p,default):
    try:return json.loads(p.read_text(encoding='utf-8'))
    except FileNotFoundError:return default

def atomic(p,obj):
    p.parent.mkdir(parents=True,exist_ok=True)
    temp=p.with_suffix('.json.tmp')
    temp.write_text(json.dumps(obj,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    temp.replace(p)

def fixtures(root,now):
    """Merged latest + immutable daily archive; no post-match odds used for identity."""
    collected={}; collisions=set()
    sources=[]
    latest=read_json(root/'predictions'/'latest.json',{})
    sources.extend(latest.get('matches',[]) if isinstance(latest.get('matches'),list) else [])
    daily=root/'docs'/'data'/'daily'
    for p in sorted(daily.glob('20??-??-??.json'))[-12:] if daily.exists() else []:
        obj=read_json(p,{})
        for r in (obj.get('records') or {}).values():
            if isinstance(r,dict) and isinstance(r.get('first'),dict):sources.append(r['first'])
    for m in sources:
        if not isinstance(m,dict) or m.get('league') not in PROVIDERS:continue
        tid=m.get('t_match_id');k=when(m.get('kickoff_utc'))
        if not isinstance(tid,str) or not re.fullmatch(r't:\d{4}-\d\d-\d\d:[^/\\\x00-\x1f]{1,32}',tid):continue
        if not k or not now-dt.timedelta(days=7)<=k<=now+dt.timedelta(days=4):continue
        if m.get('home') not in ALIASES or m.get('away') not in ALIASES:continue
        item={c:m[c] for c in ('t_match_id','league','home','away','kickoff_utc')}
        if tid in collected and item!=collected[tid]:collisions.add(tid)
        else:collected[tid]=item
    return [v for tid,v in sorted(collected.items()) if tid not in collisions][:MAX_GAMES],sorted(collisions)

def schedule_urls(fix):
    grouped=defaultdict(list)
    for m in fix:grouped[m['league']].append(when(m['kickoff_utc']))
    out={}
    for league,times in sorted(grouped.items()):
        if not times:continue
        a=min(times).date()-dt.timedelta(days=1)
        b=max(times).date()+dt.timedelta(days=1)
        fd_code,espn_code=PROVIDERS[league]
        if (b-a).days>10:continue  # safely limited query horizon
        # ESPN sometimes rejects ranges with 400; fetch one UTC calendar day per request.
        for n in range((b-a).days+1):
            day=a+dt.timedelta(days=n)
            out[(league,'espn',day.isoformat())]=ESPN_BASE+espn_code+'/scoreboard?dates='+day.strftime('%Y%m%d')+'&limit=100'
        if fd_code:
            out[(league,'football_data')]=FD_BASE+'?'+urllib.parse.urlencode({'dateFrom':a.isoformat(),'dateTo':b.isoformat()})
    return out

def match_candidate(ob,m):
    if not isinstance(ob,dict) or not all(safe_id(ob.get(k)) for k in ('match_id','home_id','away_id')):return False
    k=when(ob.get('kickoff_utc'))
    return bool(k and abs(k-when(m['kickoff_utc']))<=MATCH_TIME_TOLERANCE
                and name_ok(m['home'],ob.get('home')) and name_ok(m['away'],ob.get('away')))

def _pub(ob):
    return {k:ob.get(k) for k in ('provider','match_id','home_id','away_id','home','away','kickoff_utc','status','finished','full_time')}

def has_prior_prematch(root,m):
    # Freeze score eligibility is separate. A market baseline is not an independent AI forecast.
    try:
        folder=root/'predictions'/'records'/hashlib.sha256(m['t_match_id'].encode('utf-8')).hexdigest()[:20]
        for p in list(folder.glob('*.json'))[:120] if folder.exists() else []:
            rec=read_json(p,{})
            if (rec.get('t_match_id')==m['t_match_id'] and rec.get('home')==m['home'] and
                    rec.get('away')==m['away'] and when(rec.get('forecast_recorded_at_utc')) and
                    when(rec['forecast_recorded_at_utc'])<when(m['kickoff_utc'])):
                return True
    except (ValueError,TypeError):pass
    return False

def verify_candidate(m,candidates,approval,now):
    """Only after explicit per-match approved provider/club IDs and HTTPS evidence."""
    if not isinstance(approval,dict) or approval.get('approved') is not True:return 'NOT_MANUALLY_APPROVED',None
    if (approval.get('t_match_id')!=m['t_match_id'] or approval.get('league')!=m['league'] or
        approval.get('home')!=m['home'] or approval.get('away')!=m['away'] or
        when(approval.get('kickoff_utc'))!=when(m['kickoff_utc'])):return 'APPROVAL_IDENTITY_CONFLICT',None
    sources=approval.get('sources') or {}
    if set(sources)!={'football_data','espn'} or m['league']!='意甲':return 'TWO_SUPPORTED_PROVIDERS_REQUIRED',None
    evidence=approval.get('identity_evidence_urls') or []
    if not (isinstance(evidence,list) and evidence and all(isinstance(x,str) and x.startswith('https://') and len(x)<=600 for x in evidence)):
        return 'OFFICIAL_IDENTITY_EVIDENCE_REQUIRED',None
    found=[]
    for provider in ('football_data','espn'):
        s=sources.get(provider)
        if not isinstance(s,dict) or not all(safe_id(s.get(k)) for k in ('match_id','home_team_id','away_team_id')):
            return 'PROVIDER_IDS_NOT_APPROVED',None
        selected=[r for r in candidates.get(provider,[]) if str(r['match_id'])==str(s['match_id'])]
        if len(selected)!=1:return 'PROVIDER_MATCH_MISSING_OR_AMBIGUOUS',None
        r=selected[0]
        if str(r['home_id'])!=str(s['home_team_id']) or str(r['away_id'])!=str(s['away_team_id']):
            return 'PROVIDER_TEAM_ID_CONFLICT',None
        if not r.get('finished') or r.get('full_time') is None:return 'AWAITING_BOTH_FINISHED',None
        found.append(r)
    if found[0]['full_time']!=found[1]['full_time']:return 'FULLTIME_CONFLICT',None
    if now<when(m['kickoff_utc'])+dt.timedelta(minutes=90):return 'BEFORE_ELIGIBLE_FINAL_TIME',None
    cert={'t_match_id':m['t_match_id'],'league':m['league'],'home':m['home'],'away':m['away'],
          'kickoff_utc':m['kickoff_utc'],'full_time':found[0]['full_time'],
          'verified_at_utc':now.isoformat(),'verification_method':'TPlusNonLaLigaTwoProviderV5.2',
          'sources':[{'provider':r['provider'],'match_id':r['match_id'],'home_team_id':r['home_id'],
                      'away_team_id':r['away_id']} for r in found],
          'note_cn':'仅核实赛果；不证明独立预测、T-15冻结或真实出票返奖。'}
    return 'DUAL_SOURCE_FT_VERIFIED',cert

def execute(root=ROOT,*,now=None,token=None,fetcher=fetch):
    now=(now or dt.datetime.now(UTC)).astimezone(UTC)
    token=os.environ.get('FOOTBALL_DATA_API_KEY','') if token is None else token
    ms,conflicts=fixtures(root,now)
    urls=schedule_urls(ms)
    responses={}; errors={}
    for name,url in urls.items():
        if name[1]=='football_data' and not token:
            errors[name]={'state':'SECRET_MISSING'};continue
        try:
            obj=fetcher(url,token if name[1]=='football_data' else None)
            arr=obj.get('matches' if name[1]=='football_data' else 'events')
            if not isinstance(arr,list):raise ValueError('BAD_SOURCE_SCHEDULE_SHAPE')
            if len(arr)>MAX_SOURCE_GAMES:raise ValueError('SOURCE_LIST_LIMIT_EXCEEDED')
            parsed=[x for x in (parse_fd(y) if name[1]=='football_data' else parse_espn(y) for y in arr) if x]
            label=name[:2]
            if name[1]=='espn':
                # ESPN broadcast days overlap. Keep exactly one event per provider match ID.
                by_id={str(item['match_id']):item for item in responses.get(label,[])+parsed if safe_id(item.get('match_id'))}
                responses[label]=list(by_id.values())
            else:
                responses[label]=parsed
        except (urllib.error.HTTPError,urllib.error.URLError,TimeoutError,RuntimeError,ValueError,TypeError,KeyError,OSError,json.JSONDecodeError) as exc:
            errors[name[:2]]=safe_err(exc)
    configs=read_json(root/'predictions'/'non_laliga_links_approved.json',{'links':[]})
    approvals=configs.get('links',[]) if isinstance(configs,dict) else []
    if not isinstance(approvals,list) or len(approvals)>60:raise ValueError('INVALID_APPROVAL_LINKS')
    ap={};duplicate=set()
    for a in approvals:
        if not isinstance(a,dict):continue
        t=a.get('t_match_id');
        if t in ap:duplicate.add(t)
        ap[t]=a
    archive=read_json(root/'docs'/'data'/'results'/'non_laliga_verified.json',{})
    verified={r['t_match_id']:r for r in archive.get('results',[]) if isinstance(r,dict) and r.get('verification_method')=='TPlusNonLaLigaTwoProviderV5.2' and isinstance(r.get('t_match_id'),str)}
    cases=[];quarantined=[]
    for m in ms:
        cand={};for_ui={};availability={}
        for provider in ('football_data','espn'):
            label=(m['league'],provider)
            cand[provider]=[r for r in responses.get(label,[]) if match_candidate(r,m)]
            if len(cand[provider])>1:
                availability[provider]='AMBIGUOUS_CANDIDATES'
                cand[provider]=[]
            else:availability[provider]=errors.get(label) or ('CANDIDATE_FOUND' if cand[provider] else 'NO_CONFIRMED_MATCH')
            for_ui[provider]=[_pub(x) for x in cand[provider]]
        if m['t_match_id'] in duplicate:
            state,cert='DUPLICATE_APPROVAL_REQUIRES_REVIEW',None
        else:state,cert=verify_candidate(m,cand,ap.get(m['t_match_id']),now)
        if m['t_match_id'] in verified and cert is not None and verified[m['t_match_id']]['full_time']!=cert['full_time']:
            state='PREVIOUS_VERIFIED_SCORE_CHANGED_REQUIRES_REVIEW';quarantined.append(m['t_match_id']);verified.pop(m['t_match_id'],None);cert=None
        elif cert and m['t_match_id'] not in verified:verified[m['t_match_id']]=cert
        if m['t_match_id'] in verified and state=='NOT_MANUALLY_APPROVED':state='HISTORICAL_VERIFIED_NO_CURRENT_APPROVAL'
        cases.append({'fixture':m,'sources':for_ui,'provider_state':availability,'verification_state':state,
                      'has_prematch_baseline_record':has_prior_prematch(root,m),
                      'formal_independent_model_evaluated':False})
    report={'schema_version':SCHEMA,'checked_at_utc':now.isoformat(),'api_key_present':bool(token),
            'fixtures_examined':len(ms),'fixture_identity_conflicts':conflicts,
            'provider_requests':len(urls),'cases':cases,
            'note_cn':'发现的比赛只作为候选；未经人工批准的双源比赛身份绝不自动升级；杯赛加时与点球必须另行确认90分钟比分。'}
    result={'schema_version':SCHEMA,'checked_at_utc':now.isoformat(),
            'verified_count':len(verified),'quarantined_ids':quarantined,'results':[verified[k] for k in sorted(verified)],
            'formal_model_score_count_added':0,
            'note_cn':'已核对完赛比分不等于合规赛前冻结或已结算奖金。本文件不会更新正式预测评估。'}
    atomic(root/'docs'/'data'/'results'/'non_laliga_discovery.json',report)
    atomic(root/'docs'/'data'/'results'/'non_laliga_verified.json',result)
    print(json.dumps({'schema_version':SCHEMA,'examined':len(ms),'discovered':sum(any(x['sources'].values()) for x in cases),
                      'verified':len(verified),'conflicts':len(conflicts),'api_key_present':bool(token)},ensure_ascii=False))
    return report,result

if __name__=='__main__':execute()
