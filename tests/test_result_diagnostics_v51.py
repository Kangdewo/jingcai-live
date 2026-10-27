import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
import urllib.error

from tplus_results.diagnose_v51 import (
    diagnose, parse_openliga, parse_football_data, inspect_observation,
    error_info, _extract_espn_candidate, OPENLIGA, FOOTBALL, ESPN, UTC
)

KICK = '2026-10-26T20:00:00+00:00'
NOW = dt.datetime(2026, 10, 27, 15, 0, tzinfo=UTC)
CONFIG = {
    'approved': True, 't_match_id': 't:2026-10-27:周一003',
    'home': '塞维利亚', 'away': '奥萨苏纳', 'kickoff_utc': KICK,
    'openligadb': {'match_id': 85433, 'home_team_id': 1139, 'away_team_id': 1279},
    'football_data': {'match_id': 564721, 'home_team_id': 559, 'away_team_id': 79}
}
OPEN_STALE = {
    'matchID': 85433, 'matchDateTimeUTC': KICK,
    'team1': {'teamId': 1139}, 'team2': {'teamId': 1279},
    'matchIsFinished': False, 'matchResults': [],
    'lastUpdateDateTime': '2026-10-17T09:08:31.18'
}
FOOT_FINISH = {
    'id': 564721, 'utcDate': KICK,
    'homeTeam': {'id': 559}, 'awayTeam': {'id': 79},
    'status': 'FINISHED', 'score': {'fullTime': {'home': 2, 'away': 0}},
    'lastUpdated': '2026-10-27T04:00:00Z'
}


class DiagnosticsV51Tests(unittest.TestCase):
    def test_finished_normalizer(self):
        p = parse_football_data(FOOT_FINISH)
        self.assertEqual([2, 0], p['score'])
        self.assertTrue(p['finished'])

    def test_openliga_missing_score_not_zero_zero(self):
        p = parse_openliga(OPEN_STALE)
        self.assertIsNone(p['score'])
        self.assertFalse(p['finished'])

    def test_stale_openliga_detection(self):
        p = parse_openliga(OPEN_STALE)
        check = inspect_observation(p, CONFIG['openligadb'], dt.datetime.fromisoformat(KICK), NOW)
        self.assertEqual('SOURCE_STALE_NOT_FINISHED', check['state'])
        self.assertGreater(check['age_hours_approx'], 48)

    def test_wrong_side_rejected(self):
        p = parse_openliga(OPEN_STALE)
        p['home_id'], p['away_id'] = p['away_id'], p['home_id']
        self.assertEqual('IDENTITY_MISMATCH', inspect_observation(p, CONFIG['openligadb'],
                        dt.datetime.fromisoformat(KICK), NOW)['state'])

    def test_no_half_time_as_full_time(self):
        raw = dict(OPEN_STALE, matchResults=[{
            'resultTypeID': 1, 'pointsTeam1': 1, 'pointsTeam2': 0}])
        self.assertIsNone(parse_openliga(raw)['score'])

    def test_http_error_scrubbed(self):
        error = urllib.error.HTTPError('https://api.football-data.org/v4/matches/564721', 403,
                                       'access token secret_should_not_appear', None, None)
        out = error_info(error)
        self.assertEqual('HTTP_ERROR', out['state'])
        self.assertEqual(403, out['http_status'])
        self.assertNotIn('secret_should_not_appear', json.dumps(out))

    def test_no_token_never_fetches_football_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'predictions').mkdir()
            (root / 'predictions/result_links_approved.json').write_text(
                json.dumps({'links': [CONFIG]}, ensure_ascii=False), encoding='utf-8')
            calls=[]
            def fetcher(url, token):
                calls.append(url)
                if url.startswith(OPENLIGA): return OPEN_STALE
                raise AssertionError('should not contact football-data without token')
            output = diagnose(root, now=NOW, token='', fetcher=fetcher)
            self.assertEqual(1, output['probed_links'])
            self.assertEqual('SECRET_MISSING', output['matches'][0]['sources']['football_data']['state'])
            self.assertEqual(1, len(calls))

    def test_both_sources_checked_even_if_first_not_finished(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'predictions').mkdir()
            (root / 'predictions/result_links_approved.json').write_text(
                json.dumps({'links': [CONFIG]}, ensure_ascii=False), encoding='utf-8')
            calls=[]
            def fetcher(url, token):
                calls.append((url, token))
                if url.startswith(OPENLIGA): return OPEN_STALE
                if url.startswith(FOOTBALL):
                    raise urllib.error.HTTPError(url, 403, 'unavailable', None, None)
                raise AssertionError('disallowed')
            output = diagnose(root, now=NOW, token='private-token', fetcher=fetcher)
            sources=output['matches'][0]['sources']
            self.assertEqual(2, len(calls))
            self.assertEqual('HTTP_ERROR', sources['football_data']['state'])
            self.assertEqual(403, sources['football_data']['http_status'])
            self.assertNotIn('private-token', json.dumps(output))
            self.assertFalse(output['matches'][0]['automatic_result_certified_by_this_module'])
            self.assertTrue((root/'docs/data/results/diagnostics.json').is_file())
            self.assertFalse((root/'predictions/results_verified.json').exists())

    def test_missing_espn_ids_keeps_review_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'predictions').mkdir()
            (root/'predictions/result_links_approved.json').write_text(
                json.dumps({'links':[CONFIG]},ensure_ascii=False), encoding='utf-8')
            (root/'predictions/alternative_sources_candidates.json').write_text(
                json.dumps({'candidates':[{'t_match_id':CONFIG['t_match_id'],
                  'provider':'espn','event_id':'401882828','approved_for_diagnostic':False}]}),encoding='utf-8')
            def fetcher(url, token):
                self.assertFalse(url.startswith(ESPN))
                return OPEN_STALE if url.startswith(OPENLIGA) else FOOT_FINISH
            out=diagnose(root,now=NOW,token='hidden',fetcher=fetcher)
            self.assertEqual('ALT_ID_REVIEW_REQUIRED',out['matches'][0]['alternative']['state'])

    def test_espn_match_id_conflict_not_promoted(self):
        approved={'event_id':'401882828','home_team_id':9,'away_team_id':10,'kickoff_utc':KICK}
        remote={'header':{'id':'bad','competitions':[{'date':KICK,'competitors':[]}]}}
        self.assertEqual('ALT_ID_MISMATCH',_extract_espn_candidate(remote,approved)['state'])

    def test_no_links_does_not_touch_formal_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'predictions').mkdir()
            (root/'predictions/results_verified.json').write_text('SENTINEL',encoding='utf-8')
            out=diagnose(root,now=NOW,token='hidden',fetcher=lambda *x: 1)
            self.assertEqual([],out['matches'])
            self.assertEqual('SENTINEL',(root/'predictions/results_verified.json').read_text())


if __name__ == '__main__': unittest.main()
