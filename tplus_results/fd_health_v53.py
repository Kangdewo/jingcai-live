"""T+ v5.3: bounded football-data.org health probes and manual fixture review.

Safe for publication: never writes secret, raw response bodies or header values.
No edits to predictions, approvals, score certifications, freezes or ticket ledgers.
"""
from __future__ import annotations
import datetime as dt
import html
import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.request

ROOT = Path.cwd()
UTC = dt.timezone.utc
BASE = 'https://api.football-data.org/v4'
MAX_BODY = 4096
ALLOWED_KEYS = {'error', 'message', 'code', 'status', 'errorCode', 'detail'}
PROBES = [
    ('public_competitions', BASE+'/competitions', False),
    ('authenticated_serie_a', BASE+'/competitions/SA', True),
    ('authenticated_serie_a_schedule', BASE+'/competitions/SA/matches?dateFrom=2026-10-27&dateTo=2026-10-29', True),
]


def category_from_body(body: bytes):
    """Only return a bounded category; NEVER expose server-controlled text."""
    s = body[:MAX_BODY].decode('utf-8', errors='replace').lower()
    if re.search(r'(invalid|malformed|unrecognized|unknown|incorrect)[^\n]{0,70}(token|key|credential)|(token|key)[^\n]{0,70}(invalid|incorrect|not recognized|malformed)', s):
        return 'TOKEN_REJECTED_HINT'
    if re.search(r'(missing|no|without)[^\n]{0,55}(token|key|authentication|auth)', s):
        return 'TOKEN_MISSING_HINT'
    if re.search(r'(parameter|argument|filter|datefrom|dateto|invalid date|invalid range)', s):
        return 'INVALID_PARAMETER_HINT'
    if re.search(r'(subscription|plan|premium|restricted|not available|permission)', s):
        return 'ACCESS_LIMIT_HINT'
    return 'NO_SAFE_HINT'


def token_properties(token):
    return {
        'secret_present': bool(token),
        'contains_whitespace': any(c.isspace() for c in token),
        'has_outer_whitespace': bool(token and token != token.strip()),
        'has_outer_quotes': len(token)>1 and token[0] in ('"', "'") and token[-1]==token[0],
        'contains_non_ascii': not token.isascii(),
        'looks_like_placeholder': token.strip().lower() in {'your_token','ur_token','your-api-key','football_data_api_key','token'},
    }


def request_probe(name, url, authorized, token, *, opener=None):
    """Return metadata only; all network error payloads are intentionally discarded."""
    if url not in {p[1] for p in PROBES}:
        raise ValueError('UNAPPROVED_PROBE_URL')
    if authorized and not token:
        return {'probe':name,'authenticated':True,'outcome':'SECRET_MISSING','http_status':None,'error_hint':'NOT_REQUESTED'}
    headers={'Accept':'application/json','User-Agent':'TPlus-v53-safe-diagnostics/1.0'}
    if authorized:
        headers['X-Auth-Token']=token
    req=urllib.request.Request(url,headers=headers,method='GET')
    opener = opener or urllib.request.urlopen
    try:
        with opener(req,timeout=12) as resp:
            content=resp.read(MAX_BODY+1)
            code=int(resp.status)
        return {'probe':name,'authenticated':authorized,'outcome':'HTTP_OK' if code==200 else 'HTTP_OTHER',
                'http_status':code, 'error_hint':'NONE', 'json_shape':'object' if content.lstrip().startswith(b'{') else 'other'}
    except urllib.error.HTTPError as exc:
        try: body=exc.read(MAX_BODY)
        except Exception: body=b''
        return {'probe':name,'authenticated':authorized,'outcome':'HTTP_ERROR',
                'http_status':int(exc.code), 'error_hint':category_from_body(body),
                'response_is_json':bool(body.lstrip().startswith(b'{'))}
    except (urllib.error.URLError,TimeoutError,ValueError,OSError) as exc:
        return {'probe':name,'authenticated':authorized,'outcome':'NETWORK_OR_CLIENT_ERROR',
                'http_status':None,'error_hint':type(exc).__name__}


