"""T+ v0.6.2 single-match result verification and research evaluation.

No result fabrication. No silent identity approval. Archived prematch evidence
is not a formal T-15 freeze; this module never changes formal predictions.
"""
from __future__ import annotations
import datetime as dt
import math
import unicodedata
from typing import Any

UTC = dt.timezone.utc

class VerificationError(ValueError):
    pass


def iso(value: str) -> dt.datetime:
    if not isinstance(value, str):
        raise VerificationError('TIME_MISSING')
    try:
        v = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as e:
        raise VerificationError('TIME_INVALID') from e
    if v.tzinfo is None or v.utcoffset() is None:
        raise VerificationError('TIMEZONE_MISSING')
    return v.astimezone(UTC)


def flat_name(s: str) -> str:
    if not isinstance(s, str):
        return ''
    s = unicodedata.normalize('NFKD', s).casefold()
    return ''.join(c for c in s if c.isascii() and c.isalnum())


def identity_check(item: dict, config: dict, provider: str) -> tuple[bool, list[str]]:
    reasons=[]
    if item.get('provider') != provider:
        reasons.append('PROVIDER_MISMATCH')
    if abs((iso(item['kickoff_utc'])-iso(config['kickoff_utc'])).total_seconds()) > 600:
        reasons.append('KICKOFF_MISMATCH')
    for side in ('home','away'):
        acceptable={flat_name(t) for t in config['names'][side]}
        if flat_name(item.get(side)) not in acceptable:
            reasons.append(side.upper()+'_TEAM_MISMATCH')
    if provider=='openligadb':
        if str(item.get('provider_match_id')) != str(config['openligadb_match_id']):
            reasons.append('OPENLIGA_ID_MISMATCH')
        for side in ('home','away'):
            if str(item.get(side+'_provider_id')) != str(config['openligadb_'+side+'_team_id']):
                reasons.append(side.upper()+'_PROVIDER_ID_MISMATCH')
    if provider=='football_data':
        approved=config.get('football_data_approved_link') or {}
        if approved.get('identity_verified') is not True or not str(approved.get('provider_match_id','')):
            reasons.append('SECOND_PROVIDER_ID_NOT_APPROVED')
        elif str(item.get('provider_match_id'))!=str(approved['provider_match_id']):
            reasons.append('SECOND_PROVIDER_ID_MISMATCH')
        if not str(approved.get('evidence_url','')).startswith('https://'):
            reasons.append('SECOND_PROVIDER_EVIDENCE_MISSING')
    return not reasons,reasons


def discover_secondary(rows: list[dict], config: dict) -> list[dict]:
    """Only shortlist external match IDs, never authorize them automatically."""
    candidates=[]
    for m in rows:
        if m.get('provider')!='football_data':
            continue
        # Team, home/away and start-time all required. Independent ID approval follows.
        ok,reasons=identity_check(m,{**config,'football_data_approved_link':{
            'identity_verified':True,'provider_match_id':m.get('provider_match_id'),
            'evidence_url':'https://api.football-data.org/v4/' }},'football_data')
        if ok:
            candidates.append({'provider_match_id':str(m['provider_match_id']),
                 'home':m['home'],'away':m['away'],'kickoff_utc':m['kickoff_utc'],
                 'source_url':m['source_url'], 'identity_status':'REQUIRES_HUMAN_APPROVAL'})
    return candidates


def int_score(score: Any) -> bool:
    return isinstance(score,list) and len(score)==2 and all(type(n) is int and 0<=n<=99 for n in score)


