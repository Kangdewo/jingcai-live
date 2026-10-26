"""Use: python -m tplus_resultlink.cli check --config ... --evidence ... --out-dir ...

Reads live provider JSON only when explicitly run. Never commits to GitHub.
Never treats one provider, fixture identity, or an after-the-fact forecast as verified.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request
from datetime import datetime,timezone
from .core import iso, reconcile, market_baseline_review
from tplus_realdata.core import normalize_fd, normalize_openliga


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path, data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return path


def request_json(url,token=None):
    req=urllib.request.Request(url, headers={'User-Agent':'TPlusResultLink/0.6.2 (research)',
                                             'Accept':'application/json',
                                             **({'X-Auth-Token':token} if token else {})})
    with urllib.request.urlopen(req,timeout=25) as response:
        if response.status!=200:
            raise RuntimeError('HTTP_STATUS_NOT_200')
        content=response.read(7*1024*1024+1)
        if len(content)>7*1024*1024:
            raise RuntimeError('RESPONSE_TOO_LARGE')
        return json.loads(content.decode('utf-8-sig'))


def normalize_saved(file,provider,observed):
    document=read(file)
    if isinstance(document,dict) and document.get('schema_version')=='TPlusRealData.0.6':
        if document.get('provider')!=provider:raise ValueError('BAD_PROVIDER_IN_INPUT_FILE')
        return document['matches']
    if provider=='openligadb':
        return normalize_openliga(document if isinstance(document,list) else [document],observed)
    return normalize_fd(document,observed)


def make_report(config,evidence,primary,secondary,now):
    reviewed=reconcile(config,primary,secondary,now)
    score=market_baseline_review(reviewed,evidence,config.get('handicap_integer'))
    report={'schema_version':'TPlusMatch003Review.0.6.2','t_match_id':config['t_match_id'],
            'checked_at_utc':now,'result_review':reviewed,'research_market_baseline':score,
            'formal_model_005_evaluation':None,
            'formal_model_005_reason':'NO_INDEPENDENT_MODEL_005_OR_VALID_T15_FREEZE',
            'training_eligible':False,
            'official_prediction_freeze_changed':False,
            'note_cn':'仅提供赛前市场基准的研究级回顾；不能冒充真实005模型准确率。'}
    return report


def main():
    p=argparse.ArgumentParser(description='T+ v0.6.2 result verification; never changes formal predictions')
    p.add_argument('action',choices=['check'])
    p.add_argument('--config',default='evidence/match003_config.json')
    p.add_argument('--evidence',default='evidence/match003_prematch_evidence.json')
    p.add_argument('--openliga-file',help='Optional normalized pre-saved file, no network')
    p.add_argument('--football-data-file',help='Optional second provider response, no network')
    p.add_argument('--out-dir',default='output/match003_result_review')
    args=p.parse_args()
    cfg=read(args.config);ev=read(args.evidence)
    now=datetime.now(timezone.utc).isoformat()
    if ev.get('t_match_id')!=cfg['t_match_id'] or ev.get('match',{}).get('kickoff_utc')!=cfg['kickoff_utc']:
        p.error('EVIDENCE_MATCH_ID_OR_KICKOFF_MISMATCH')
    if iso(ev['market_baseline_from_existing_github_report']['forecast_recorded_at_utc']) >= iso(cfg['kickoff_utc']):
        p.error('MARKET_BASELINE_IS_NOT_PREMATCH')
    # The file option is intended for fixtures/testing. A local file must not be
    # considered a second independent live fetch without provenance verification.
    primary=None; secondary=[];issues=[];sources=[]
    if args.openliga_file:
        try:
            candidates=normalize_saved(args.openliga_file,'openligadb',now)
            candidates=[m for m in candidates if str(m.get('provider_match_id'))==str(cfg['openligadb_match_id'])]
            if len(candidates)!=1:raise ValueError('PRIMARY_ID_MISSING_OR_DUPLICATE')
            primary=candidates[0]
            sources.append({'provider':'openligadb','method':'LOCAL_FILE','path':args.openliga_file})
        except Exception as exc:
            issues.append('PRIMARY_LOCAL_FILE_ERROR: '+str(exc))
    else:
        try:
            raw=request_json('https://api.openligadb.de/getmatchdata/'+str(cfg['openligadb_match_id']))
            result=normalize_openliga([raw],now)
            if len(result)!=1: raise ValueError('PRIMARY_NORMALIZED_COUNT_NOT_ONE')
            primary=result[0]
            sources.append({'provider':'openligadb','method':'HTTPS_LIVE',
                            'source_url':primary['source_url']})
        except (ValueError,urllib.error.HTTPError,urllib.error.URLError,TimeoutError) as exc:
            issues.append('PRIMARY_FETCH_ERROR: '+str(exc))
    if args.football_data_file:
        try:
            secondary=normalize_saved(args.football_data_file,'football_data',now)
            sources.append({'provider':'football_data','method':'LOCAL_FILE','path':args.football_data_file})
        except Exception as exc:
            issues.append('SECONDARY_FILE_ERROR: '+str(exc))
    elif os.getenv('FOOTBALL_DATA_API_KEY','').strip():
        try:
            api=f'https://api.football-data.org/v4/competitions/{cfg["league_code_football_data"]}/matches?season={cfg["season"]}'
            raw=request_json(api,os.environ['FOOTBALL_DATA_API_KEY'].strip())
            secondary=normalize_fd(raw,now)
            sources.append({'provider':'football_data','method':'HTTPS_LIVE','source_url':api})
        except (ValueError,urllib.error.HTTPError,urllib.error.URLError,TimeoutError) as exc:
            issues.append('SECONDARY_FETCH_ERROR: '+str(exc))
    else:
        issues.append('FOOTBALL_DATA_API_KEY_NOT_CONFIGURED')
    # Never promote local arbitrary samples to production independent observations.
    report=make_report(cfg,ev,primary,secondary,now)
    if report['result_review']['ft_verified'] and any(x['method']=='LOCAL_FILE' for x in sources):
        report['result_review']['ft_verified']=False
        report['result_review']['ht_verified']=False
        report['result_review']['status']='LOCAL_FILE_RESULT_REQUIRES_SOURCE_PROVENANCE'
        report['research_market_baseline']=market_baseline_review(report['result_review'],ev,cfg.get('handicap_integer'))
    report['fetch_issues']=issues;report['sources_accessed']=sources
    content=json.dumps(report,sort_keys=True,ensure_ascii=False,default=str).encode('utf8')
    # Snapshot uses unique content digest. Do not overwrite an earlier observation.
    suffix=hashlib.sha256(content).hexdigest()[:16]
    folder=Path(args.out_dir)
    archive=folder/'snapshots'/f'{now.replace(":","").replace("+", "_")[:19]}_{suffix}.json'
    write(archive,report)
    write(folder/'latest_review.json',report)
    print('T+ v0.6.2 Match ID:',cfg['t_match_id'])
    print('Score verification:',report['result_review']['status'])
    print('Independent FT sources:',report['result_review']['source_count_verified_ft'])
    print('Research market evaluation:',report['research_market_baseline']['evaluated'])
    print('Secondary candidates:',json.dumps(report['result_review']['second_source_candidates'],ensure_ascii=False))
    print('Issues:',', '.join(issues) if issues else 'none')
    print('Latest report:',folder/'latest_review.json')
    print('Immutable snapshot:',archive)
    if report['result_review']['status']=='IDENTITY_CONFLICT':
        return 2
    return 0

if __name__=='__main__':
    sys.exit(main())
