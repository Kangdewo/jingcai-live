"""Build public, T-origin-only, timestamped model feeds from existing repository snapshots.
No API keys, football-data.org data, API-Football data, or private database are exported.
"""
import argparse, datetime as dt, hashlib, json, os, pathlib, sys
UTC=dt.timezone.utc
ROOT=pathlib.Path(__file__).resolve().parents[1]
OUT=ROOT/'model_feed'

def utcnow(): return dt.datetime.now(UTC).isoformat(timespec='seconds')
def load(name):
    p=ROOT/name
    try: return json.loads(p.read_text(encoding='utf-8'))
    except (OSError,ValueError) as exc: raise RuntimeError(f'Missing or invalid {name}: {exc}') from exc

def parse_time(value):
    if not value:return None
    try:
        obj=dt.datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return obj.astimezone(UTC).isoformat() if obj.tzinfo else None
    except ValueError:return None

def build():
    latest=load('odds_latest.json'); hist=load('odds_history.json'); freeze=load('odds_t15.json')
    status=load('status.json')
    now=utcnow(); new=latest.get('matches') or {}
    if not isinstance(new,dict):raise RuntimeError('odds_latest.matches must be an object')
    # The source uses Beijing-style local timestamps without explicit offset.
    # Do not manufacture UTC capture times from naive legacy text.
    records=[]
    for key, m in sorted(new.items()):
        if not isinstance(m,dict):continue
        name=m.get('numStr'); date=m.get('mDate');
        if not name or not date:continue
        # Preserve full source fields to avoid silently dropping the six lottery markets.
        odds={k:v for k,v in m.items() if k not in ('home','away','league','numStr','mDate','mTime')}
        records.append({'t_match_id':f't:{date}:{name}','source_match_key':str(key),
            'league':m.get('league'),'home':m.get('home'),'away':m.get('away'),
            'date_local':date,'kickoff_clock_local':m.get('mTime'),
            'kickoff_timezone':'Asia/Shanghai','source':'jingcai-live', 'odds':odds})
    src_at=latest.get('updated_at')
    content={'schema_version':'1.0','feed_type':'T_odds_research','generated_at_utc':now,
        'upstream_updated_at_local':src_at,'upstream_timezone_assumed':'Asia/Shanghai',
        'timestamp_status':'UPSTREAM_NAIVE_LOCAL_NOT_VERIFIED_UTC',
        'match_count':len(records),'data_policy':{'permitted_sources':['user_owned_T_repository_only'],
        'excluded':['api_football','paid_data','secrets','personal_data','private_match_database'],
        'market_odds_are_not_independent_xg':True},
        'limitations':['No verified independent xG or lineups','Do not infer new data from missing fields',
        'Current snapshot is not an immutable historical pre-match freeze'], 'matches':records}
    OUT.mkdir(exist_ok=True)
    result=json.dumps(content,ensure_ascii=False,indent=2)+'\n'
    target=OUT/'latest.json'
    target.write_text(result,encoding='utf-8')
    # Timestamped archive of source snapshot, only when content changes, bounded by a content digest.
    immutable_payload={'upstream_updated_at_local':src_at,'matches':records}
    digest=hashlib.sha256(json.dumps(immutable_payload,ensure_ascii=False,sort_keys=True).encode()).hexdigest()[:16]
    archive=OUT/'snapshots'/f'{digest}.json';archive.parent.mkdir(exist_ok=True)
    if not archive.exists():archive.write_text(json.dumps({'archived_at_utc':now,'source_snapshot':immutable_payload},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    feed_status={'schema_version':'1.0','generated_at_utc':now,'upstream_updated_at_local':src_at,
                 'source_status':status.get('last_error'),'match_count':len(records),
                 'snapshot_id':digest,'independent_xg_coverage':0,'lineup_coverage':0,
                 'verified_tplus_links':'not imported to public feed','is_prediction':False}
    (OUT/'status.json').write_text(json.dumps(feed_status,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (OUT/'README.md').write_text('# T+ Public Model Feed\n\nStatic read-only source: original T lottery odds. No private API-Sports data.\n\n' +
      'Use latest.json for currently published snapshot, status.json for freshness, snapshots/ for content-hash archive.\n'+
      'Always cite source times, distinguish odds from team xG, and never treat latest as a historical freeze.\n',encoding='utf-8')
    print(f'Produced {len(records)} matches; snapshot={digest}; output={OUT}')
    return content
if __name__=='__main__':build()
