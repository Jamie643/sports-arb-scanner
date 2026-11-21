import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

from curl_cffi import requests as curl_requests

from scrapers.common import (
    fetch_json_feed,
    is_normalized_payload,
    normalize_matches,
)
from settings import BETKING_FEED_URL


_BETKING_HOME_URL = "https://www.betking.com/"


def _utc_dates() -> tuple[str, str]:
    today = datetime.now(timezone.utc).date()
    tomorrow = today + timedelta(days=1)
    return today.isoformat(), tomorrow.isoformat()


def _date_wide_urls(feed_url: str) -> list[str] | None:
    if not re.search(r"/api/feeds/prematch/GetEvents/", feed_url, re.IGNORECASE):
        return None

    placeholder = re.compile(
        r"\{(?:date|YYYY-MM-DD)\}",
        re.IGNORECASE,
    )
    if placeholder.search(feed_url):
        current, next_day = _utc_dates()
        return [
            placeholder.sub(current, feed_url),
            placeholder.sub(next_day, feed_url),
        ]

    dated_url = re.compile(
        r"/GetEvents/(?P<language>[^/]+)/"
        r"(?P<date>\d{4}-\d{2}-\d{2})/"
        r"(?P<area>[^/]+)/(?P<region>[^/]+)/(?P<sport>\d+)",
        re.IGNORECASE,
    )
    match = dated_url.search(feed_url)
    if match:
        current, next_day = _utc_dates()
        prefix = feed_url[: match.start("date")]
        suffix = feed_url[match.end("date") :]
        return [prefix + current + suffix, prefix + next_day + suffix]
    return None


def _deduplicate_matches(
    matches: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    deduplicated: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for match in matches:
        key = (
            str(match["home"]).strip().casefold(),
            str(match["away"]).strip().casefold(),
            str(match["kickoff"]).strip(),
            str(match["market"]).strip().casefold(),
        )
        deduplicated.setdefault(key, match)
    return list(deduplicated.values())


def _teams(item: dict[str, Any]) -> tuple[str, str] | None:
    teams = item.get("Teams")
    if isinstance(teams, list):
        named_teams = [
            team
            for team in teams
            if isinstance(team, dict) and str(team.get("Name", "")).strip()
        ]

        def team_order(team: dict[str, Any]) -> float:
            try:
                return float(team.get("ItemOrder", 0))
            except (TypeError, ValueError):
                return 0

        named_teams.sort(key=team_order)
        if len(named_teams) >= 2:
            return (
                str(named_teams[0]["Name"]).strip(),
                str(named_teams[1]["Name"]).strip(),
            )

    item_name = item.get("ItemName")
    if isinstance(item_name, str) and " - " in item_name:
        home, away = item_name.split(" - ", maxsplit=1)
        if home.strip() and away.strip():
            return home.strip(), away.strip()
    return None


def _league_name(item: dict[str, Any], area: dict[str, Any]) -> str:
    keys = (
        "LeagueName",
        "ItemLeagueName",
        "leagueName",
        "league",
        "CompetitionName",
        "ItemCompetitionName",
        "competitionName",
        "competition",
        "TournamentName",
        "ItemTournamentName",
        "tournamentName",
        "tournament",
        "AreaName",
        "RegionName",
    )
    for source in (item, area):
        for key in keys:
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, dict):
                for name_key in ("name", "Name", "displayName"):
                    name = value.get(name_key)
                    if isinstance(name, str) and name.strip():
                        return name.strip()
    return ""


def _market_kind(collection: dict[str, Any]) -> str | None:
    odds_type = collection.get("OddsType")
    name = odds_type.get("OddsTypeName", "") if isinstance(odds_type, dict) else ""
    normalized_name = " ".join(str(name).casefold().split())

    is_btts = (
        "both teams to score" in normalized_name
        or re.search(r"\bbtts\b", normalized_name)
        or re.search(r"\bgg\s*/\s*ng\b", normalized_name)
    )
    if is_btts and not any(
        period in normalized_name for period in ("half", "1st half", "2nd half")
    ):
        return "btts"
    if "total goals" not in normalized_name:
        return None
    if "early" in normalized_name or "half" in normalized_name:
        return None

    line_values: list[Any] = [
        collection.get("SpecialBetValue"),
        collection.get("SpecialValueDisplay"),
    ]
    match_odds = collection.get("MatchOdds", [])
    if not isinstance(match_odds, list):
        match_odds = []
    for odd in match_odds:
        if isinstance(odd, dict):
            attribute = odd.get("OddAttribute")
            if isinstance(attribute, dict):
                line_values.extend(
                    (
                        attribute.get("SpecialValue"),
                        attribute.get("SpecialValueString"),
                    )
                )
    line_is_25 = "2.5" in normalized_name
    for value in line_values:
        try:
            if math.isclose(float(value), 2.5):
                line_is_25 = True
                break
        except (TypeError, ValueError):
            continue
    return "over_under_25" if line_is_25 else None


