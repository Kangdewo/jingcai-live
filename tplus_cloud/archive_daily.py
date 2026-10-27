"""Append market-only *pre-kickoff* research snapshots to public daily history.

No scores are imported here. Snapshots cannot be elevated to formal predictions.
All I/O is read-only except docs/data/daily, and no API keys are accessed.
"""
from __future__ import annotations
import datetime as dt
import json
import os
from pathlib import Path
import re
import tempfile

TZ = dt.timezone(dt.timedelta(hours=8))


def aware(v: str) -> dt.datetime:
    out = dt.datetime.fromisoformat(v.replace('Z', '+00:00'))
    if out.tzinfo is None:
        raise ValueError('timezone required for audit log')
    return out


def clean_match(m: dict) -> dict | None:
    if m.get('model_id') != 'market_devig_v1' or m.get('independent_of_market') is not False:
        return None
    mid = str(m.get('t_match_id',''))
    if not re.fullmatch(r't:\d{4}-\d{2}-\d{2}:.{1,40}', mid):
        return None
    try:
        at = aware(m['forecast_recorded_at_utc'])
        kick = aware(m['kickoff_utc'])
    except (KeyError,ValueError,TypeError):
        return None
    if not at < kick:
        return None
    date_local = kick.astimezone(TZ).date().isoformat()
    p = m.get('p_1x2') or {}
    try:
        prob = {x: round(float(p[x]), 8) for x in ('home','draw','away')}
    except (KeyError,ValueError,TypeError):
        return None
    if any(x < 0 or x > 1 for x in prob.values()) or not .999 <= sum(prob.values()) <= 1.001:
        return None
    return {'t_match_id':mid,'date_bjt':date_local,'home':str(m.get('home',''))[:100],
            'away':str(m.get('away',''))[:100], 'league':str(m.get('league',''))[:100],
            'kickoff_utc':kick.isoformat(), 'model_id':'market_devig_v1',
            'independent_model':False,'outcome_top1':m.get('top1'),
            'p_1x2':prob,'forecast_recorded_at_utc':at.isoformat(),
            'information_cutoff_utc':m.get('information_cutoff_utc'),
            'input_hash':str(m.get('input_hash',''))[:64]}


def atomic_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw=json.dumps(obj,ensure_ascii=False,indent=2,sort_keys=True)+'\n'
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,delete=False) as f:
        temp=f.name
        f.write(raw)
    os.replace(temp,path)


def generate(root:Path)->dict:
    preds=json.loads((root/'predictions/latest.json').read_text(encoding='utf-8'))
    archive=root/'docs/data/daily'
    collected={}
    for m in preds.get('matches',[]):
        clean=clean_match(m)
        if clean:
            collected.setdefault(clean['date_bjt'],[]).append(clean)
    count=0
    for date, matches in collected.items():
        path=archive/(date+'.json')
        if path.exists():
            old=json.loads(path.read_text(encoding='utf-8'))
        else:
            old={'schema_version':'TPlusDailyPrematchArchive.1','date_bjt':date,
                 'source_category':'T_market_implied_baseline_only',
                 'not_formal_score_evaluation':True,
                 'records':{}}
        records=old.setdefault('records',{})
        for m in matches:
            mid=m['t_match_id']
            obj=records.get(mid)
            if not obj:
                records[mid]={'first':m,'latest':m,'snapshots_observed':1}
            else:
                prior=aware(obj['latest']['forecast_recorded_at_utc'])
                now=aware(m['forecast_recorded_at_utc'])
                if now>prior:
                    obj['latest']=m
                    obj['snapshots_observed']=int(obj.get('snapshots_observed',1))+1
            count+=1
        atomic_json(path,old)
    idx={'schema_version':'TPlusDailyIndex.1','dates':[],'source':'archived pre-match market-only probabilities; results are tracked separately'}
    for p in sorted(archive.glob('????-??-??.json'),reverse=True):
        d=json.loads(p.read_text(encoding='utf-8'))
        idx['dates'].append({'date_bjt':p.stem,'match_count':len(d.get('records',{})),
                             'path':'data/daily/'+p.name})
    atomic_json(archive/'index.json',idx)
    return {'dates':len(idx['dates']),'current_snapshots':count}


if __name__=='__main__':
    print('Daily archive:',generate(Path(__file__).resolve().parents[1]))
