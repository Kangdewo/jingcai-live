import datetime as dt
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tplus_predict.runner import (run,choose,probabilities,kickoff_utc,safe_slug,parse_upstream,UTC)

NOW=dt.datetime(2026,10,26,18,40,tzinfo=UTC)

class TestAutoPredict(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        (self.root/'model_feed').mkdir()
        self.row={'t_match_id':'t:2026-10-27:周一001','source_match_key':'1001','date_local':'2026-10-27',
                  'kickoff_clock_local':'02:45:00','kickoff_timezone':'Asia/Shanghai',
                  'home':'圣克拉拉','away':'本菲卡','league':'葡超',
                  'odds':{'had_h':8.5,'had_d':4.1,'had_a':1.24}}
        self.feed={'schema_version':'1.0','feed_type':'T_odds_research',
          'generated_at_utc':'2026-10-26T18:39:00+00:00',
          'upstream_updated_at_local':'2026-10-27 02:38:00',
          'matches':[self.row]}
        self.save_feed()

    def tearDown(self):self.temp.cleanup()

    def save_feed(self):
        (self.root/'model_feed'/'latest.json').write_text(json.dumps(self.feed,ensure_ascii=False),encoding='utf8')

    def test_math(self):
        probs,_=probabilities(self.row['odds'])
        self.assertAlmostEqual(sum(probs.values()),1,places=6)
        self.assertEqual(max(probs,key=probs.get),'away')
        self.assertIsNone(probabilities({'had_h':0,'had_d':3,'had_a':4}))

    def test_time(self):
        self.assertEqual(kickoff_utc(self.row),dt.datetime(2026,10,26,18,45,tzinfo=UTC))
        self.assertEqual(parse_upstream('2026-10-27 02:38:00'),dt.datetime(2026,10,26,18,38,tzinfo=UTC))

    def test_nominal_and_freeze(self):
        state=run(self.root,now=NOW)
        self.assertEqual(state['valid_pre_match_forecasts'],1)
        self.assertEqual(state['new_freezes'],1)
        self.assertEqual(state['new_immutable_snapshots'],1)
        rec=json.loads((self.root/'predictions'/'latest.json').read_text())['matches'][0]
        self.assertFalse(rec['independent_of_market'])
        self.assertIsNone(rec['xg_source'])
        freeze=self.root/'predictions'/'freezes'/(safe_slug(rec['t_match_id'])+'.json')
        self.assertTrue(freeze.exists())
        self.assertFalse(json.loads(freeze.read_text())['claimed_exact_T_minus_15'])
        state2=run(self.root,now=NOW+dt.timedelta(seconds=15))
        self.assertEqual(state2['new_freezes'],0)
        self.assertEqual(state2['new_immutable_snapshots'],0)

    def test_postkickoff_cannot_backfill(self):
        state=run(self.root,now=NOW+dt.timedelta(minutes=10))
        self.assertEqual(state['valid_pre_match_forecasts'],0)
        self.assertEqual(state['new_freezes'],0)
        self.assertEqual(state['skipped_by_reason']['AFTER_KICKOFF'],1)

    def test_source_after_kickoff(self):
        self.feed['upstream_updated_at_local']='2026-10-27 03:01:00'
        self.save_feed()
        state=run(self.root,now=NOW)
        self.assertEqual(state['valid_pre_match_forecasts'],0)

    def test_stale(self):
        self.feed['generated_at_utc']='2026-10-26T10:00:00+00:00'
        self.feed['upstream_updated_at_local']='2026-10-26 17:59:00'
        self.save_feed()
        state=run(self.root,now=NOW)
        self.assertEqual(state['skipped_by_reason'].get('FEED_STALE'),1)

    def test_verified_result_scoring_only(self):
        run(self.root,now=NOW)
        outcome={'results':[{'t_match_id':self.row['t_match_id'],'home_goals':0,'away_goals':2,
            'status':'FT','source_url':'https://example.com/verified-final',
            'verified_at_utc':'2026-10-27T02:30:00+00:00'}]}
        (self.root/'predictions'/'results_verified.json').write_text(json.dumps(outcome))
        state=run(self.root,now=NOW+dt.timedelta(hours=10))
        self.assertEqual(state['verified_results_evaluated'],1)
        ev=json.loads((self.root/'predictions'/'evaluation.json').read_text())
        self.assertIsNotNone(ev['summary']['mean_brier'])
        self.assertEqual(ev['evaluations'][0]['verified_result']['outcome'],'away')

    def test_result_not_verified_no_score(self):
        run(self.root,now=NOW)
        outcome={'results':[{'t_match_id':self.row['t_match_id'],'home_goals':0,'away_goals':2,'status':'FT',
                              'verified_at_utc':'2026-10-27T02:30:00+00:00'}]}
        (self.root/'predictions'/'results_verified.json').write_text(json.dumps(outcome))
        state=run(self.root,now=NOW+dt.timedelta(hours=10))
        self.assertEqual(state['verified_results_evaluated'],0)

if __name__=='__main__':unittest.main()
