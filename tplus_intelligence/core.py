"""Strict, source-aware football match intelligence aggregation (stdlib only).

All data is user/provider-supplied. No invented team, player, news or results data.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

UTC = timezone.utc
STANCES = {"home", "draw", "away", "none"}
TONES = {"positive", "neutral", "negative", "unknown"}
TOPICS = {"match_preview", "team_news", "player_news", "injury", "transfer", "lineup", "coach", "opinion", "rumor", "other"}
COVERAGE_SECTIONS = (
    "match_identity", "club_history", "league_standings", "recent_form", "head_to_head",
    "squad", "injuries_suspensions", "transfers", "market_valuations",
    "lineups", "team_statistics", "weather_venue", "odds_timeline",
    "model_predictions", "verified_results", "evaluations",
)


class DataContractError(ValueError):
    pass


def parse_time(s: str) -> datetime:
    """Parse timezone-aware ISO8601. Naive timestamps are not accepted as proof."""
    if not isinstance(s, str) or not s.strip():
        raise DataContractError("TIME_MISSING")
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DataContractError("TIME_INVALID") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise DataContractError("TIMEZONE_REQUIRED")
    return dt.astimezone(UTC)


def canonical_url(s: str) -> str:
    if not isinstance(s, str):
        raise DataContractError("URL_MISSING")
    u = urlsplit(s.strip())
    if u.scheme.lower() not in ("http", "https") or not u.netloc:
        raise DataContractError("URL_INVALID")
    params = [(k, v) for k, v in parse_qsl(u.query, keep_blank_values=True)
              if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}]
    return urlunsplit((u.scheme.lower(), u.netloc.lower(), u.path.rstrip("/") or "/", urlencode(params), ""))


def _article_eligible(article: dict, match_id: str, cutoff: datetime, kickoff: datetime):
    if not isinstance(article, dict) or article.get("match_id") != match_id:
        return None, "WRONG_MATCH"
    if not article.get("publisher_id"):
        return None, "PUBLISHER_MISSING"
    try:
        pub = parse_time(article.get("published_at_utc"))
        seen = parse_time(article.get("observed_at_utc"))
        url = canonical_url(article.get("source_url"))
    except DataContractError as exc:
        return None, str(exc)
    if pub > seen:  # News cannot be observed before it is published.
        return None, "CHRONOLOGY_INVALID"
    if pub >= kickoff or seen >= kickoff or pub > cutoff or seen > cutoff:
        return None, "AFTER_INFORMATION_CUTOFF"
    if article.get("relevance") is not True:
        return None, "NOT_RELEVANT_OR_UNASSESSED"
    stance = article.get("explicit_match_pick", "none")
    if stance not in STANCES:
        return None, "STANCE_INVALID"
    # A genuine prediction needs a source-supported statement; sentiment is not a pick.
    if stance != "none" and not (isinstance(article.get("pick_evidence"), str) and article["pick_evidence"].strip()):
        return None, "PICK_EVIDENCE_MISSING"
    tone_h = article.get("tone_home", "unknown")
    tone_a = article.get("tone_away", "unknown")
    if tone_h not in TONES or tone_a not in TONES:
        return None, "TONE_INVALID"
    origin = str(article.get("syndication_origin_id") or "").strip()
    return {
        "source_url": url,
        "publisher_id": str(article["publisher_id"]),
        "published_at_utc": pub.isoformat(),
        "observed_at_utc": seen.isoformat(),
        "origin_key": origin if origin else "unverified:" + url,
        "origin_verified": bool(origin),
        "stance": stance,
        "tone_home": tone_h,
        "tone_away": tone_a,
        "topic": article.get("topic") if article.get("topic") in TOPICS else "other",
        "assessment_model": article.get("assessment_model"),
        "assessment_version": article.get("assessment_version"),
        "evidence_verified": bool(article.get("evidence_verified", False)),
    }, None


def aggregate_media(articles: list, match_id: str, cutoff_at: str, kickoff_at: str) -> dict:
    """Counts only independently evidenced explicit picks, never infers pick from tone.

    Syndicated/copy articles sharing syndication_origin_id count as one independent
    origin, even when 20 publishers reproduce the same story.
    """
    cutoff, kickoff = parse_time(cutoff_at), parse_time(kickoff_at)
    if not cutoff < kickoff:
        raise DataContractError("CUTOFF_MUST_PRECEDE_KICKOFF")
    rejected = Counter()
    eligible = []
    for article in articles:
        item, reason = _article_eligible(article, match_id, cutoff, kickoff)
        if reason:
            rejected[reason] += 1
        else:
            eligible.append(item)
    # Deduplicate exact page URLs (even when entered more than once).
    seen_urls = set()
    unique = []
    for row in sorted(eligible, key=lambda x: (x["observed_at_utc"], x["source_url"])):
        if row["source_url"] in seen_urls:
            rejected["DUPLICATE_URL"] += 1
            continue
        seen_urls.add(row["source_url"])
        unique.append(row)
    origins = defaultdict(list)
    for row in unique:
        origins[row["origin_key"]].append(row)
    independent_picks = Counter({x: 0 for x in ("home", "draw", "away", "none")})
    provisional_picks = Counter({x: 0 for x in ("home", "draw", "away", "none")})
    conflicting_origins = 0
    unresolved_provenance = 0
    for group in origins.values():
        target = independent_picks if all(x["origin_verified"] for x in group) else provisional_picks
        if target is provisional_picks:
            unresolved_provenance += 1
        explicit = {a["stance"] for a in group if a["stance"] != "none"}
        if len(explicit) > 1:
            # Potential independent analysis hidden in one syndication cluster;
            # don't count a conflicting origin as multiple votes.
            conflicting_origins += 1
            target["none"] += 1
        elif len(explicit) == 1:
            target[next(iter(explicit))] += 1
        else:
            target["none"] += 1
    explicit_n = sum(independent_picks[x] for x in ("home", "draw", "away"))
    tones = {side: dict(Counter(x[f"tone_{side}"] for x in unique)) for side in ("home", "away")}
    digest = hashlib.sha256(json.dumps({
        "id": match_id, "cutoff": cutoff.isoformat(),
        "sources": sorted((x["source_url"], x["stance"], x["origin_key"]) for x in unique)
    }, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return {
        "schema_version": "TPlusMediaAudit.0.5",
        "match_id": match_id,
        "information_cutoff_utc": cutoff.isoformat(),
        "kickoff_utc": kickoff.isoformat(),
        "raw_submissions": len(articles),
        "eligible_unique_articles": len(unique),
        "unique_publishers": len({x["publisher_id"] for x in unique}),
        "origin_clusters_total": len(origins),
        "independent_origins_verified": len(origins) - unresolved_provenance,
        "provenance_unresolved_origins": unresolved_provenance,
        "independent_explicit_picks": dict(independent_picks),
        "provisional_explicit_picks_not_counted": dict(provisional_picks),
        "explicit_pick_origin_count": explicit_n,
        "unresolved_origin_disagreements": conflicting_origins,
        "tone_by_team": tones,
        "rejected_counts": dict(rejected),
        "input_digest_sha256": digest,
        "predictive_edge_verified": False,
        "notes": [
            "An article's positive sentiment about a club is not a match outcome prediction.",
            "Only syndication-identified origins are counted as independently evidenced. Unresolved provenance is kept separate.",
            "Counts are descriptive, not an estimate of match outcome probabilities.",
            "No news fetching or AI inference occurs in this module; assessments must be supplied and audited.",
        ],
    }


def build_match_dossier(payload: dict) -> dict:
    """Assemble source-aware fields without inventing missing data."""
    match = payload.get("match") or {}
    mid = match.get("canonical_match_id")
    if not isinstance(mid, str) or not mid.strip():
        raise DataContractError("MATCH_ID_REQUIRED")
    kickoff = parse_time(match.get("kickoff_at"))
    cutoff = parse_time(payload.get("information_cutoff_at"))
    if cutoff >= kickoff:
        raise DataContractError("AFTER_KICKOFF")
    sections = payload.get("sections") or {}
    if not isinstance(sections, dict):
        raise DataContractError("SECTIONS_INVALID")
    rendered = {}
    for name in COVERAGE_SECTIONS:
        item = sections.get(name)
        if isinstance(item, dict) and item.get("verification_status") == "VERIFIED" and item.get("source_url"):
            seen = parse_time(item.get("observed_at_utc"))
            published = parse_time(item.get("source_published_at_utc"))
            if published <= seen <= cutoff:
                rendered[name] = {"status": "VERIFIED_AS_OF", "data": item.get("data"),
                                  "source_url": canonical_url(item["source_url"]),
                                  "observed_at_utc": seen.isoformat(),
                                  "source_published_at_utc": published.isoformat()}
            else:
                rendered[name] = {"status": "NOT_AVAILABLE_AS_OF", "data": None}
        else:
            rendered[name] = {"status": "MISSING", "data": None}
    media = aggregate_media(payload.get("media_articles") or [], mid,
                            payload["information_cutoff_at"], match["kickoff_at"])
    return {
        "schema_version": "TPlusMatchDossier.0.5",
        "canonical_match_id": mid,
        "home": match.get("home"), "away": match.get("away"),
        "kickoff_utc": kickoff.isoformat(),
        "information_cutoff_utc": cutoff.isoformat(),
        "sections": rendered,
        "coverage": {
            "verified_as_of": sum(v["status"] == "VERIFIED_AS_OF" for v in rendered.values()),
            "expected": len(COVERAGE_SECTIONS),
        },
        "media": media,
        "research_only": True,
        "is_independent_forecast": False,
    }
