import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from tplus_cloud.archive_daily import aware,clean_match,generate


def sample(clock='2026-10-27T08:20:00+00:00'):
    return {'model_id':'market_devig_v1','independent_of_market':False,
      't_match_id':'t:2026-10-27:周二001','home':'甲','away':'乙','league':'测试',
      'kickoff_utc':'2026-10-27T10:00:00+00:00', 'forecast_recorded_at_utc':clock,
      'top1':'home','p_1x2':{'home':.5,'draw':.3,'away':.2},'input_hash':'hash'}

class ArchiveTests(unittest.TestCase):
    def test_reject_after_kickoff(self):
        self.assertIsNone(clean_match(sample('2026-10-27T11:00:00+00:00')))
    def test_reject_fake_independent(self):
        s=sample();s['independent_of_market']=True
        self.assertIsNone(clean_match(s))
    def test_preserve_first_and_update_latest(self):
        with tempfile.TemporaryDirectory() as p:
            root=Path(p);(root/'predictions').mkdir()
            file=root/'predictions/latest.json'
            file.write_text(json.dumps({'matches':[sample()]},ensure_ascii=False))
            generate(root)
            updated=sample('2026-10-27T08:30:00+00:00')
            file.write_text(json.dumps({'matches':[updated]},ensure_ascii=False))
            generate(root)
            d=json.loads((root/'docs/data/daily/2026-10-27.json').read_text())
            r=d['records'][updated['t_match_id']]
            self.assertIn('08:20:00',r['first']['forecast_recorded_at_utc'])
            self.assertIn('08:30:00',r['latest']['forecast_recorded_at_utc'])
            self.assertEqual(r['snapshots_observed'],2)
    def test_no_duplicate_counts(self):
        with tempfile.TemporaryDirectory() as p:
            root=Path(p);(root/'predictions').mkdir()
            (root/'predictions/latest.json').write_text(json.dumps({'matches':[sample()]},ensure_ascii=False))
            generate(root);generate(root)
            d=json.loads((root/'docs/data/daily/2026-10-27.json').read_text())
            self.assertEqual(next(iter(d['records'].values()))['snapshots_observed'],1)

if __name__=='__main__':unittest.main()