def diagnosis(probes):
    by={p['probe']:p for p in probes}
    public=by.get('public_competitions',{}).get('http_status')
    auth=by.get('authenticated_serie_a',{}).get('http_status')
    sched=by.get('authenticated_serie_a_schedule',{}).get('http_status')
    if auth==200 and sched==200:
        return 'FD_AVAILABLE_FOR_SCHEDULE'
    if public==200 and auth==400:
        return 'AUTHENTICATED_REQUEST_REJECTED_CHECK_TOKEN_FORMAT_OR_PROVIDER_MESSAGE'
    if auth==200 and sched==400:
        return 'SCHEDULE_REQUEST_INVALID_CHECK_FILTERS'
    if auth==403:
        return 'AUTH_RESOURCE_RESTRICTED_OR_KEY_NOT_ENTITLED'
    if auth==429:
        return 'RATE_LIMITED'
    if public==400 and auth==400:
        return 'BOTH_BASIC_REQUESTS_BAD_REQUEST_CHECK_UPSTREAM_OR_GATEWAY'
    if auth==400:
        return 'AUTH_BASIC_HTTP_400_UNRESOLVED'
    if auth is None:
        return 'PROVIDER_UNREACHABLE_OR_SECRET_MISSING'
    return 'INCOMPLETE_INVESTIGATE_PROBE_STATUSES'


def safe_review_queue(discovery):
    """Derive only source-submitted candidate IDs; no synthesized provider IDs."""
    if not isinstance(discovery,dict): return {'items':[], 'count':0}
    seen=set();out=[]
    for row in discovery.get('cases',[])[:60]:
        m=row.get('fixture') or {}
        tid=m.get('t_match_id')
        if not isinstance(tid,str) or tid in seen or not tid.startswith('t:'):continue
        seen.add(tid)
        sources=row.get('sources') or {}
        cand={}
        for provider in ('football_data','espn'):
            picks=[]
            for src in (sources.get(provider) or [])[:3]:
                if not isinstance(src,dict):continue
                mid=src.get('match_id')
                if not (isinstance(mid,(str,int)) and re.fullmatch(r'[0-9]{1,16}',str(mid))):continue
                picks.append({k:src.get(k) for k in ('provider','match_id','home_id','away_id','home','away','kickoff_utc','finished','full_time')})
            cand[provider]=picks
        out.append({'t_match_id':tid,'league':m.get('league'),'home':m.get('home'),
                    'away':m.get('away'),'kickoff_utc':m.get('kickoff_utc'),
                    'candidates':cand,'provider_state':row.get('provider_state') or {},
                    'review_state':'MANUAL_PROVIDER_IDENTITY_REVIEW_REQUIRED',
                    'approved':False, 'formal_result_verified':False})
    return {'schema_version':'TPlusManualReviewQueue.v5.3','count':len(out),
            'candidate_match_count':sum(any(v['candidates'].values()) for v in out),
            'note_cn':'来自最近一次v5.2诊断的候选证据，不是官方比赛身份批准或正式赛果。',
            'items':out}