def _selections(collection: dict[str, Any]) -> dict[str, float]:
    selections: dict[str, float] = {}
    match_odds = collection.get("MatchOdds")
    if not isinstance(match_odds, list):
        return selections

    for odd in match_odds:
        if not isinstance(odd, dict):
            continue
        attribute = odd.get("OddAttribute")
        outcome = odd.get("Outcome")
        if not isinstance(attribute, dict) or not isinstance(outcome, dict):
            continue
        name = str(attribute.get("OddName", "")).strip().casefold()
        try:
            price = float(outcome.get("OddOutcome"))
        except (TypeError, ValueError):
            continue
        if math.isfinite(price) and price > 1:
            selections[name] = price
    return selections


def _parse_betking_payload(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(
        payload.get("AreaMatches"), list
    ):
        raise ValueError("BetKing feed must contain an AreaMatches list")

    matches: list[dict[str, Any]] = []
    for area in payload["AreaMatches"]:
        if not isinstance(area, dict):
            continue
        items = area.get("Items", [])
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            teams = _teams(item)
            kickoff = item.get("ItemDate")
            if teams is None or not isinstance(kickoff, str) or not kickoff:
                continue

            collections = item.get("OddsCollection")
            if not isinstance(collections, list):
                continue
            for collection in collections:
                if not isinstance(collection, dict):
                    continue
                kind = _market_kind(collection)
                selections = _selections(collection)
                if kind == "over_under_25":
                    outcome_a, outcome_b = selections.get("over"), selections.get(
                        "under"
                    )
                    market = "Over/Under 2.5 Goals"
                elif kind == "btts":
                    outcome_a = selections.get("yes", selections.get("gg"))
                    outcome_b = selections.get("no", selections.get("ng"))
                    market = "Both Teams to Score"
                else:
                    continue
                if outcome_a is None or outcome_b is None:
                    continue

                matches.append(
                    {
                        "home": teams[0],
                        "away": teams[1],
                        "kickoff": kickoff,
                        "market": market,
                        "outcome_a": outcome_a,
                        "outcome_b": outcome_b,
                        "league": _league_name(item, area),
                        "url": str(
                            item.get("URL")
                            or item.get("Url")
                            or item.get("url")
                            or _BETKING_HOME_URL
                        ),
                    }
                )
    return matches


def parse_payload(payload: Any) -> list[dict[str, Any]]:
    """Map BetKing prematch JSON or normalized sample records to scanner rows."""
    if is_normalized_payload(payload):
        return normalize_matches(payload, "BetKing")
    return normalize_matches(_parse_betking_payload(payload), "BetKing")


def fetch_matches() -> list[dict[str, Any]]:
    """Fetch and normalize the configured BetKing public feed."""
    if not BETKING_FEED_URL:
        raise ValueError("BetKing feed URL is not configured")

    parsed_url = urlparse(BETKING_FEED_URL)
    if parsed_url.scheme == "file":
        return fetch_json_feed(BETKING_FEED_URL, "BetKing", parse_payload)

    date_urls = _date_wide_urls(BETKING_FEED_URL)
    if date_urls is not None:
        matches: list[dict[str, Any]] = []
        for date_url in date_urls:
            response = curl_requests.get(
                date_url,
                headers={"Accept": "application/json"},
                timeout=15,
            )
            response.raise_for_status()
            matches.extend(parse_payload(response.json()))
        return _deduplicate_matches(matches)

    return fetch_json_feed(BETKING_FEED_URL, "BetKing", parse_payload)
