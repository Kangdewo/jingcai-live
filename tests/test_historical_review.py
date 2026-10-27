"""Checks the sanitised 2026-10-26 user-approved historical report.

NOT a test of lottery official redemption or T+ two-source result verification.
"""
from pathlib import Path
import json
import unittest

ROOT=Path(__file__).resolve().parents[1]

class HistoryReviewContract(unittest.TestCase):
    def setUp(self):
        self.d=json.loads((ROOT/'docs/data/reviews/2026-10-26.json').read_text(encoding='utf-8'))
    def test_review_does_not_claim_formal_verification(self):
        self.assertTrue(self.d['source_separation']['do_not_overwrite_formal_evaluation'])
        self.assertFalse(self.d['summary']['cashout_verified'])
        for m in self.d['matches']:
            self.assertEqual(m['result']['source_count_for_formal_dual_verification'],0)
            self.assertFalse(m['result']['formal_evaluation_eligible'])
            self.assertFalse(m['baseline']['is_independent_model'])
    def test_four_reconstructed_scores(self):
        self.assertEqual([m['result']['ft'] for m in self.d['matches']],['1:2','1:1','2:0','3:2'])
        self.assertEqual(sum(x['checks']['baseline_top1_hit'] for x in self.d['matches']),3)
    def test_all_frozen_sp_bets_reconcile(self):
        bets=self.d['bets'];tickets=self.d['tickets'];score={m['code']:m['result']['ft'] for m in self.d['matches']}
        self.assertEqual(len(tickets),7);self.assertEqual(len(bets),58)
        self.assertEqual(sum(t['stake'] for t in tickets),116)
        for b in bets:
            hit=all(score[l['code']]==l['score'] for l in b['legs'])
            pay=round(b['stake']*__import__('math').prod(l['sp'] for l in b['legs'])+1e-6,2) if hit else 0
            self.assertEqual(b['hit'],hit)
            self.assertAlmostEqual(b['theoretical_payout'],pay,places=2)
        self.assertEqual(sum(b['hit'] for b in bets),4)
        self.assertAlmostEqual(sum(b['theoretical_payout'] for b in bets),112.25,places=2)
        self.assertAlmostEqual(sum(t['theoretical_net'] for t in tickets),-3.75,places=2)
    def test_public_data_without_photo_filenames(self):
        text=json.dumps(self.d,ensure_ascii=False)
        self.assertNotIn('photo_sha256',text)
        self.assertNotIn('photo_file',text)
        self.assertNotIn('.jpg',text)

if __name__=='__main__':unittest.main()
