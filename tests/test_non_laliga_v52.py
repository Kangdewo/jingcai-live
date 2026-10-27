"""Offline, deterministic contract tests for the v5.2 non-LaLiga pipeline."""
import datetime as dt
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from tplus_results.non_laliga_v52 import (
    UTC,when,name_ok,parse_fd,parse_espn,match_candidate,fixtures,
    schedule_urls,verify_candidate,execute,FD_BASE
)
NOW=dt.datetime(2026,10,29,22,tzinfo=UTC)
MATCH={'t_match_id':'t:2026-10-29:周三006','league':'意甲','home':'AC米兰','away':'博洛尼亚','kickoff_utc':'2026-10-28T17:30:00+00:00'}
FD={'id':211000,'utcDate':'2026-10-28T17:30:00Z','homeTeam':{'id':18,'name':'AC Milan'},'awayTeam':{'id':22,'name':'Bologna'},'status':'FINISHED','score':{'fullTime':{'home':2,'away':1}}}
ES={'id':'401980123','date':'2026-10-28T17:30:00Z','competitions':[{'competitors':[{'homeAway':'home','team':{'id':'103','displayName':'AC Milan'},'score':'2'},{'homeAway':'away','team':{'id':'104','displayName':'Bologna'},'score':'1'}],'status':{'type':{'completed':True,'name':'STATUS_FINAL'}}}]}
APPROVAL={'approved':True,**MATCH,'identity_evidence_urls':['https://www.legaseriea.it/en'],
          'sources':{'football_data':{'match_id':211000,'home_team_id':18,'away_team_id':22},
                     'espn':{'match_id':'401980123','home_team_id':'103','away_team_id':'104'}}}

