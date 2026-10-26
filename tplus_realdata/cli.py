"""T+ v0.6: small, opt-in real data adapter and conservative score reconciliation."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import urllib.request
import urllib.error
from .core import (normalize_fd, normalize_openliga, asof_match_studies,
                   match_results_by_links, read_normalized, utcnow, ContractError)


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path,data):
    out=Path(path)
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return out


def http_json(url,token=None):
    headers={'User-Agent':'TPlusRealDataResearch/0.6 (user operated; rate limited)',
             'Accept':'application/json'}
    if token:
        headers['X-Auth-Token']=token
    req=urllib.request.Request(url,headers=headers)
    try:
        with urllib.request.urlopen(req,timeout=25) as response:
            if int(response.status)!=200:
                raise RuntimeError('HTTP_NOT_200')
            data=response.read(8*1024*1024+1)
            if len(data)>8*1024*1024:
                raise RuntimeError('RESPONSE_TOO_LARGE')
            return json.loads(data)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f'PROVIDER_HTTP_ERROR_{exc.code} (token, access or rate limit)') from exc
    except urllib.error.URLError as exc:
        raise RuntimeError('NETWORK_OR_DNS_ERROR') from exc


def _int_4_year(raw):
    n=int(raw)
    if n<1990 or n>2100:
        raise ValueError('INVALID_SEASON')
    return n


def cli():
    parser=argparse.ArgumentParser(description='T+ v0.6 real fixture data research. No main-branch writes.')
    sub=parser.add_subparsers(dest='cmd',required=True)
    fetch=sub.add_parser('fetch',help='Fetch one season only, never scrape web pages')
    fetch.add_argument('--provider',choices=['openligadb','football_data'],required=True)
    fetch.add_argument('--league',required=True,help='OpenLigaDB bl1/bl2 or football-data.org BL1/PL/etc')
    fetch.add_argument('--season',required=True,type=_int_4_year)
    fetch.add_argument('--output',required=True)
    normalize=sub.add_parser('normalize-fixture',help='Convert a saved provider example or user supplied raw data')
    normalize.add_argument('--provider',choices=['openligadb','football_data'],required=True)
    normalize.add_argument('--input',required=True)
    normalize.add_argument('--observed-at',required=True)
    normalize.add_argument('--output',required=True)
    report=sub.add_parser('report',help='Build provider-based recent form and H2H, strictly as-of')
    report.add_argument('--input',action='append',required=True)
    report.add_argument('--cutoff',required=True,help='Timezone-aware ISO8601')
    report.add_argument('--output',required=True)
    compare=sub.add_parser('reconcile',help='Explicit T match links + independent two-source FT agreement')
    compare.add_argument('--input',action='append',required=True)
    compare.add_argument('--links',required=True)
    compare.add_argument('--checked-at',default=None)
    compare.add_argument('--output',required=True)
    compare.add_argument('--verified-output',default=None,help='Optional compatible predictions/results_verified.json; NOT auto committed')
    args=parser.parse_args()
    if args.cmd=='fetch':
        if args.provider=='football_data':
            token=os.environ.get('FOOTBALL_DATA_API_KEY','').strip()
            if not token:
                parser.error('FOOTBALL_DATA_API_KEY secret required. No fake results will be generated.')
            code=args.league.upper()
            if not code.replace('_','').isalnum():
                parser.error('INVALID_LEAGUE')
            url=f'https://api.football-data.org/v4/competitions/{code}/matches?season={args.season}'
            raw=http_json(url,token)
        else:
            code=args.league.lower()
            if not code.isascii() or not code.isalnum():
                parser.error('INVALID_LEAGUE')
            url=f'https://api.openligadb.de/getmatchdata/{code}/{args.season}'
            raw=http_json(url)
        observed_at=utcnow()
        rows=normalize_fd(raw,observed_at) if args.provider=='football_data' else normalize_openliga(raw,observed_at)
        data={'schema_version':'TPlusRealData.0.6','provider':args.provider,
              'retrieved_at_utc':observed_at,'request_url':url,'matches':rows,
              'league_code':code,'season':args.season,
              'note':'Provider data unverified for T match linkage; no historical as-of claims.'}
        write(args.output,data)
        print(f'Fetched {len(rows)} matches from {args.provider}, saved {args.output}')
        if not rows:
            print('WARNING: Zero accessible matches. Verify league, season and provider coverage; do not infer results.')
    elif args.cmd=='normalize-fixture':
        raw=load(args.input)
        rows=normalize_fd(raw,args.observed_at) if args.provider=='football_data' else normalize_openliga(raw,args.observed_at)
        data={'schema_version':'TPlusRealData.0.6','provider':args.provider,
              'retrieved_at_utc':args.observed_at,'matches':rows,
              'league_code':'SYNTHETIC','season':2026,
              'note':'Local fixture converted; synthetic input is not a real result.'}
        write(args.output,data)
        print(f'Normalized {len(rows)} records: {args.output}')
    elif args.cmd in ('report','reconcile'):
        all_rows=[]
        for path in args.input:
            all_rows.extend(read_normalized(load(path)))
        if args.cmd=='report':
            cutoff = utcnow() if args.cutoff.strip().lower()=='now' else args.cutoff
            result={'schema_version':'TPlusAsOfStudy.0.6','cutoff_utc':cutoff,
                    'studies':asof_match_studies(all_rows,cutoff),
                    'note':'Current-season provider subset only. For historical replay, actual observation must predate cutoff.'}
            write(args.output,result)
            print(f"Saved {len(result['studies'])} as-of studies: {args.output}")
        else:
            links_doc=load(args.links)
            if not isinstance(links_doc,dict) or not isinstance(links_doc.get('links'),list):
                raise ContractError('BAD_LINKS_FORMAT')
            result=match_results_by_links(all_rows,links_doc['links'],args.checked_at or utcnow())
            write(args.output,result)
            if args.verified_output is not None:
                # Current runner accepts {'results':[...]} but only true pre-match frozen records may be evaluated.
                write(args.verified_output,{'results':result['results'],
                     '_meta':{'verified_by':'TPlus v0.6 two-source result reconciliation',
                              'checked_at_utc':result['checked_at_utc']}})
            print(f"Candidates {len(result['candidates'])}; 2-source verified {result['verified_count']}")

if __name__=='__main__':
    cli()
