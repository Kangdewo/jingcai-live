import datetime as dt
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tplus_predict.runner import safe_slug
from tplus_results.verify import execute, verify_one, normalize_openligadb
UTC=dt.timezone.utc
KICK='2026-10-26T20:00:00+00:00'
NOW=dt.datetime(2026,10,26,23,0,tzinfo=UTC)
TID='t:2026-10-27:周一003'


def link():
    return {'t_match_id':TID,'kickoff_utc':KICK,'approved':True,
      'home':'塞维利亚','away':'奥萨苏纳','identity_evidence_urls':['https://example.org/official-fixture'],
      'openligadb':{'match_id':85433,'home_team_id':1139,'away_team_id':1279},
      'football_data':{'match_id':564721,'home_team_id':559,'away_team_id':79}}


def openliga(score=(2,0),finished=True):
    return {'matchID':85433,'matchDateTimeUTC':KICK,'team1':{'teamId':1139},'team2':{'teamId':1279},
       'matchIsFinished':finished,'matchResults':[{'resultTypeID':1,'pointsTeam1':1,'pointsTeam2':0},
       {'resultTypeID':2,'pointsTeam1':score[0],'pointsTeam2':score[1]}]}


def football(score=(2,0),finished=True):
    return {'id':564721,'utcDate':KICK,'homeTeam':{'id':559},'awayTeam':{'id':79},
       'status':'FINISHED' if finished else 'SCHEDULED','score':{'fullTime':{'home':score[0],'away':score[1]}}}


def files(root):
    slug=safe_slug(TID)
    rec={'t_match_id':TID,'kickoff_utc':KICK,'forecast_recorded_at_utc':'2026-10-26T19:50:00+00:00',
     'home':'塞维利亚','away':'奥萨苏纳','model_id':'market_devig_v1','p_1x2':{'home':.5,'draw':.2,'away':.3},'top1':'home'}
    p=root/'predictions'/'records'/slug/'snapshot.json';p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(rec))
    frozen=root/'predictions'/'freezes'/(slug+'.json');frozen.parent.mkdir(parents=True,exist_ok=True);frozen.write_text(json.dumps(rec))
    cfg=root/'predictions'/'result_links_approved.json';cfg.parent.mkdir(parents=True,exist_ok=True)
    cfg.write_text(json.dumps({'links':[link()]}))


class DualSourceTests(unittest.TestCase):
    def test_half_time_is_not_full_time(self):
        self.assertEqual(normalize_openligadb(openliga())['score'],(2,0))
        self.assertIsNone(normalize_openligadb({**openliga(),'matchResults':[]} )['score'])
    def test_full_positive_two_source_and_evaluation(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);files(root)
            def mock(url,token):
                return openliga() if 'openligadb' in url else football()
            stat=execute(root,NOW,token='dummy',fetcher=mock)
            self.assertEqual(stat['dual_source_verified_results'],1)
            self.assertEqual(stat['eligible_formal_pre_match_evaluations'],1)
            self.assertEqual(json.loads((root/'predictions'/'evaluation.json').read_text())['evaluations'][0]['top1_hit'],True)
    def test_disagreement_never_promotes(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);files(root)
            stat=execute(root,NOW,'dummy',lambda url,token:openliga() if 'openligadb' in url else football((1,0)))
            self.assertEqual(stat['dual_source_verified_results'],0)
            self.assertEqual(stat['checks'][0]['status'],'FULLTIME_SCORE_CONFLICT')
    def test_wrong_home_away_ids_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);files(root)
            o=openliga();o['team1']={'teamId':1279};o['team2']={'teamId':1139}
            stat=execute(root,NOW,'dummy',lambda url,token:o if 'openligadb' in url else football())
            self.assertEqual(stat['checks'][0]['status'],'IDENTITY_OR_FINISH_CONFLICT')
    def test_missing_key_does_not_fetch(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);files(root)
            stat=execute(root,NOW,'',lambda url,token: (_ for _ in ()).throw(AssertionError('Network should not be called')))
            self.assertEqual(stat['checks'][0]['status'],'FOOTBALL_DATA_API_KEY_NOT_CONFIGURED')
    def test_unknown_fixture_does_not_fetch(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'predictions').mkdir()
            (root/'predictions'/'result_links_approved.json').write_text(json.dumps({'links':[link()]}))
            stat=execute(root,NOW,'dummy',lambda url,token: (_ for _ in ()).throw(AssertionError('Network should not be called')))
            self.assertEqual(stat['checks'][0]['status'],'NO_MATCHING_PREMATCH_PREDICTION')
    def test_future_fixture_does_not_fetch(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);files(root)
            stat=execute(root,dt.datetime(2026,10,26,19,55,tzinfo=UTC),'dummy',lambda url,token: (_ for _ in ()).throw(AssertionError('Network should not be called')))
            self.assertEqual(stat['checks'][0]['status'],'AWAITING_FINAL_WHISTLE')
    def test_duplicate_links_do_not_duplicate_verified(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);files(root)
            path=root/'predictions'/'result_links_approved.json';path.write_text(json.dumps({'links':[link(),link()]}))
            stat=execute(root,NOW,'dummy',lambda url,token:openliga() if 'openligadb' in url else football())
            self.assertEqual(stat['dual_source_verified_results'],1)
            self.assertEqual(stat['checks'][1]['status'],'DUPLICATE_OR_INVALID_ID')
    def test_conflict_quarantines_old_verified(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);files(root)
            one=lambda url,token:openliga() if 'openligadb' in url else football()
            execute(root,NOW,'dummy',one)
            stat=execute(root,NOW+dt.timedelta(hours=1),'dummy',lambda url,token:openliga() if 'openligadb' in url else football((0,0)))
            self.assertEqual(stat['dual_source_verified_results'],0)
            self.assertEqual(stat['eligible_formal_pre_match_evaluations'],0)
    def test_no_links_status_honest(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'predictions').mkdir();(root/'predictions'/'result_links_approved.json').write_text('{"links":[]}')
            stat=execute(root,NOW,'',lambda url,token: (_ for _ in ()).throw(AssertionError('No fetch')))
            self.assertEqual(stat['checked_links'],0)
            self.assertEqual(stat['eligible_formal_pre_match_evaluations'],0)

if __name__=='__main__':unittest.main()