class Check(unittest.TestCase):
    def setup(self,tmp,approved=None,league='意甲'):
        root=Path(tmp);(root/'predictions').mkdir();(root/'docs'/'data'/'daily').mkdir(parents=True)
        m={**MATCH,'league':league}
        (root/'predictions'/'latest.json').write_text(json.dumps({'matches':[m]},ensure_ascii=False))
        (root/'predictions'/'non_laliga_links_approved.json').write_text(json.dumps({'links':approved or []},ensure_ascii=False))
        return root
    def sources(self,url,token):
        if url.startswith(FD_BASE):return {'matches':[FD]}
        return {'events':[ES]}
    def test_exact_alias(self):
        self.assertTrue(name_ok('AC米兰','AC Milan'))
        self.assertFalse(name_ok('AC米兰','Internazionale'))
        self.assertFalse(name_ok('不在列表','AC Milan'))
    def test_source_parser(self):
        self.assertEqual([2,1],parse_fd(FD)['full_time'])
        self.assertEqual([2,1],parse_espn(ES)['full_time'])
    def test_reject_swapped_team(self):
        m=dict(FD,homeTeam=FD['awayTeam'],awayTeam=FD['homeTeam'])
        self.assertFalse(match_candidate(parse_fd(m),MATCH))
    def test_reject_kickoff_change(self):
        m=dict(FD,utcDate='2026-10-28T18:00:00Z')
        self.assertFalse(match_candidate(parse_fd(m),MATCH))
    def test_reject_postponed(self):
        m=dict(ES);m['competitions']=[{**ES['competitions'][0],'status':{'type':{'completed':False}}}]
        self.assertIsNone(parse_espn(m)['full_time'])
    def test_missing_approval_no_score(self):
        with tempfile.TemporaryDirectory() as t:
            root=self.setup(t)
            report,result=execute(root,now=NOW,token='hidden',fetcher=self.sources)
            self.assertEqual(1,report['fixtures_examined'])
            self.assertEqual('NOT_MANUALLY_APPROVED',report['cases'][0]['verification_state'])
            self.assertEqual(0,result['verified_count'])
            self.assertFalse((root/'predictions'/'results_verified.json').exists())
    def test_approved_two_sources(self):
        with tempfile.TemporaryDirectory() as t:
            root=self.setup(t,[APPROVAL])
            report,res=execute(root,now=NOW,token='hidden',fetcher=self.sources)
            self.assertEqual('DUAL_SOURCE_FT_VERIFIED',report['cases'][0]['verification_state'])
            self.assertEqual(1,res['verified_count'])
            self.assertEqual([2,1],res['results'][0]['full_time'])
            self.assertFalse((root/'predictions'/'evaluation.json').exists())
    def test_conflicting_scores_blocked(self):
        with tempfile.TemporaryDirectory() as t:
            root=self.setup(t,[APPROVAL])
            def call(url,token):
                if url.startswith(FD_BASE):return {'matches':[{**FD,'score':{'fullTime':{'home':0,'away':1}}}]}
                return {'events':[ES]}
            report,res=execute(root,now=NOW,token='hidden',fetcher=call)
            self.assertEqual('FULLTIME_CONFLICT',report['cases'][0]['verification_state'])
            self.assertEqual(0,res['verified_count'])
    def test_wrong_id_never_promoted(self):
        with tempfile.TemporaryDirectory() as t:
            root=self.setup(t,[{**APPROVAL,'sources':{**APPROVAL['sources'],'espn':{**APPROVAL['sources']['espn'],'match_id':'401111111'}}}])
            report,res=execute(root,now=NOW,token='hidden',fetcher=self.sources)
            self.assertEqual(0,res['verified_count'])
            self.assertEqual('PROVIDER_MATCH_MISSING_OR_AMBIGUOUS',report['cases'][0]['verification_state'])
    def test_no_token_no_live_fd(self):
        with tempfile.TemporaryDirectory() as t:
            root=self.setup(t)
            def call(url,token):
                if url.startswith(FD_BASE):raise AssertionError('Never call FD without token')
                return {'events':[ES]}
            r,_=execute(root,now=NOW,token='',fetcher=call)
            self.assertEqual('SECRET_MISSING',r['cases'][0]['provider_state']['football_data']['state'])
    def test_http_error_no_secrets(self):
        with tempfile.TemporaryDirectory() as t:
            root=self.setup(t)
            def error(url,token):raise urllib.error.HTTPError(url,400,'API secret-123',None,None)
            report,res=execute(root,now=NOW,token='secret-123',fetcher=error)
            self.assertNotIn('secret-123',json.dumps(report))
            self.assertEqual(0,res['verified_count'])
    def test_cup_does_not_claim_two_sources(self):
        with tempfile.TemporaryDirectory() as t:
            root=self.setup(t,[{**APPROVAL,'league':'德国杯'}],league='德国杯')
            def call(url,token):return {'events':[ES]}
            report,res=execute(root,now=NOW,token='hidden',fetcher=call)
            self.assertEqual(0,res['verified_count'])
            self.assertEqual('TWO_SUPPORTED_PROVIDERS_REQUIRED',report['cases'][0]['verification_state'])
    def test_duplicate_approval_blocked(self):
        with tempfile.TemporaryDirectory() as t:
            root=self.setup(t,[APPROVAL,APPROVAL])
            report,res=execute(root,now=NOW,token='hidden',fetcher=self.sources)
            self.assertEqual('DUPLICATE_APPROVAL_REQUIRES_REVIEW',report['cases'][0]['verification_state'])
            self.assertEqual(0,res['verified_count'])
    def test_fixture_conflict_quarantined(self):
        with tempfile.TemporaryDirectory() as t:
            root=self.setup(t)
            data=json.loads((root/'predictions'/'latest.json').read_text())
            data['matches'].append({**MATCH,'away':'尤文图斯'})
            (root/'predictions'/'latest.json').write_text(json.dumps(data,ensure_ascii=False))
            f,c=fixtures(root,NOW)
            self.assertEqual([],f);self.assertEqual([MATCH['t_match_id']],c)
    def test_retrieval_links_bounded(self):
        src=schedule_urls([MATCH])
        self.assertEqual({('意甲','espn'),('意甲','football_data')},set(src))
        self.assertIn('dateFrom=',src[('意甲','football_data')])

if __name__=='__main__':unittest.main()