def reconcile(config:dict, primary:dict | None, secondary:list[dict], now_utc:str) ->dict:
    now=iso(now_utc);kick=iso(config['kickoff_utc'])
    status='WAITING_FOR_KICKOFF' if now<kick else 'WAITING_FOR_FINAL_RESULT'
    out={'schema_version':'TPlusResultReview.0.6.2','t_match_id':config['t_match_id'],
         'checked_at_utc':now.isoformat(),'kickoff_utc':kick.isoformat(),
         'status':status,'ft_verified':False,'ht_verified':False,
         'full_time':None,'half_time':None,'first_source':None,'second_source':None,
         'second_source_candidates':discover_secondary(secondary,config),
         'issues':[],'source_count_verified_ft':0,
         'disclaimer_cn':'未满足双源核验时不能写入正式赛果文件'}
    if primary is not None:
        ok,err=identity_check(primary,config,'openligadb')
        if not ok:
            out['status']='IDENTITY_CONFLICT';out['issues']+=err;return out
        out['first_source']={'provider':'openligadb','provider_match_id':str(primary['provider_match_id']),
                             'finished':primary.get('finished') is True,
                             'source_url':primary.get('source_url')}
    if now<kick:
        return out
    if primary is None:
        out['status']='PRIMARY_SOURCE_MISSING';return out
    if not primary.get('finished') or not int_score(primary.get('full_time')):
        return out
    if iso(primary.get('observed_at_utc'))<kick:
        out['issues'].append('PRIMARY_OBSERVATION_BEFORE_KICKOFF');return out
    out['full_time']=primary['full_time']
    out['source_count_verified_ft']=1
    out['status']='SECOND_SOURCE_REQUIRED'
    approved=config.get('football_data_approved_link') or {}
    if not approved.get('identity_verified'):
        if out['second_source_candidates']:
            out['status']='SECOND_SOURCE_ID_REQUIRES_APPROVAL'
        return out
    second=[m for m in secondary if str(m.get('provider_match_id'))==str(approved.get('provider_match_id'))]
    if len(second)!=1:
        out['status']='SECOND_SOURCE_DATA_MISSING_OR_AMBIGUOUS';return out
    s=second[0]
    ok,err=identity_check(s,config,'football_data')
    if not ok:
        out['status']='IDENTITY_CONFLICT';out['issues']+=err;return out
    out['second_source']={'provider':'football_data','provider_match_id':str(s['provider_match_id']),
                          'finished':s.get('finished') is True,'source_url':s.get('source_url')}
    if not s.get('finished') or not int_score(s.get('full_time')):
        out['status']='WAITING_FOR_SECOND_SOURCE_RESULT';return out
    if iso(s['observed_at_utc'])<kick:
        out['issues'].append('SECOND_OBSERVATION_BEFORE_KICKOFF');out['status']='SECOND_SOURCE_INVALID_TIME';return out
    if s['full_time'] != primary['full_time']:
        out['status']='FULL_TIME_CONFLICT';out['issues'].append('FT_SCORE_DISAGREEMENT');out['full_time']=None;return out
    out['ft_verified']=True;out['source_count_verified_ft']=2;out['status']='FT_VERIFIED_TWO_SOURCES'
    pht=primary.get('half_time');sht=s.get('half_time')
    if int_score(pht) and int_score(sht):
        if pht==sht:
            out['half_time']=pht;out['ht_verified']=True;out['status']='FT_AND_HT_VERIFIED_TWO_SOURCES'
        else:
            out['issues'].append('HT_SCORE_DISAGREEMENT')
            out['status']='FT_VERIFIED_HT_CONFLICT'
    else:
        out['issues'].append('HT_INCOMPLETE')
    return out


def derive_labels(review:dict, handicap:int|None=None)->dict:
    if not review.get('ft_verified'):
        return {}
    h,a=review['full_time']
    label={'spf':'home' if h>a else 'draw' if h==a else 'away',
           'exact_score':f'{h}:{a}', 'total_goals':str(min(h+a,7)) if h+a<7 else '7+',
           'total_goals_raw':h+a}
    if handicap is not None:
        diff=h+handicap-a
        label['rqspf']='home' if diff>0 else 'draw' if diff==0 else 'away'
        label['handicap_integer']=handicap
    if review.get('ht_verified'):
        hh,ha=review['half_time']
        half='home' if hh>ha else 'draw' if hh==ha else 'away'
        label['half_full']=half+'/'+label['spf']
    return label


def market_baseline_review(review:dict,evidence:dict, handicap:int|None=None)->dict:
    """Historical research only, not formal frozen model evaluation."""
    baseline=evidence.get('market_baseline_from_existing_github_report') or {}
    out={'evaluation_class':'RESEARCH_ONLY_ARCHIVED_PREMATCH_MARKET_BASELINE',
         'not_formal_t15_freeze':True,'not_005':True,'evaluated':False,
         'reason':'FT_NOT_TWO_SOURCE_VERIFIED','model_id':baseline.get('model_id'),
         'reference_input_hash':baseline.get('input_hash'), 'labels':{},
         'spf_top1_hit':None,'spf_brier_multiclass':None,'spf_log_loss':None,
         'verified_result_source_count':review.get('source_count_verified_ft',0)}
    if not review.get('ft_verified'):
        return out
    when=iso(baseline['forecast_recorded_at_utc']);kick=iso(evidence['match']['kickoff_utc'])
    if when>=kick:
        out['reason']='MARKET_BASELINE_NOT_PREMATCH';return out
    ps=baseline.get('p_1x2') or {}
    if set(ps)!={'home','draw','away'} or not all(isinstance(v,(int,float)) and 0<=v<=1 for v in ps.values()) or abs(sum(ps.values())-1)>0.0001:
        out['reason']='INVALID_MARKET_PROBABILITIES';return out
    labels=derive_labels(review,handicap)
    k=labels['spf'];out['evaluated']=True;out['reason']='RESEARCH_ONLY_VALID_PREMATCH_BASELINE'
    out['labels']=labels
    out['spf_top1_hit']=(max(ps,key=ps.get)==k)
    out['spf_brier_multiclass']=round(sum((ps[x]-(x==k))**2 for x in ('home','draw','away')),8)
    out['spf_log_loss']=round(-math.log(max(ps[k],1e-15)),8)
    return out
