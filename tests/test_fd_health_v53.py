import datetime as dt
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from tplus_results import fd_health_v53 as v

class FakeResponse:
    status=200
    def read(self,n):return b'{"competitions":[]}'[:n]
    def __enter__(self):return self
    def __exit__(self,*args):return False

class HealthTests(unittest.TestCase):
    def test_sanitizes_error_body(self):
        self.assertEqual('TOKEN_REJECTED_HINT',v.category_from_body(b'{"error":"Invalid X-Auth-Token: SUPERSECRET123"}'))
        self.assertEqual('INVALID_PARAMETER_HINT',v.category_from_body(b'{"error":"Parameter dateFrom invalid"}'))
        self.assertEqual('NO_SAFE_HINT',v.category_from_body(b'{"error":"sensitive private abc"}'))
    def test_three_probe_urls_fixed(self):
        self.assertEqual(3,len(v.PROBES))
        self.assertTrue(all(a.startswith(v.BASE) for _,a,_ in v.PROBES))
    def test_public_probe_no_auth(self):
        def op(req, timeout):
            self.assertIsNone(req.get_header('X-auth-token'))
            return FakeResponse()
        r=v.request_probe(*v.PROBES[0],'SECRET_VALUE',opener=op)
        self.assertEqual(200,r['http_status'])
    def test_auth_probe_with_auth_but_not_published(self):
        def op(req, timeout):
            self.assertEqual('NOT_FOR_PUBLICATION',req.get_header('X-auth-token'))
            return FakeResponse()
        r=v.request_probe(*v.PROBES[1],'NOT_FOR_PUBLICATION',opener=op)
        self.assertNotIn('NOT_FOR_PUBLICATION',json.dumps(r))
    def test_http400_only_bounded_hint(self):
        def op(req,timeout):
            raise urllib.error.HTTPError(req.full_url,400,'USER_SECRET_IN_REASON',{},None)
        r=v.request_probe(*v.PROBES[1],'PRIVATE',opener=op)
        self.assertEqual(400,r['http_status'])
        self.assertNotIn('USER_SECRET',json.dumps(r))
    def test_diagnosis_classification(self):
        p=[{'probe':'public_competitions','http_status':200},
           {'probe':'authenticated_serie_a','http_status':400},
           {'probe':'authenticated_serie_a_schedule','http_status':400}]
        self.assertTrue(v.diagnosis(p).startswith('AUTHENTICATED_REQUEST_REJECTED'))
    def test_candidate_queue_no_approval(self):
        data={'cases':[{'fixture':{'t_match_id':'t:2026-10-29:周三006','league':'意甲','home':'AC米兰','away':'博洛尼亚','kickoff_utc':'2026-10-28T17:30:00Z'},
             'sources':{'espn':[{'match_id':'401874993','home_id':'103','away_id':'104','home':'AC Milan','away':'Bologna','kickoff_utc':'2026-10-28T17:30:00Z'}]},
             'provider_state':{'espn':'CANDIDATE_FOUND'}}]}
        out=v.safe_review_queue(data)
        self.assertEqual(1,out['candidate_match_count'])
        self.assertFalse(out['items'][0]['approved'])
        self.assertEqual([],out['items'][0]['candidates']['football_data'])
    def test_candidate_bad_id_rejected(self):
        out=v.safe_review_queue({'cases':[{'fixture':{'t_match_id':'t:good'},'sources':{'espn':[{'match_id':'guess123'}]}}]})
        self.assertEqual(0,out['candidate_match_count'])
    def test_html_escape(self):
        h={'checked_at_utc':'2026-10-27T00:00:00Z','classification':'<x>',
           'probes':[], 'token_format':{'secret_present':True}}
        page=v.render_page(h,{'items':[],'count':0,'candidate_match_count':0})
        self.assertNotIn('> <x> ',page)
        self.assertIn('&lt;x&gt;',page)
    def test_does_not_change_forecasts(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root/'docs/data/results').mkdir(parents=True)
            original='{"never":"overwrite"}'
            (root/'predictions').mkdir()
            (root/'predictions/latest.json').write_text(original)
            def o(req,timeout):return FakeResponse()
            h,q=v.main(root,token='PRIVATE',opener=o,now=dt.datetime(2026,10,27,tzinfo=dt.timezone.utc))
            self.assertEqual(original,(root/'predictions/latest.json').read_text())
            all_json=''.join(x.read_text() for x in (root/'docs/data/results').glob('*.json'))
            self.assertNotIn('PRIVATE',all_json)
            self.assertTrue((root/'docs/fd-health.html').exists())

if __name__=='__main__':unittest.main()
