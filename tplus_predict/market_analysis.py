# coding: utf-8
"""T+ 0.4.1: audited public history priors + five T-market prices.

Publishes analysis for other readers WITHOUT claiming to be independent 005,
team form, real xG or an authenticated pre-match historic freeze.
Only public aggregate seasons STRICTLY EARLIER than the fixture calendar year
are used as historical priors; no in-season future result leakage.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path

from .runner import ROOT, UTC, atomic_json, choose, load_json, safe_slug, utc_now

SCHEMA = 'TPlusFiveMarketHistory.0.4.1'
# 'h' = home win, 'd' = draw, 'a' = away win in the ORIGINAL non-handicap result.
MARKETS = {
    'spf': [('home','had_h'),('draw','had_d'),('away','had_a')],
    'rqspf': [('home','hhad_h'),('draw','hhad_d'),('away','hhad_a')],
    'total_goals': [(str(i),'ttg_'+str(i)) for i in range(8)],
    'half_full': [(a+b,'hf_'+a+b) for a in 'hda' for b in 'hda'],
}
SCORES = (
    '1:0','2:0','2:1','3:0','3:1','3:2','4:0','4:1','4:2','5:0','5:1','5:2','胜其它',
    '0:0','1:1','2:2','3:3','平其它',
    '0:1','0:2','1:2','0:3','1:3','2:3','0:4','1:4','2:4','0:5','1:5','2:5','负其它',
)
MARKETS['exact_score'] = [(v, 'crs_'+v) for v in SCORES]
# Aliases only when the legacy dataset's league identity is known.
LEAGUE_ALIASES = {
    '葡超': ['POR1'], '英超': ['ENG1'], '荷甲': ['NED1'],
    '西甲': ['ESP1'], '西乙': ['ESP2'], '法甲': ['FRA1'], '法乙': ['FRA2'],
    '德甲': ['GER1'], '德乙': ['GER2'], '意甲': ['ITA1'], '意乙': ['ITA2'],
    '比甲': ['BEL1'], '希腊超': ['GRE1'], '土超': ['TUR1'], '苏超': ['SCO1'],
    '巴甲': ['Brazil:Serie A'], '美职': ['USA:MLS'], '美职联': ['USA:MLS'],
    '日职': ['Japan:J1 League','Japan: J1 League'],
    '瑞超': ['Sweden:Allsvenskan','Sweden :Allsvenskan '],
    '挪超': ['Norway:Eliteserien'],
    '芬超': ['Finland:Veikkausliiga','Finland :Veikkausliiga '],
}


def market_probabilities(raw: dict, config: list[tuple[str, str]]) -> dict | None:
    """Normalize 1/decimal-odds within one COMPLETE mutually-exclusive market."""
    implied = []
    if not isinstance(raw, dict):
        return None
    for label, field in config:
        try:
            value = raw[field]
            if isinstance(value, bool):
                return None
            odd = float(value)
        except (ValueError, TypeError, KeyError):
            return None
        if not math.isfinite(odd) or not 1.000001 < odd <= 100000:
            return None
        implied.append((label, 1.0 / odd))
    total = sum(x for _, x in implied)
    if not 0.55 <= total <= 1.85:
        return None
    return {'probabilities': {k: round(v / total, 8) for k, v in implied},
            'overround': round(total - 1, 6),
            'top_three': [
                {'outcome': key, 'probability': round(p / total, 8)}
                for key, p in sorted(implied, key=lambda kv: -kv[1])[:3]],
            'method': 'inverse_decimal_odds_normalized; not independent forecasting'}


def normalize_league(league: object) -> list[str]:
    if not isinstance(league, str):
        return []
    if league in LEAGUE_ALIASES:
        return LEAGUE_ALIASES[league]
    # Literal full league IDs from legacy file are safe exact matches.
    if re.fullmatch(r'[A-Z]{2,4}\d', league):
        return [league]
    return []


def history_prior(league: object, cutoff_year: int, items: list[dict], years_back: int = 3) -> dict | None:
    aliases = set(normalize_league(league))
    if not aliases:
        return None
    eligible = []
    for item in items:
        if not isinstance(item, dict) or item.get('league') not in aliases:
            continue
        try:
            year = int(item['year'])
            count = int(item['matches'])
        except (KeyError, ValueError, TypeError):
            continue
        # Important: the season/year that includes the target event is never touched.
        if year >= cutoff_year or year < cutoff_year - 6 or count <= 0:
            continue
        eligible.append((year, item))
    selected_years = sorted({year for year, _ in eligible}, reverse=True)[:years_back]
    if not selected_years:
        return None
    sample = [(year, item) for year, item in eligible if year in selected_years]
    counts = Counter(); goals = Counter(); exact = Counter()
    for _, item in sample:
        try:
            for name in ('home','draw','away'):
                counts[name] += int(item['ft_result_counts'].get(name, 0))
            for v in range(8):
                goals[str(v)] += int(item['total_goals_0_to_7plus'].get(str(v), 0))
            for score, val in item.get('exact_score_frequency', {}).items():
                if re.fullmatch(r'\d{1,2}:\d{1,2}', score):
                    exact[score] += int(val)
        except (TypeError, ValueError, KeyError):
            return None
    n = sum(counts.values()); ng = sum(goals.values())
    if min(n, ng) < 50 or n != ng:
        return None
    return {
        'source': 'history_feed/league_seasons.json',
        'source_kind': 'previous_seasons_aggregated_real_results',
        'league_keys': sorted(aliases),
        'selected_complete_prior_years': selected_years,
        'asof_rule': 'season_year < fixture_calendar_year; current year strictly excluded',
        'sample_size': n,
        'ft_1x2': {k: round(counts[k] / n, 8) for k in ('home','draw','away')},
        'total_goals': {str(k): round(goals[str(k)] / ng, 8) for k in range(8)},
        'top_exact_scores': [{'score':k,'historical_frequency':round(v / n, 8),'count':v}
                             for k,v in exact.most_common(8)],
        'quality': 'league_prior_only; NOT team form, xG, or independently timestamped historical odds',
    }


def analyze_row(row: dict, feed: dict, now: dt.datetime, history: dict) -> tuple[dict | None, str | None]:
    benchmark, err = choose(row, feed, now)
    if err:
        return None, err
    games = row.get('odds') or {}
    result = {}
    for name, conf in MARKETS.items():
        group = market_probabilities(games, conf)
        if group is not None:
            result[name] = group
    # Do not claim available odds groups that are incomplete.
    fixture_year = int(str(row['date_local'])[:4])
    prior = history_prior(row.get('league'), fixture_year, history.get('items', []))
    deltas = None
    if prior and 'spf' in result:
        deltas = {k: round(result['spf']['probabilities'][k] - prior['ft_1x2'][k], 6)
                  for k in ('home','draw','away')}
    score_top = result.get('exact_score', {}).get('top_three', [])
    ident = benchmark['t_match_id']
    # Hash includes all five-market quotes and the historical priors selected, not just 1x2.
    payload = json.dumps({'id':ident,'market':games,'history':prior,
                          'source':benchmark['information_cutoff_utc']},
                         ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    quote_hash = hashlib.sha256(payload.encode('utf8')).hexdigest()[:24]
    analysis = {
        'schema_version': SCHEMA,
        't_match_id': ident,
        'source_match_key': benchmark.get('source_match_key'),
        'home': benchmark['home'], 'away': benchmark['away'], 'league': benchmark['league'],
        'kickoff_utc': benchmark['kickoff_utc'],
        'analysis_created_at_utc': now.isoformat(),
        'source_input_cutoff_utc': benchmark['information_cutoff_utc'],
        'time_confidence': 'upstream_local_time_assumed_Asia_Shanghai_not_verified',
        'lead_minutes_at_recording': benchmark['lead_minutes_at_recording'],
        'legacy_market_input_hash': benchmark['input_hash'],
        'analysis_input_hash': quote_hash,
        'market_odds_implied': result,
        'five_markets_covered': len(result),
        'market_handicap_integer': str(games.get('goal')) if games.get('goal') is not None else None,
        'history_league_prior': prior,
        'market_minus_history_prior_spf': deltas,
        'prior_available_for_match': prior is not None,
        'independent_team_form_available': False,
        'true_xg_available': False,
        'official_005_prediction': None,
        'model_id': 'market_5way_with_historical_league_context_v041',
        'model_class': 'market_and_prior_research_not_independent_model',
        'betting_instruction': False,
        'warnings': [
            'All five market probabilities are derived from current T odds; they are NOT independent forecasts.',
            'Historical priors are completed EARLIER calendar years only and cannot predict a specific matchup.',
            'No independently verified 005, lineup, injuries, or xG data in these inputs.',
            'Historical result frequencies are not historical bookmaker quoted prices.',
            'Historical Chinese Jingcai half/full and integer handicap prices are not reconstructed.',
        ],
    }
    return analysis, None


def run(root: Path = ROOT, now: dt.datetime | None = None) -> dict:
    now = (now or utc_now()).astimezone(UTC)
    feed = load_json(root / 'model_feed/latest.json')
    history = load_json(root / 'history_feed/league_seasons.json')
    if not isinstance(feed, dict) or feed.get('feed_type') != 'T_odds_research':
        raise RuntimeError('Missing or unexpected model_feed/latest.json')
    if not isinstance(history, dict) or not isinstance(history.get('items'), list):
        raise RuntimeError('Missing history_feed/league_seasons.json')
    outdir = root / 'predictions'
    valid, skips, archived, coverage = [], Counter(), 0, Counter()
    for row in feed.get('matches', [])[:250]:
        if not isinstance(row, dict):
            continue
        record, err = analyze_row(row, feed, now, history)
        if err:
            skips[err] += 1
            continue
        valid.append(record)
        for key in record['market_odds_implied']:
            coverage[key] += 1
        path = outdir / 'analysis_records' / safe_slug(record['t_match_id']) / (record['analysis_input_hash'] + '.json')
        if not path.exists():
            atomic_json(path, record)
            archived += 1
    published = {
        'schema_version': SCHEMA,
        'generated_at_utc': now.isoformat(),
        'source_feed_generated_at_utc': feed.get('generated_at_utc'),
        'research_only': True,
        'match_count': len(valid),
        'historic_league_context_count': sum(x['prior_available_for_match'] for x in valid),
        'markets_coverage': dict(coverage),
        'matches': valid,
        'explicitly_not_005': True,
    }
    status = {
        'schema_version': SCHEMA,
        'updated_at_utc': now.isoformat(),
        'match_count': len(valid),
        'skipped_by_reason': dict(skips),
        'history_league_prior_coverage': published['historic_league_context_count'],
        'markets_coverage': dict(coverage),
        'new_immutable_analysis_records': archived,
        'verified_independent_team_feature_count': 0,
        'note': 'No licensed team-level as-of feed is published; league aggregate is previous-years only.',
    }
    atomic_json(outdir / 'analysis_latest.json', published)
    atomic_json(outdir / 'analysis_status.json', status)
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return status


if __name__ == '__main__':
    run()
