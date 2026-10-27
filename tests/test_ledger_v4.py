import unittest,sys,tempfile,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tplus_cloud.build_ledger_index import build,validate_day
ROOT=Path(__file__).resolve().parents[1]

class LedgerTests(unittest.TestCase):
    def test_three_historical_days_separate(self):
        with tempfile.TemporaryDirectory() as td:
            o=build(ROOT/'docs/data/ledger/days',Path(td)/'index.json')
        self.assertEqual([x['date_bjt'] for x in o['dates'][:3]],['2026-10-24','2026-10-25','2026-10-26'])
        points=o['cumulative_points']
        october26=next(x for x in points if x['date_bjt']=='2026-10-26')
        self.assertAlmostEqual(october26['stake_cny'],242)
        self.assertAlmostEqual(october26['theoretical_return_cny'],195.48)
        self.assertAlmostEqual(october26['net_cny'],-46.52)
        self.assertAlmostEqual(o['cumulative']['stake_cny'],sum(x['summary']['stake_cny'] for x in o['dates'] if x['summary']))
        self.assertAlmostEqual(o['cumulative']['theoretical_return_cny'],sum(x['summary']['theoretical_return_cny'] for x in o['dates'] if x['summary']))
    def test_real_bets_from_archived_20261026_review(self):
        d=json.loads((ROOT/'docs/data/ledger/days/2026-10-26.json').read_text())
        self.assertEqual(len(d['tickets']),7)
        self.assertEqual(len(d['bets']),58)
        self.assertEqual(sum(b['theoretical_payout'] for b in d['bets']),112.25)
        self.assertEqual(sum(b['hit'] for b in d['bets']),4)
        self.assertTrue(any(r['purchase_status']=='not_purchased' for r in d['recommendations']))
    def test_model_labels_do_not_promote_shadow(self):
        for date in ['2026-10-24','2026-10-25','2026-10-26']:
            d=json.loads((ROOT/f'docs/data/ledger/days/{date}.json').read_text())
            validate_day(d,date)
            self.assertTrue(d['not_formal_ai_evaluation'])
            self.assertFalse(d['summary']['cashout_verified'])
        d=json.loads((ROOT/'docs/data/ledger/days/2026-10-26.json').read_text())
        self.assertEqual(next(t for t in d['tickets'] if t['id']=='D')['attribution_quality'],'provisional_only')
    def test_unsettled_day_not_zero_loss(self):
        d=json.loads((ROOT/'docs/data/ledger/days/2026-10-27.json').read_text())
        self.assertIn(validate_day(d,'2026-10-27')['status'],('pending','reviewed_theoretical','pending_settlement'))
    def test_unsettled_tickets_are_visible_but_excluded_from_returns(self):
        d=json.loads((ROOT/'docs/data/ledger/days/2026-10-27.json').read_text())
        d['tickets']=[{'id':'H01','stake':12,'bet_count':6,'winning_bets':None,
            'theoretical_return':None,'theoretical_net':None,'attribution_quality':'unattributed'}]
        d['summary']={'tickets':1,'bet_units':6,'stake_cny':12,
                      'theoretical_return_cny':None,'theoretical_net_cny':None,
                      'fully_reconciled':False,'cashout_verified':False}
        self.assertEqual(validate_day(d,'2026-10-27')['status'],'pending_settlement')
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'days';p.mkdir()
            (p/'2026-10-27.json').write_text(json.dumps(d))
            out=build(p,Path(td)/'index.json')
            self.assertIsNone(out['dates'][0]['summary']['theoretical_net_cny'])
            self.assertEqual(out['cumulative']['settled_days'],0)
            self.assertEqual(out['cumulative']['net_cny'],0)

    def test_mismatch_rejected(self):
        d=json.loads((ROOT/'docs/data/ledger/days/2026-10-26.json').read_text())
        d['tickets'][0]['stake']=22.01
        with self.assertRaisesRegex(ValueError,'STAKE_VS_BET_UNIT'):
            validate_day(d,'2026-10-26')
    def test_no_identifying_ticket_material(self):
        data=(ROOT/'docs/data/ledger/days/2026-10-26.json').read_text()
        for word in ['photo_sha256','photo_file','Kangdeword','secret','API_KEY','.jpg']:
            self.assertNotIn(word,data)

if __name__=='__main__':unittest.main()