def write_json(path, data):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.json.tmp')
    temp.write_text(json.dumps(data,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf-8')
    temp.replace(path)


def render_page(health, queue):
    def h(s):return html.escape(str(s),quote=True)
    cards=''.join(f'<div class="metric"><small>{h(label)}</small><b>{h(val)}</b></div>' for label,val in [
        ('公开基础请求',next((p.get('http_status') or p['outcome'] for p in health['probes'] if p['probe']=='public_competitions'),'—')),
        ('携密钥意甲请求',next((p.get('http_status') or p['outcome'] for p in health['probes'] if p['probe']=='authenticated_serie_a'),'—')),
        ('待审核比赛',queue['count']),('发现候选',queue['candidate_match_count'])])
    trs=''.join(f'<tr><td>{h(r["probe"])}</td><td>{h(r.get("http_status") or r["outcome"])}</td><td>{h(r.get("error_hint"))}</td></tr>' for r in health['probes'])
    items=''.join('<tr><td>'+h(x['t_match_id'])+'<small>'+h(x['league'])+'</small></td><td>'+h(x['home'])+' — '+h(x['away'])+'</td><td>'+h(x['kickoff_utc'])+'</td><td>'+h(', '.join(str(c['match_id']) for c in x['candidates']['espn']) or '—')+'</td><td>'+h(', '.join(str(c['match_id']) for c in x['candidates']['football_data']) or '—')+'</td></tr>' for x in queue['items'])
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>T+ v5.3 赛果接口健康与候选审查</title><style>
:root{{color-scheme:dark;--bg:#091623;--card:#102337;--line:#2b4358;--ink:#edf5fb;--muted:#adc1d2;--cyan:#7ce1e2;--warning:#fac77c}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 'Segoe UI','Microsoft YaHei UI','PingFang SC',sans-serif}}main{{max-width:1200px;margin:0 auto;padding:24px 18px}}header{{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:16px}}h1{{font-size:22px;margin:0 0 4px}}h2{{font-size:16px;margin:0 0 10px}}a{{color:var(--cyan);text-decoration:none}}small,.muted{{display:block;color:var(--muted);font-size:12px}}.row{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:16px 0}}.metric,.panel{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px}}.metric b{{display:block;font-size:23px;margin-top:5px}}.panel{{margin:15px 0}}.warning{{color:var(--warning)}}.scroll{{overflow:auto}}table{{border-collapse:collapse;width:100%}}th,td{{border-bottom:1px solid var(--line);padding:9px 8px;text-align:left;vertical-align:top;font-size:12px;white-space:nowrap}}th{{color:var(--muted)}}.tag{{display:inline-block;border:1px solid var(--line);padding:2px 7px;border-radius:30px;font-size:11px}}@media(max-width:700px){{.row{{grid-template-columns:repeat(2,1fr)}}table{{min-width:720px}}}}
</style></head><body><main><header><div><h1>T+ · API 健康与比赛候选审查 <span class="tag">v5.3</span></h1><p class="muted">检查时间（UTC）：{h(health['checked_at_utc'])}</p></div><nav><a href="./">返回数据中枢</a>　<a href="non-laliga-results.html">非西甲核验</a></nav></header>
<div class="panel warning">诊断不公开 Token、HTTP 响应正文或响应头个人信息。候选 ID 尚未人工批准，且不能算作正式赛果、独立模型命中或实单盈亏。</div><div class="row">{cards}</div>
<section class="panel"><h2>football-data.org 三项受控请求</h2><p class="muted">根因判断：{h(health['classification'])}</p><div class="scroll"><table><thead><tr><th>请求</th><th>结果</th><th>安全错误分类</th></tr></thead><tbody>{trs}</tbody></table></div><p class="muted">Token 格式风险：{h(', '.join(k for k,v in health['token_format'].items() if k!='secret_present' and v) or '未发现明显格式风险')}</p></section>
<section class="panel"><h2>非西甲候选审核清单（{queue['candidate_match_count']}场有候选）</h2><p class="muted">列表仅来自历史快照；下次 v5.2 发现更多比赛后需再次生成。</p><div class="scroll"><table><thead><tr><th>T编号</th><th>比赛</th><th>开球 UTC</th><th>ESPN ID</th><th>football-data ID</th></tr></thead><tbody>{items}</tbody></table></div></section><p class="muted">原始安全报告：<a href="data/results/football_data_health.json">football_data_health.json</a> · <a href="data/results/non_laliga_mapping_review.json">non_laliga_mapping_review.json</a></p></main></body></html>'''


def main(root=ROOT,*, token=None, opener=None, now=None):
    token=os.environ.get('FOOTBALL_DATA_API_KEY','') if token is None else token
    now=now or dt.datetime.now(UTC)
    probes=[request_probe(name,url,authorized,token,opener=opener) for name,url,authorized in PROBES]
    props=token_properties(token)
    health={'schema_version':'TPlusFootballDataHealth.v5.3','checked_at_utc':now.isoformat(),
            'classification':diagnosis(probes),'token_format':props,'probes':probes,
            'note_cn':'仅供API故障诊断。不存储密钥、原始错误正文或任何赛果。'}
    source=root/'docs'/'data'/'results'/'non_laliga_discovery.json'
    discovery=json.loads(source.read_text(encoding='utf-8')) if source.exists() else {}
    queue=safe_review_queue(discovery)
    output=root/'docs'/'data'/'results'
    write_json(output/'football_data_health.json',health)
    write_json(output/'non_laliga_mapping_review.json',queue)
    page=root/'docs'/'fd-health.html'
    page.parent.mkdir(parents=True,exist_ok=True)
    page.write_text(render_page(health,queue),encoding='utf-8')
    print(json.dumps({'schema_version':health['schema_version'],'classification':health['classification'],
          'probe_http_statuses':{p['probe']:p.get('http_status') for p in probes},
          'review_items':queue['count'],'candidates':queue['candidate_match_count'],
          'secret_value_never_logged':True},ensure_ascii=False))
    return health,queue


if __name__=='__main__':
    main()
