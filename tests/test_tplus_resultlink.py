import copy
import json
import unittest
from pathlib import Path
from tplus_resultlink.core import (reconcile, market_baseline_review, derive_labels,
                                    identity_check,discover_secondary, iso, VerificationError)
ROOT=Path(__file__).resolve().parents[1]
CONFIG=json.loads((ROOT/'evidence/match003_config.json').read_text(encoding='utf-8'))
EVID=json.loads((ROOT/'evidence/match003_prematch_evidence.json').read_text(encoding='utf-8'))

def p(finished=True,ft=None,ht=None):
    return {'provider':'openligadb','provider_match_id':'85433','home_provider_id':'1139',
            'away_provider_id':'1279','home':'FC Sevilla','away':'CA Osasuna',
            'kickoff_utc':'2026-10-26T20:00:00+00:00','observed_at_utc':'2026-10-26T23:00:00+00:00',
            'finished':finished,'full_time':ft if ft is not None else [2,1],
            'half_time':ht if ht is not None else [1,0],
            'source_url':'https://api.openligadb.de/getmatchdata/85433'}

def f(ft=None,ht=None):
    return {'provider':'football_data','provider_match_id':'999999','home_provider_id':'265',
            'away_provider_id':'79','home':'Sevilla FC','away':'CA Osasuna',
            'kickoff_utc':'2026-10-26T20:00:00+00:00','observed_at_utc':'2026-10-26T23:01:00+00:00',
            'finished':True,'full_time':ft if ft is not None else [2,1],
            'half_time':ht if ht is not None else [1,0],
            'source_url':'https://api.football-data.org/v4/matches/999999'}

def approved():
    c=copy.deepcopy(CONFIG)
    c['football_data_approved_link']={'identity_verified':True,'provider_match_id':'999999',
                                      'evidence_url':'https://www.football-data.org/documentation/api'}
    return c

class MatchLinkTests(unittest.TestCase):
    def test_aware_time_only(self):
        with self.assertRaises(VerificationError): iso('2026-10-26T20:00:00')
    def test_identity_correct(self):
        self.assertTrue(identity_check(p(),CONFIG,'openligadb')[0])
    def test_different_openliga_id_rejected(self):
        q=p();q['provider_match_id']='85434'
        self.assertFalse(identity_check(q,CONFIG,'openligadb')[0])
    def test_swapped_teams_rejected(self):
        q=p();q['home'],q['away']=q['away'],q['home']
        self.assertFalse(identity_check(q,CONFIG,'openligadb')[0])
    def test_discover_second_never_auto_approves(self):
        r=discover_secondary([f()],CONFIG)
        self.assertEqual(len(r),1)
        self.assertEqual(r[0]['identity_status'],'REQUIRES_HUMAN_APPROVAL')
    def test_before_kickoff_no_result(self):
        q=reconcile(approved(),p(),[f()],'2026-10-26T19:00:00Z')
        self.assertFalse(q['ft_verified']);self.assertEqual(q['status'],'WAITING_FOR_KICKOFF')
    def test_single_source_cannot_verify(self):
        q=reconcile(CONFIG,p(),[],'2026-10-26T23:30:00Z')
        self.assertFalse(q['ft_verified']);self.assertEqual(q['status'],'SECOND_SOURCE_REQUIRED')
    def test_second_source_cannot_auto_authorize(self):
        q=reconcile(CONFIG,p(),[f()],'2026-10-26T23:30:00Z')
        self.assertFalse(q['ft_verified']);self.assertEqual(q['status'],'SECOND_SOURCE_ID_REQUIRES_APPROVAL')
    def test_approved_two_consistent_full_time(self):
        q=reconcile(approved(),p(),[f()],'2026-10-26T23:30:00Z')
        self.assertTrue(q['ft_verified']);self.assertTrue(q['ht_verified'])
        self.assertEqual(q['source_count_verified_ft'],2)
    def test_conflict_full_time_blocked(self):
        q=reconcile(approved(),p(),[f(ft=[3,1])],'2026-10-26T23:30:00Z')
        self.assertFalse(q['ft_verified']);self.assertEqual(q['status'],'FULL_TIME_CONFLICT')
    def test_conflict_half_time_not_verified(self):
        q=reconcile(approved(),p(),[f(ht=[0,0])],'2026-10-26T23:30:00Z')
        self.assertTrue(q['ft_verified']);self.assertFalse(q['ht_verified'])
        self.assertEqual(q['status'],'FT_VERIFIED_HT_CONFLICT')
    def test_future_observation_blocked(self):
        q=p();q['observed_at_utc']='2026-10-26T18:00:00Z'
        t=reconcile(approved(),q,[f()],'2026-10-26T23:30:00Z')
        self.assertFalse(t['ft_verified'])
    def test_secondary_kickoff_change_blocked(self):
        q=f();q['kickoff_utc']='2026-10-27T01:30:00Z'
        t=reconcile(approved(),p(),[q],'2026-10-26T23:30:00Z')
        self.assertEqual(t['status'],'IDENTITY_CONFLICT')
    def test_missing_half_time_no_half_full(self):
        q=f();q['half_time']=None
        t=reconcile(approved(),p(),[q],'2026-10-26T23:30:00Z')
        self.assertTrue(t['ft_verified']);self.assertFalse(t['ht_verified'])
        self.assertNotIn('half_full',derive_labels(t,-1))
    def test_handicap_and_market_review(self):
        t=reconcile(approved(),p(),[f()],'2026-10-26T23:30:00Z')
        score=market_baseline_review(t,EVID,-1)
        self.assertTrue(score['evaluated'])
        self.assertEqual(score['labels']['rqspf'],'draw')
        self.assertEqual(score['labels']['spf'],'home')
        self.assertTrue(score['spf_top1_hit'])
        self.assertTrue(score['not_formal_t15_freeze'])
    def test_unverified_no_market_accuracy(self):
        t=reconcile(CONFIG,p(),[],'2026-10-26T23:30:00Z')
        score=market_baseline_review(t,EVID,-1)
        self.assertFalse(score['evaluated']);self.assertIsNone(score['spf_top1_hit'])
    def test_market_baseline_after_kickoff_rejected(self):
        e=copy.deepcopy(EVID)
        e['market_baseline_from_existing_github_report']['forecast_recorded_at_utc']='2026-10-26T21:00:00Z'
        t=reconcile(approved(),p(),[f()],'2026-10-26T23:30:00Z')
        score=market_baseline_review(t,e,-1)
        self.assertFalse(score['evaluated'])

if __name__=='__main__': unittest.main()
