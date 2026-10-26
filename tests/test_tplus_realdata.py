import copy
import unittest
from tplus_realdata.core import (
    normalize_fd, normalize_openliga, timestamp, asof_match_studies,
    match_results_by_links, read_normalized, competition_standings_asof, ContractError
)

OBS = '2026-10-26T12:00:00+00:00'


def fd_rows():
    return normalize_fd({'competition':{'name':'TEST'},'matches':[
        {'id':101,'utcDate':'2026-10-20T12:00:00Z','status':'FINISHED',
         'homeTeam':{'id':1,'name':'A'},'awayTeam':{'id':2,'name':'B'},
         'score':{'fullTime':{'home':2,'away':1},'halfTime':{'home':1,'away':0}}},
        {'id':102,'utcDate':'2026-10-30T12:00:00Z','status':'SCHEDULED',
         'homeTeam':{'id':1,'name':'A'},'awayTeam':{'id':2,'name':'B'},
         'score':{'fullTime':{'home':None,'away':None}}}
    ]},OBS)


def ol_rows():
    return normalize_openliga([
        {'matchID':201,'matchDateTimeUTC':'2026-10-20T12:00:00','matchIsFinished':True,
         'team1':{'teamId':51,'teamName':'A'},'team2':{'teamId':52,'teamName':'B'},
         'matchResults':[{'resultTypeID':1,'pointsTeam1':1,'pointsTeam2':0},
                         {'resultTypeID':2,'pointsTeam1':2,'pointsTeam2':1}]},
        {'matchID':202,'matchDateTimeUTC':'2026-10-30T12:00:00','matchIsFinished':False,
         'team1':{'teamId':51,'teamName':'A'},'team2':{'teamId':52,'teamName':'B'},'matchResults':[]}
    ],OBS)


def links():
    return [{'t_match_id':'synthetic:001','provider':'football_data','provider_match_id':'101',
             'identity_verified':True,'evidence_url':'https://example.com/test'},
            {'t_match_id':'synthetic:001','provider':'openligadb','provider_match_id':'201',
             'identity_verified':True,'evidence_url':'https://example.com/test'}]


class RealDataTests(unittest.TestCase):
    def test_timezone_required(self):
        with self.assertRaises(ContractError): timestamp('2026-10-26T00:00:00')

    def test_normalize_fd_finished_and_upcoming(self):
        a=fd_rows();self.assertEqual(len(a),2)
        self.assertEqual(a[0]['full_time'],[2,1]);self.assertIsNone(a[1]['full_time'])

    def test_normalize_openliga_final_score(self):
        a=ol_rows();self.assertEqual(a[0]['full_time'],[2,1]);self.assertEqual(a[0]['half_time'],[1,0])

    def test_knockout_extra_time_is_not_auto_verified(self):
        data={'matches':[{'id':1,'utcDate':'2026-10-20T12:00:00Z','status':'FINISHED',
             'homeTeam':{'id':11,'name':'A'},'awayTeam':{'id':12,'name':'B'},
             'score':{'duration':'EXTRA_TIME','fullTime':{'home':2,'away':1},
                      'extraTime':{'home':1,'away':0}}}]}
        a=normalize_fd(data,OBS)
        self.assertIsNone(a[0]['full_time'])

    def test_openliga_not_finished_has_no_score(self):
        self.assertFalse(ol_rows()[1]['finished'])

    def test_only_two_sources_verify(self):
        res=match_results_by_links(fd_rows()+ol_rows(),links(),'2026-10-26T13:00:00Z')
        self.assertEqual(res['verified_count'],1)
        self.assertEqual(res['results'][0]['home_goals'],2)
        self.assertEqual(res['results'][0]['verification_rule'],'TWO_SOURCE_AGREEMENT')

    def test_single_source_not_verified(self):
        res=match_results_by_links(fd_rows(),links(),'2026-10-26T13:00:00Z')
        self.assertEqual(res['verified_count'],0)
        self.assertEqual(res['candidates'][0]['status'],'SINGLE_SOURCE_ONLY')

    def test_source_conflict_blocks_verification(self):
        altered=ol_rows();altered[0]['full_time']=[3,1]
        res=match_results_by_links(fd_rows()+altered,links(),'2026-10-26T13:00:00Z')
        self.assertEqual(res['verified_count'],0)
        self.assertEqual(res['candidates'][0]['status'],'SOURCE_CONFLICT')

    def test_halftime_conflict_blocks_verification(self):
        altered=ol_rows();altered[0]['half_time']=[0,0]
        res=match_results_by_links(fd_rows()+altered,links(),'2026-10-26T13:00:00Z')
        self.assertEqual(res['verified_count'],0)
        self.assertEqual(res['candidates'][0]['status'],'HALF_TIME_CONFLICT')

    def test_unverified_match_link_rejected(self):
        lk=links();lk[0]['identity_verified']=False
        res=match_results_by_links(fd_rows()+ol_rows(),lk,'2026-10-26T13:00:00Z')
        self.assertEqual(res['verified_count'],0)

    def test_source_captured_after_reconcile_time_rejected(self):
        altered=ol_rows();altered[0]['observed_at_utc']='2026-10-27T00:00:00Z'
        res=match_results_by_links(fd_rows()+altered,links(),'2026-10-26T13:00:00Z')
        self.assertEqual(res['verified_count'],0)

    def test_prematch_form_does_not_leak_future_results(self):
        studies=asof_match_studies(fd_rows(),'2026-10-26T13:00:00Z')
        self.assertEqual(len(studies),1)
        self.assertEqual(studies[0]['home_recent']['last5']['wins'],1)

    def test_past_asof_cannot_see_later_observed_results(self):
        studies=asof_match_studies(fd_rows(),'2026-10-19T13:00:00Z')
        self.assertEqual(studies,[])

    def test_studies_do_not_claim_real_xg(self):
        result=asof_match_studies(fd_rows(),'2026-10-26T13:00:00Z')
        self.assertIn('xG',result[0]['note'])

    def test_provisional_table_asof(self):
        rows=fd_rows()
        for row in rows:
            row['league_code']='TEST'
            row['season']=2026
        table=competition_standings_asof(rows,rows[1],'2026-10-26T13:00:00Z')
        self.assertEqual(table['matched_finished_matches'],1)
        self.assertEqual(table['rows'][0]['points'],3)
        self.assertEqual(table['rows'][1]['points'],0)

    def test_provisional_table_no_future_game(self):
        rows=fd_rows()
        for row in rows:
            row['league_code']='TEST'
            row['season']=2026
        table=competition_standings_asof(rows,rows[1],'2026-10-19T13:00:00Z')
        self.assertEqual(table['matched_finished_matches'],0)

    def test_read_normalized_checks_provider(self):
        with self.assertRaises(ContractError):
            read_normalized({'schema_version':'TPlusRealData.0.6','provider':'openligadb','matches':fd_rows()})

if __name__=='__main__': unittest.main()
