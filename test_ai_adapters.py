import os
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tplus_predict.agents import parse_forecast,openai_predict,gemini_predict

class AgentTests(unittest.TestCase):
    def test_valid_json(self):
        p,why=parse_forecast('{"home":0.3,"draw":0.3,"away":0.4,"reason":"sample"}')
        self.assertEqual(why,'sample')
        self.assertAlmostEqual(sum(p.values()),1)
    def test_invalid(self):
        for s in ('{"home":.6,"draw":0,"away":0}',
                  '{"home":0.2,"draw":0.2,"away":0.2}', 'not json'):
            with self.assertRaises((ValueError,KeyError)): parse_forecast(s)
    def test_openai_mock(self):
        def fake(url,headers,body):
            self.assertEqual(url,'https://api.openai.com/v1/responses')
            self.assertIn('Authorization',headers)
            return {'output':[{'content':[{'type':'output_text','text':'{"home":0.2,"draw":0.3,"away":0.5}'}]}]}
        p,_=openai_predict('test-model','fake-secret','prompt',fake)
        self.assertEqual(p['away'],0.5)
    def test_gemini_mock(self):
        def fake(url,headers,body):
            self.assertIn(':generateContent',url)
            self.assertEqual(headers['x-goog-api-key'],'fake-secret')
            return {'candidates':[{'content':{'parts':[{'text':'{"home":0.2,"draw":0.3,"away":0.5}'}]}}]}
        p,_=gemini_predict('test-model','fake-secret','prompt',fake)
        self.assertEqual(p['home'],0.2)

if __name__=='__main__':unittest.main()
