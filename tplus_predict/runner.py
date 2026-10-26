"""T+ cloud prediction runner v0.4.

Only uses public T-owned odds feed. Strictly excludes post-kickoff features.
Market de-vig probabilities are a benchmark, NOT an independent predictive model.
Output files in predictions/ are research records, never a betting instruction.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
from zoneinfo import ZoneInfo

UTC = dt.timezone.utc
BJT = ZoneInfo('Asia/Shanghai')
ROOT = Path(__file__).resolve().parents[1]
MODEL_VERSION = 'market_devig_v1'
SCHEMA_VERSION = '0.4'
LEAD_FREEZE_MIN = 15


def utc_now() -> dt.datetime:
    return dt.datetime.now(UTC)


def parse_aware(raw):
    if not raw: return None
    try:
        t = dt.datetime.fromisoformat(str(raw).replace('Z', '+00:00'))
        if t.tzinfo is None: return None
        return t.astimezone(UTC)
    except (ValueError, TypeError): return None


def parse_upstream(raw):
    """Unzoned legacy source time is assumed Beijing, not verified UTC."""
    if not raw: return None
    try:
        t = dt.datetime.fromisoformat(str(raw).strip())
        return (t.replace(tzinfo=BJT) if t.tzinfo is None else t).astimezone(UTC)
    except (ValueError, TypeError): return None


def kickoff_utc(row):
    date, clock = row.get('date_local'), row.get('kickoff_clock_local')
    if not isinstance(date, str) or not isinstance(clock, str): return None
    try:
        local = dt.datetime.fromisoformat(date + 'T' + clock)
        return local.replace(tzinfo=ZoneInfo(row.get('kickoff_timezone') or 'Asia/Shanghai')).astimezone(UTC)
    except (ValueError, TypeError, KeyError): return None


def safe_slug(raw):
    # Stable opaque ascii key, prevents input-derived paths and collisions.
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:20]


def atomic_json(path:Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(data,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    temp.replace(path)


def load_json(path:Path, default=None):
    try: return json.loads(path.read_text(encoding='utf8'))
    except FileNotFoundError: return default


def probabilities(odds):
    try:
        values=[float(odds[k]) for k in ('had_h','had_d','had_a')]
    except (TypeError, KeyError, ValueError): return None
    if not all(math.isfinite(v) and v > 1.0 for v in values): return None
    inv=[1.0/v for v in values]
    total=sum(inv)
    if not .65 <= total <= 1.60: return None
    return {'home':round(inv[0]/total,8), 'draw':round(inv[1]/total,8), 'away':round(inv[2]/total,8)},round(total-1,6)


def choose(row, feed, now):
    match_id=row.get('t_match_id')
    if not isinstance(match_id,str) or not match_id.startswith('t:'): return None,'BAD_ID'
    kick=kickoff_utc(row)
    feed_time=parse_aware(feed.get('generated_at_utc'))
    source_time=parse_upstream(feed.get('upstream_updated_at_local'))
    if not kick or not feed_time or not source_time: return None,'UNKNOWN_TIME'
    if source_time > feed_time+dt.timedelta(minutes=10):return None,'SOURCE_CLOCK_SKEW'
    # Never create a "pre-match" forecast from a post-match or post-kickoff snapshot.
    if not (source_time < kick and feed_time < kick and now < kick): return None,'AFTER_KICKOFF'
    if feed_time > now+dt.timedelta(minutes=5):return None,'FEED_CLOCK_SKEW'
    if now-feed_time>dt.timedelta(hours=2):return None,'FEED_STALE'
    if feed_time-source_time>dt.timedelta(hours=3):return None,'UPSTREAM_STALE'
    vals=probabilities(row.get('odds') or {})
    if not vals:return None,'MISSING_1X2'
    proba,overround=vals
    leads=(kick-now).total_seconds()/60
    choice=max(proba,key=proba.get)
    rec={'schema_version':SCHEMA_VERSION,'model_id':MODEL_VERSION,'model_class':'odds_market_baseline',
      'independent_of_market':False,'is_betting_advice':False,'t_match_id':match_id,
      'home':row.get('home'),'away':row.get('away'),'league':row.get('league'),
      'kickoff_utc':kick.isoformat(),'forecast_recorded_at_utc':now.isoformat(),
      'feed_generated_at_utc':feed_time.isoformat(),'upstream_local_time':feed.get('upstream_updated_at_local'),
      'upstream_time_zone_assumed':'Asia/Shanghai','information_cutoff_utc':feed_time.isoformat(),
      'lead_minutes_at_recording':round(leads,2),'source_match_key':row.get('source_match_key'),
      'p_1x2':proba,'top1':choice,'market_overround':overround,
      'total_goals_distribution':None,'score_distribution':None,'xg_source':None,
      'data_warnings':['Market-implied baseline only; NO independent xG, form or verified lineups',
       'Upstream naive timestamp interpreted as Asia/Shanghai; provenance not independently certified']}
    input_hash=hashlib.sha256(json.dumps({'model':MODEL_VERSION,'match':match_id,
      'odds':{k:row['odds'][k] for k in ('had_h','had_d','had_a')}},
      sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:20]
    rec['input_hash']=input_hash
    return rec,None


def brier(proba, winner):
    return sum((proba[k]-(1 if k==winner else 0))**2 for k in ('home','draw','away'))


def evaluate(root:Path, now:dt.datetime):
    """Score only separately verified final results and previously frozen predictions.
    Does not scrape results or treat live/unverified scores as final.
    """
    results=load_json(root/'predictions'/'results_verified.json',default={}) or {}
    entries=results.get('results',[]) if isinstance(results,dict) else []
    judged=[]
    for entry in entries:
        if not isinstance(entry,dict):continue
        if entry.get('status')!='FT' or not entry.get('source_url') or not entry.get('verified_at_utc'):continue
        ident=entry.get('t_match_id')
        if not isinstance(ident,str):continue
        try: h,a=int(entry['home_goals']),int(entry['away_goals'])
        except (ValueError,TypeError,KeyError):continue
        if min(h,a)<0 or (isinstance(entry['home_goals'],bool) or isinstance(entry['away_goals'],bool)):continue
        f=root/'predictions'/'freezes'/(safe_slug(ident)+'.json')
        rec=load_json(f)
        if not isinstance(rec,dict) or rec.get('t_match_id')!=ident:continue
        kick=parse_aware(rec.get('kickoff_utc')); captured=parse_aware(rec.get('forecast_recorded_at_utc'))
        verified=parse_aware(entry.get('verified_at_utc'))
        if not kick or not captured or not verified or not (captured<kick<verified<=now):continue
        outcome='home' if h>a else 'draw' if h==a else 'away'
        p=rec['p_1x2']
        judged.append({'t_match_id':ident,'model_id':rec['model_id'],
          'verified_result':{'home_goals':h,'away_goals':a,'outcome':outcome,'source_url':entry['source_url']},
          'freeze_at_utc':rec['forecast_recorded_at_utc'],'top1_hit':rec['top1']==outcome,
          'brier_multiclass':round(brier(p,outcome),6),'log_loss':round(-math.log(max(p[outcome],1e-12)),6)})
    # An opt-in AI forecast is immutable and can be evaluated only after a verified FT result.
    # AI and same-time market benchmark are compared using the SAME recorded input cutoff.
    ai_pairs=[]
    for entry in entries:
        if not isinstance(entry,dict) or entry.get('status')!='FT' or not entry.get('source_url') or not entry.get('verified_at_utc'):continue
        ident=entry.get('t_match_id')
        if not isinstance(ident,str):continue
        try:h,a=int(entry['home_goals']),int(entry['away_goals'])
        except (ValueError,TypeError,KeyError):continue
        if min(h,a)<0:continue
        outcome='home' if h>a else 'draw' if h==a else 'away'
        verified=parse_aware(entry.get('verified_at_utc'))
        for rec_path in (root/'predictions'/'agents').glob('*/'+safe_slug(ident)+'.json'):
            rec=load_json(rec_path)
            if not isinstance(rec,dict) or rec.get('t_match_id')!=ident:continue
            kick=parse_aware(rec.get('kickoff_utc')); captured=parse_aware(rec.get('forecast_recorded_at_utc'))
            if not kick or not captured or not verified or not (captured<kick<verified<=now):continue
            p=rec.get('p_1x2'); base=rec.get('benchmark_same_cutoff_1x2')
            if not p or not base:continue
            ai_pairs.append({'t_match_id':ident,'model_id':rec['model_id'],
               'model_top1_hit':rec['top1']==outcome,'baseline_top1_hit':max(base,key=base.get)==outcome,
               'model_log_loss':round(-math.log(max(float(p[outcome]),1e-12)),6),
               'baseline_log_loss':round(-math.log(max(float(base[outcome]),1e-12)),6),
               'model_brier':round(brier(p,outcome),6),'baseline_brier':round(brier(base,outcome),6),
               'same_input_cutoff':True,'model_independent_of_market_data':False})
    total=len(judged)
    evaluation={'schema_version':SCHEMA_VERSION,'evaluated_at_utc':now.isoformat(),
      'verified_completed_count':total,'evaluations':judged,'ai_paired_evaluations':ai_pairs,
      'summary':{'top1_hit_rate':round(sum(x['top1_hit'] for x in judged)/total,6) if total else None,
        'mean_brier':round(sum(x['brier_multiclass'] for x in judged)/total,6) if total else None,
        'mean_log_loss':round(sum(x['log_loss'] for x in judged)/total,6) if total else None},
      'status':'NOT_EVALUATED_NO_VERIFIED_RESULTS' if not total and not ai_pairs else 'EVALUATED'}
    atomic_json(root/'predictions'/'evaluation.json',evaluation)
    return evaluation


def run(root:Path=ROOT,now:dt.datetime|None=None):
    now=(now or utc_now()).astimezone(UTC)
    feed=load_json(root/'model_feed'/'latest.json')
    if not isinstance(feed,dict):raise RuntimeError('Missing model_feed/latest.json; run publisher first')
    if feed.get('feed_type')!='T_odds_research':raise RuntimeError('Unexpected feed type')
    directory=root/'predictions'
    records=[];skips={}; archived=0;freeze_count=0
    for row in feed.get('matches',[])[:250]:
        if not isinstance(row,dict):continue
        rec,error=choose(row,feed,now)
        if error:
            skips[error]=skips.get(error,0)+1
            continue
        records.append(rec)
        slug=safe_slug(rec['t_match_id'])
        # Each distinct input snapshot recorded once; never overwrite immutable research samples.
        historical=directory/'records'/slug/(rec['input_hash']+'.json')
        if not historical.exists():
            atomic_json(historical,rec);archived+=1
        # A T-15-eligible record is only a record actually generated in 0-15 min pre-kickoff.
        # GitHub schedule is best effort and can miss the window; NEVER backdate a forecast.
        freeze=directory/'freezes'/(slug+'.json')
        if 0 < rec['lead_minutes_at_recording']<=LEAD_FREEZE_MIN and not freeze.exists():
            frozen=dict(rec,freeze_label='REAL_CAPTURE_WITHIN_15_MINUTES_BEFORE_KICKOFF',
                        claimed_exact_T_minus_15=False)
            atomic_json(freeze,frozen);freeze_count+=1
    from tplus_predict.agents import run_agents
    agent_report=run_agents(root,records,now)
    output={'schema_version':SCHEMA_VERSION,'generated_at_utc':now.isoformat(),
      'source_feed_generated_at_utc':feed.get('generated_at_utc'),
      'research_only':True,'model_inventory':[{'id':MODEL_VERSION,'role':'market_baseline','independent':False}],
      'independent_ai_agents_configured':agent_report['api_enabled_count']>0,
      'ai_agent_runs':agent_report['predictions_saved'],
      'match_count':len(records),'matches':records,
      'limitations':['No independent team xG or verified lineup features in public T feed',
                     'Predictions freeze only when scheduler actually runs before kickoff',
                     'An externally shared ChatGPT conversation is not automatically invoked']}
    atomic_json(directory/'latest.json',output)
    ev=evaluate(root,now)
    status={'schema_version':SCHEMA_VERSION,'updated_at_utc':now.isoformat(),
       'source_generated_at_utc':feed.get('generated_at_utc'),
       'valid_pre_match_forecasts':len(records), 'new_immutable_snapshots':archived,
       'new_freezes':freeze_count, 'skipped_by_reason':skips,
       'verified_results_evaluated':ev['verified_completed_count'],
       'ai_runner_state':agent_report['state'],
       'agent_requests_attempted':agent_report['requests_attempted'],
       'agent_predictions_saved':len(agent_report['predictions_saved']),
       'agent_errors':agent_report['errors'],
       'has_independent_team_features':False}
    atomic_json(directory/'status.json',status)
    print(json.dumps(status,ensure_ascii=False,indent=2))
    return status


if __name__=='__main__':
    # Support direct script execution via `python tplus_predict/runner.py`.
    sys.path.insert(0,str(ROOT))
    run()
