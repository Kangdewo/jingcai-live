# coding: utf-8
import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tplus_predict.market_analysis import market_probabilities, MARKETS, history_prior, analyze_row, run

NOW = dt.datetime(2026,10,26,18,40,tzinfo=dt.timezone.utc)

class HistoryMarketTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root/'model_feed').mkdir(); (self.root/'history_feed').mkdir()
        self.row = {
            't_match_id':'t:2026-10-27:周一003','source_match_key':'1003',
            'date_local':'2026-10-27','kickoff_clock_local':'04:00:00',
            'kickoff_timezone':'Asia/Shanghai','home':'塞维利亚','away':'奥萨苏纳','league':'西甲',
            'odds':{'had_h':1.7,'had_d':3.1,'had_a':4.6,
                    'goal':'-1','hhad_h':3.56,'hhad_d':2.87,'hhad_a':2.0,
                    **{'ttg_'+str(i):x for i,x in enumerate([11,5,4,4,6,12,23,42])},
                    **{'hf_'+a+b:10.0 for a in 'hda' for b in 'hda'},
                    **{'crs_'+k:40.0 for k,_ in MARKETS['exact_score']}}}
        self.feed = {'feed_type':'T_odds_research','generated_at_utc':'2026-10-26T18:39:00+00:00',
                     'upstream_updated_at_local':'2026-10-27 02:38:00','matches':[self.row]}
        self.hist = {'items':[
            {'league':'ESP1','year':'2024','matches':100,'ft_result_counts':{'home':50,'draw':25,'away':25},
             'total_goals_0_to_7plus':{'0':10,'1':10,'2':20,'3':25,'4':15,'5':10,'6':5,'7':5},
             'exact_score_frequency':{'1:1':25,'2:1':12}},
            {'league':'ESP1','year':'2025','matches':100,'ft_result_counts':{'home':40,'draw':30,'away':30},
             'total_goals_0_to_7plus':{'0':10,'1':10,'2':20,'3':25,'4':15,'5':10,'6':5,'7':5},
             'exact_score_frequency':{'1:1':15,'2:1':18}},
            {'league':'ESP1','year':'2026','matches':100,'ft_result_counts':{'home':100,'draw':0,'away':0},
             'total_goals_0_to_7plus':{'0':100},'exact_score_frequency':{'5:0':100}},
        ]}
        (self.root/'model_feed/latest.json').write_text(json.dumps(self.feed,ensure_ascii=False))
        (self.root/'history_feed/league_seasons.json').write_text(json.dumps(self.hist,ensure_ascii=False))

    def tearDown(self):
        self.tmp.cleanup()

    def test_market_groups(self):
        for market in ('spf','rqspf','total_goals','half_full','exact_score'):
            res=market_probabilities(self.row['odds'],MARKETS[market])
            self.assertIsNotNone(res, market)
            self.assertAlmostEqual(sum(res['probabilities'].values()),1,places=6)

    def test_partial_market_rejected(self):
        odds=dict(self.row['odds']);del odds['hf_hd']
        self.assertIsNone(market_probabilities(odds,MARKETS['half_full']))
        odds['had_h']=-1
        self.assertIsNone(market_probabilities(odds,MARKETS['spf']))

    def test_pre_year_filter(self):
        prior=history_prior('西甲',2026,self.hist['items'])
        self.assertEqual(prior['sample_size'],200)
        self.assertEqual(prior['selected_complete_prior_years'],[2025,2024])
        self.assertAlmostEqual(prior['ft_1x2']['home'],.45)
        self.assertNotIn('2026',str(prior['selected_complete_prior_years']))
        self.assertIsNone(history_prior('西甲',2024,self.hist['items']))

    def test_reject_old_data_and_post_kickoff(self):
        too_late=dt.datetime(2026,10,26,20,1,tzinfo=dt.timezone.utc)
        r,err=analyze_row(self.row,self.feed,too_late,self.hist)
        self.assertIsNone(r)
        self.assertIn(err,('AFTER_KICKOFF','FEED_STALE'))

    def test_publication_idempotence_and_naming(self):
        st=run(self.root,now=NOW)
        self.assertEqual(st['match_count'],1)
        self.assertEqual(st['history_league_prior_coverage'],1)
        self.assertEqual(st['new_immutable_analysis_records'],1)
        result=json.loads((self.root/'predictions/analysis_latest.json').read_text())
        match=result['matches'][0]
        self.assertEqual(match['five_markets_covered'],5)
        self.assertIsNone(match['official_005_prediction'])
        self.assertEqual(match['history_league_prior']['sample_size'],200)
        self.assertTrue((self.root/'predictions/analysis_status.json').exists())
        st2=run(self.root,now=NOW)
        self.assertEqual(st2['new_immutable_analysis_records'],0)

    def test_missing_market_does_not_fabricate(self):
        del self.row['odds']['hf_hh']
        rec,err=analyze_row(self.row,self.feed,NOW,self.hist)
        self.assertIsNone(err)
        self.assertNotIn('half_full',rec['market_odds_implied'])
        self.assertEqual(rec['five_markets_covered'],4)

    def test_no_unknown_league_guessing(self):
        self.assertIsNone(history_prior('欧冠',2026,self.hist['items']))

if __name__=='__main__': unittest.main()
