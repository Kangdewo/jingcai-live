import json, tempfile, pathlib, subprocess, sys, shutil
src=pathlib.Path(__file__).resolve().parents[1]/'tplus_cloud'/'build.py'
with tempfile.TemporaryDirectory() as t:
 p=pathlib.Path(t);(p/'tplus_cloud').mkdir();shutil.copyfile(src,p/'tplus_cloud'/'build.py')
 (p/'odds_latest.json').write_text(json.dumps({'updated_at':'2026-10-26 17:00:00','matches':{'1001':{'numStr':'周一001','mDate':'2026-10-27','home':'A','away':'B','mTime':'02:45:00','league':'test','had_h':1.5}}}),encoding='utf8')
 (p/'odds_history.json').write_text('[]',encoding='utf8');(p/'odds_t15.json').write_text('{}',encoding='utf8');(p/'status.json').write_text('{}',encoding='utf8')
 subprocess.run([sys.executable,str(p/'tplus_cloud'/'build.py')],check=True)
 out=json.loads((p/'model_feed'/'latest.json').read_text());assert out['match_count']==1
 assert out['matches'][0]['odds']['had_h']==1.5
 assert out['timestamp_status']=='UPSTREAM_NAIVE_LOCAL_NOT_VERIFIED_UTC'
 assert not any('api_key' in k.lower() for k in out)
 assert len(list((p/'model_feed'/'snapshots').glob('*.json')))==1
 print('PASS: T-only export, timestamps, immutable snapshot, no credentials')
