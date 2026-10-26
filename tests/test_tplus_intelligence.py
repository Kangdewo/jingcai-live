import unittest
from tplus_intelligence import aggregate_media, build_match_dossier, DataContractError

MID='test:2030-01-03:001'
KO='2030-01-03T12:00:00+00:00'
CUT='2030-01-03T10:00:00+00:00'

def article(url='https://news.example.com/p/1', publisher='news1', stance='home', origin='agency:story1'):
    return {'match_id':MID,'source_url':url,'publisher_id':publisher,
            'published_at_utc':'2030-01-03T08:00:00+00:00',
            'observed_at_utc':'2030-01-03T08:20:00+00:00',
            'relevance':True,'explicit_match_pick':stance,
            'pick_evidence':'The journalist explicitly predicts a home win' if stance!='none' else None,
            'syndication_origin_id':origin,'tone_home':'positive','tone_away':'neutral'}

class MediaContractTests(unittest.TestCase):
    def test_syndicated_articles_are_one_independent_origin(self):
        a=article()
        b=article('https://another.example.com/story','site2','home')
        res=aggregate_media([a,b],MID,CUT,KO)
        self.assertEqual(res['raw_submissions'],2)
        self.assertEqual(res['unique_publishers'],2)
        self.assertEqual(res['independent_origins_verified'],1)
        self.assertEqual(res['independent_explicit_picks']['home'],1)

    def test_utm_duplicate_does_not_double_count(self):
        a=article()
        b=article('https://news.example.com/p/1?utm_source=copy')
        res=aggregate_media([a,b],MID,CUT,KO)
        self.assertEqual(res['eligible_unique_articles'],1)
        self.assertEqual(res['rejected_counts']['DUPLICATE_URL'],1)

    def test_unknown_origin_not_claimed_independent(self):
        a=article(origin="")
        result=aggregate_media([a],MID,CUT,KO)
        self.assertEqual(result["independent_origins_verified"],0)
        self.assertEqual(result["provenance_unresolved_origins"],1)
        self.assertEqual(result["provisional_explicit_picks_not_counted"]["home"],1)

    def test_news_after_cutoff_excluded(self):
        a=article()
        a['published_at_utc']='2030-01-03T10:30:00+00:00'
        a['observed_at_utc']='2030-01-03T10:40:00+00:00'
        res=aggregate_media([a],MID,CUT,KO)
        self.assertEqual(res['eligible_unique_articles'],0)
        self.assertEqual(res['rejected_counts']['AFTER_INFORMATION_CUTOFF'],1)

    def test_pick_requires_explicit_evidence(self):
        a=article()
        a['pick_evidence']=None
        res=aggregate_media([a],MID,CUT,KO)
        self.assertEqual(res['explicit_pick_origin_count'],0)
        self.assertEqual(res['rejected_counts']['PICK_EVIDENCE_MISSING'],1)

    def test_tone_is_not_betting_opinion(self):
        a=article(stance='none')
        res=aggregate_media([a],MID,CUT,KO)
        self.assertEqual(res['independent_explicit_picks']['home'],0)
        self.assertEqual(res['tone_by_team']['home']['positive'],1)

    def test_conflicting_origin_not_two_votes(self):
        a=article()
        b=article('https://else.example.com/b','news2','away')
        res=aggregate_media([a,b],MID,CUT,KO)
        self.assertEqual(res['unresolved_origin_disagreements'],1)
        self.assertEqual(res['explicit_pick_origin_count'],0)

    def test_naive_timestamp_rejected(self):
        a=article()
        a['observed_at_utc']='2030-01-03T08:20:00'
        res=aggregate_media([a],MID,CUT,KO)
        self.assertEqual(res['eligible_unique_articles'],0)
        self.assertEqual(res['rejected_counts']['TIMEZONE_REQUIRED'],1)

    def test_dossier_marks_missing_without_invention(self):
        inp={'match':{'canonical_match_id':MID,'home':'演示主队','away':'演示客队','kickoff_at':KO},
             'information_cutoff_at':CUT,'sections':{},'media_articles':[]}
        res=build_match_dossier(inp)
        self.assertEqual(res['coverage']['verified_as_of'],0)
        self.assertEqual(res['sections']['market_valuations']['status'],'MISSING')
        self.assertIsNone(res['sections']['verified_results']['data'])

    def test_dossier_verifies_only_asof(self):
        inp={'match':{'canonical_match_id':MID,'kickoff_at':KO},'information_cutoff_at':CUT,
             'sections':{'league_standings':{'verification_status':'VERIFIED',
                'source_url':'https://example.com/league','observed_at_utc':'2030-01-03T11:00:00+00:00',
                'source_published_at_utc':'2030-01-03T09:00:00+00:00',
                'data':{'rank':2}}}}
        r=build_match_dossier(inp)
        self.assertEqual(r['sections']['league_standings']['status'],'NOT_AVAILABLE_AS_OF')

    def test_postkickoff_dossier_refused(self):
        with self.assertRaises(DataContractError):
            build_match_dossier({'match':{'canonical_match_id':MID,'kickoff_at':KO},
                 'information_cutoff_at':'2030-01-03T13:00:00+00:00'})

if __name__=='__main__':unittest.main()
