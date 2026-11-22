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
from settings import BETKING_FEED_URL, DEFAULT_BETKING_FEED_URL


_BETKING_HOME_URL = "https://www.betking.com/"
_BETKING_SPORT_IDS = (1, 2, 5)


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


def _sport_urls(feed_url: str) -> list[str]:
    match = re.search(
        r"(?P<prefix>/GetEvents/[^/]+/\d{4}-\d{2}-\d{2}/[^/]+/[^/]+/)"
        r"(?P<sport>\d+)(?P<suffix>(?:\?.*)?$)",
        feed_url,
        re.IGNORECASE,
    )
    if match is None:
        return [feed_url]
    return [
        feed_url[: match.start("sport")]
        + str(sport_id)
        + feed_url[match.end("sport") :]
        for sport_id in _BETKING_SPORT_IDS
    ]


def _deduplicate_matches(
    matches: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    deduplicated: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    for match in matches:
        key = (
            str(match["sport"]).strip().casefold(),
            str(match["home"]).strip().casefold(),
            str(match["away"]).strip().casefold(),
            str(match["kickoff"]).strip(),
            str(match["market"]).strip().casefold(),
        )
        deduplicated.setdefault(key, match)
    return list(deduplicated.values())


def _sport_name(area: dict[str, Any]) -> str | None:
    value = str(area.get("SportName") or "Football").strip().casefold()
    return {
        "football": "Football",
        "basketball": "Basketball",
        "tennis": "Tennis",
    }.get(value)


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


def _market_kind(collection: dict[str, Any], sport: str) -> str | None:
    odds_type = collection.get("OddsType")
    name = odds_type.get("OddsTypeName", "") if isinstance(odds_type, dict) else ""
    odds_type_id = (
        str(odds_type.get("OddsTypeID", ""))
        if isinstance(odds_type, dict)
        else ""
    )
    normalized_name = " ".join(str(name).casefold().split())

    if sport == "Basketball":
        if odds_type_id == "9300" or normalized_name in {
            "moneyline",
            "match winner",
        }:
            return "Match Winner"
        if not any(
            phrase in normalized_name
            for phrase in ("total points", "points over/under", "total score")
        ):
            return None
        if any(
            term in normalized_name
            for term in ("half", "quarter", "1q", "2q", "3q", "4q", "team")
        ):
            return None
        line_values: list[Any] = [
            collection.get("SpecialBetValue"),
            collection.get("SpecialValueDisplay"),
        ]
        line_in_name = re.search(
            r"(?<!\d)\d+(?:[.,]\d+)?(?!\d)",
            normalized_name,
        )
        if line_in_name:
            line_values.insert(0, line_in_name.group())
        match_odds = collection.get("MatchOdds", [])
        if isinstance(match_odds, list):
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
        for value in line_values:
            try:
                line = float(str(value).replace(",", "."))
            except (TypeError, ValueError):
                continue
            if math.isfinite(line) and line > 0:
                return f"Over/Under {line:g} Points"
        return None

    if sport == "Tennis":
        if odds_type_id == "9388" or normalized_name in {
            "1-2",
            "moneyline",
            "match winner",
        }:
            return "Match Winner"
        return None

    if sport != "Football":
        return None

    if "draw no bet" in normalized_name or re.search(r"\bdnb\b", normalized_name):
        if not any(period in normalized_name for period in ("half", "early")):
            return "Draw No Bet"

    is_btts = (
        "both teams to score" in normalized_name
        or re.search(r"\bbtts\b", normalized_name)
        or re.search(r"\bgg\s*/\s*ng\b", normalized_name)
    )
    if is_btts and not any(
        period in normalized_name for period in ("half", "1st half", "2nd half")
    ):
        return "Both Teams to Score"
    if not any(term in normalized_name for term in ("total goals", "over/under")):
        return None
    if any(
        term in normalized_name
        for term in ("early", "half", "home team", "away team", "team total")
    ):
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
    for line in (1.5, 2.5, 3.5):
        line_pattern = rf"(?<!\d){line:.1f}(?!\d)"
        if re.search(line_pattern, normalized_name):
            return f"Over/Under {line:.1f} Goals"
        for value in line_values:
            try:
                if math.isclose(float(str(value).replace(",", ".")), line):
                    return f"Over/Under {line:.1f} Goals"
            except (TypeError, ValueError):
                continue
    return None


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


def _two_way_selections(
    selections: dict[str, float],
) -> tuple[float | None, float | None]:
    if len(selections) != 2 or {"x", "draw", "tie"}.intersection(selections):
        return None, None
    outcome_a = selections.get(
        "1",
        selections.get("home", selections.get("player 1")),
    )
    outcome_b = selections.get(
        "2",
        selections.get("away", selections.get("player 2")),
    )
    return outcome_a, outcome_b


def _parse_betking_payload(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(
        payload.get("AreaMatches"), list
    ):
        raise ValueError("BetKing feed must contain an AreaMatches list")

    matches: list[dict[str, Any]] = []
    for area in payload["AreaMatches"]:
        if not isinstance(area, dict):
            continue
        sport = _sport_name(area)
        if sport is None:
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
                kind = _market_kind(collection, sport)
                selections = _selections(collection)
                if kind == "Match Winner":
                    outcome_a, outcome_b = _two_way_selections(selections)
                    market = kind
                elif kind in {
                    "Over/Under 1.5 Goals",
                    "Over/Under 2.5 Goals",
                    "Over/Under 3.5 Goals",
                } or (
                    kind is not None
                    and re.fullmatch(r"Over/Under \d+(?:\.\d+)? Points", kind)
                ):
                    outcome_a, outcome_b = selections.get("over"), selections.get(
                        "under"
                    )
                    market = kind
                elif kind == "Both Teams to Score":
                    outcome_a = selections.get("yes", selections.get("gg"))
                    outcome_b = selections.get("no", selections.get("ng"))
                    market = kind
                elif kind == "Draw No Bet":
                    outcome_a = selections.get(
                        "home",
                        selections.get("1 dnb", selections.get("1")),
                    )
                    outcome_b = selections.get(
                        "away",
                        selections.get("2 dnb", selections.get("2")),
                    )
                    market = kind
                else:
                    continue
                if outcome_a is None or outcome_b is None:
                    continue

                matches.append(
                    {
                        "sport": sport,
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
    feed_url = (
        BETKING_FEED_URL.strip()
        if BETKING_FEED_URL and BETKING_FEED_URL.strip()
        else DEFAULT_BETKING_FEED_URL
    )
    parsed_url = urlparse(feed_url)
    if parsed_url.scheme == "file":
        return fetch_json_feed(feed_url, "BetKing", parse_payload)

    date_urls = _date_wide_urls(feed_url)
    if date_urls is not None:
        matches: list[dict[str, Any]] = []
        for date_url in date_urls:
            for sport_url in _sport_urls(date_url):
                response = curl_requests.get(
                    sport_url,
                    headers={"Accept": "application/json"},
                    timeout=15,
                )
                response.raise_for_status()
                matches.extend(parse_payload(response.json()))
        return _deduplicate_matches(matches)

    return fetch_json_feed(feed_url, "BetKing", parse_payload)
