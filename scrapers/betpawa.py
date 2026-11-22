import json
import math
import re
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

from curl_cffi import requests as curl_requests

from scrapers.common import (
    fetch_json_feed,
    is_normalized_payload,
    normalize_matches,
)
from settings import BETPAWA_FEED_URL, DEFAULT_BETPAWA_FEED_URL


_BETPAWA_HOME_URL = "https://www.betpawa.ng/"
_BETPAWA_LIVE_QUERY_PATH = "/api/sportsbook/v4/events/lists/by-queries"
_BETPAWA_SPORT_MARKETS = (
    ("2", ("5000", "3795", "4703")),
    ("3", ("4791", "5009")),
    ("452", ("2043818",)),
)
_BETPAWA_QUERY_TAKE = 40
_BETPAWA_MAX_QUERY_PAGES = 5


def _native_events(payload: Any) -> list[dict[str, Any]] | None:
    if isinstance(payload, list):
        events = payload
    elif isinstance(payload, dict) and isinstance(payload.get("responses"), list):
        events = []
        for group in payload["responses"]:
            if isinstance(group, dict) and isinstance(group.get("responses"), list):
                events.extend(
                    event
                    for event in group["responses"]
                    if isinstance(event, dict)
                )
    elif (
        isinstance(payload, dict)
        and isinstance(payload.get("events"), list)
        and payload["events"]
    ):
        events = [
            event for event in payload["events"] if isinstance(event, dict)
        ]
    elif isinstance(payload, dict) and (
        isinstance(payload.get("participants"), list)
        or isinstance(payload.get("name"), str)
    ):
        events = [payload]
    else:
        return None
    return events


def _event_teams(event: dict[str, Any]) -> tuple[str, str] | None:
    participants = event.get("participants")
    if isinstance(participants, list):
        named = [
            participant
            for participant in participants
            if isinstance(participant, dict)
            and str(participant.get("name", "")).strip()
        ]

        def position(participant: dict[str, Any]) -> float:
            try:
                return float(participant.get("position", 0))
            except (TypeError, ValueError):
                return 0

        named.sort(key=position)
        if len(named) >= 2:
            return (
                str(named[0]["name"]).strip(),
                str(named[1]["name"]).strip(),
            )

    name = event.get("name")
    if isinstance(name, str) and " - " in name:
        home, away = name.split(" - ", maxsplit=1)
        if home.strip() and away.strip():
            return home.strip(), away.strip()
    return None


def _league_name(event: dict[str, Any]) -> str:
    keys = (
        "leagueName",
        "league",
        "competitionName",
        "competition",
        "tournamentName",
        "tournament",
        "eventGroupName",
        "eventGroup",
        "championshipName",
        "championship",
    )
    for key in keys:
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            for name_key in ("name", "displayName"):
                name = value.get(name_key)
                if isinstance(name, str) and name.strip():
                    return name.strip()
    return ""


def _event_sport(event: dict[str, Any]) -> str | None:
    category = event.get("category")
    if not isinstance(category, dict):
        return "Football"
    category_id = str(category.get("id", ""))
    category_name = str(category.get("name", "")).strip().casefold()
    return {
        "2": "Football",
        "3": "Basketball",
        "452": "Tennis",
    }.get(
        category_id,
        {
            "football": "Football",
            "basketball": "Basketball",
            "tennis": "Tennis",
        }.get(category_name),
    )


def _total_line(market: dict[str, Any], row: dict[str, Any]) -> str | None:
    values: list[Any] = []
    for source in (row, market):
        for key in ("specifier", "handicap"):
            value = source.get(key)
            if isinstance(value, dict):
                values.extend(value.get(name) for name in ("total", "points"))
            elif value is not None:
                values.append(value)
    for value in values:
        try:
            line = float(str(value).replace(",", "."))
        except (TypeError, ValueError):
            continue
        if math.isfinite(line) and line > 0:
            return f"{line:g}"
    return None


def _market_kind(
    market: dict[str, Any],
    row: dict[str, Any],
    sport: str,
) -> str | None:
    market_type = market.get("marketType")
    market_type = market_type if isinstance(market_type, dict) else {}
    market_type_id = str(market_type.get("id", ""))
    descriptors = " ".join(
        str(value)
        for value in (
            market_type.get("name"),
            market_type.get("displayName"),
            market.get("name"),
            market.get("displayName"),
        )
        if value is not None
    ).casefold()
    line_details = " ".join(
        str(value)
        for value in (
            market.get("specifier"),
            row.get("specifier"),
            market.get("handicap"),
            row.get("handicap"),
        )
        if value is not None
    ).casefold()

    if sport == "Basketball":
        if (
            market_type_id == "4791" or "moneyline" in descriptors
        ) and not re.search(
            r"\b(?:1h|2h|[1-4]q|[1-4](?:st|nd|rd|th)\s+quarter)\b",
            descriptors,
        ):
            return "Match Winner"
        is_full_match_total = (
            market_type_id == "5009"
            or "total score over/under" in descriptors
            or "total points" in descriptors
        )
        if (
            is_full_match_total
            and not any(
                term in descriptors
                for term in (
                    "1h",
                    "2h",
                    "1q",
                    "2q",
                    "3q",
                    "4q",
                    "quarter",
                    "1st half",
                    "2nd half",
                )
            )
        ):
            line = _total_line(market, row)
            if line is not None:
                return f"Over/Under {line} Points"
        return None

    if sport == "Tennis":
        if market_type_id == "2043818" or "moneyline" in descriptors:
            if not re.search(r"\b(?:[1-5]s|set)\b", descriptors):
                return "Match Winner"
        return None

    if sport != "Football":
        return None

    if (
        market_type_id == "4703"
        or "draw no bet" in descriptors
        or re.search(r"\bdnb\b", descriptors)
    ) and not any(term in descriptors for term in ("half", "1st half", "2nd half")):
        return "Draw No Bet"
    if (
        market_type_id == "3795"
        or "both teams to score" in descriptors
        or re.search(r"\bbtts\b", descriptors)
    ):
        return "Both Teams to Score"
    if any(
        term in descriptors
        for term in ("half", "home team", "away team", "team total")
    ):
        return None
    is_goal_total = any(
        term in descriptors for term in ("goal", "over/under", "total")
    )
    if market_type_id == "5000" or is_goal_total:
        for line in ("1.5", "2.5", "3.5"):
            if re.search(
                rf"(?<!\d){line[0]}[.,]5(?!\d)",
                descriptors + " " + line_details,
            ):
                return f"Over/Under {line} Goals"
    return None


def _row_prices(row: dict[str, Any]) -> dict[str, float]:
    prices = row.get("prices")
    if not isinstance(prices, list):
        return {}
    selections: dict[str, float] = {}
    for price in prices:
        if not isinstance(price, dict) or price.get("suspended") is True:
            continue
        name = str(price.get("name") or price.get("displayName") or "").strip()
        normalized_name = name.casefold()
        try:
            odds = float(price.get("odds"))
        except (TypeError, ValueError):
            continue
        if math.isfinite(odds) and odds > 1:
            selections[normalized_name] = odds
    return selections


def _two_way_prices(
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


def _parse_native_payload(payload: Any) -> list[dict[str, Any]] | None:
    events = _native_events(payload)
    if events is None:
        return None

    matches: list[dict[str, Any]] = []
    for event in events:
        sport = _event_sport(event)
        if sport is None:
            continue
        teams = _event_teams(event)
        kickoff = event.get("startTime")
        if teams is None or not isinstance(kickoff, str) or not kickoff:
            continue
        markets = event.get("markets")
        if not isinstance(markets, list):
            continue
        for market in markets:
            if not isinstance(market, dict):
                continue
            rows = market.get("row")
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                kind = _market_kind(market, row, sport)
                selections = _row_prices(row)
                if kind == "Match Winner":
                    outcome_a, outcome_b = _two_way_prices(selections)
                    market_name = kind
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
                    market_name = kind
                elif kind == "Both Teams to Score":
                    outcome_a = selections.get("yes", selections.get("gg"))
                    outcome_b = selections.get("no", selections.get("ng"))
                    market_name = kind
                elif kind == "Draw No Bet":
                    outcome_a = selections.get("home", selections.get("1"))
                    outcome_b = selections.get("away", selections.get("2"))
                    market_name = kind
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
                        "market": market_name,
                        "outcome_a": outcome_a,
                        "outcome_b": outcome_b,
                        "league": _league_name(event),
                        "url": str(
                            event.get("url")
                            or event.get("URL")
                            or _BETPAWA_HOME_URL
                        ),
                    }
                )
    return matches


def _live_query(skip: int) -> dict[str, Any]:
    return {
        "queries": [
            {
                "query": {
                    "eventType": "UPCOMING",
                    "categories": [category_id],
                    "hasOdds": True,
                    "marketTypes": list(market_types),
                },
                "view": {"marketTypes": list(market_types)},
                "skip": skip,
                "take": _BETPAWA_QUERY_TAKE,
            }
            for category_id, market_types in _BETPAWA_SPORT_MARKETS
        ]
    }


def _event_identity(event: dict[str, Any]) -> tuple[str, ...]:
    category = event.get("category")
    category_id = (
        str(category.get("id", ""))
        if isinstance(category, dict)
        else ""
    )
    event_id = event.get("id")
    if event_id is not None:
        return "id", category_id, str(event_id)
    teams = _event_teams(event)
    kickoff = event.get("startTime")
    if teams is not None and isinstance(kickoff, str):
        return (
            "match",
            category_id,
            teams[0].strip().casefold(),
            teams[1].strip().casefold(),
            kickoff.strip(),
        )
    return "payload", json.dumps(event, sort_keys=True, separators=(",", ":"))


def _fetch_live_query(
    feed_url: str,
    native_parser: Callable[[Any], Any] | None,
) -> list[dict[str, Any]]:
    events_by_key: dict[tuple[str, ...], dict[str, Any]] = {}
    for page_index in range(_BETPAWA_MAX_QUERY_PAGES):
        skip = page_index * _BETPAWA_QUERY_TAKE
        response = curl_requests.get(
            feed_url,
            params={
                "q": json.dumps(_live_query(skip), separators=(",", ":")),
            },
            headers={
                "Accept": "application/json",
                "X-Pawa-Brand": "betpawa-nigeria",
            },
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        page_events = _native_events(payload)
        if page_events is None:
            if page_index == 0:
                return parse_payload(payload, native_parser)
            raise ValueError("Betpawa paginated response is not an event response")

        for event in page_events:
            events_by_key.setdefault(_event_identity(event), event)
        if len(page_events) < _BETPAWA_QUERY_TAKE:
            break

    return parse_payload(
        {"responses": [{"responses": list(events_by_key.values())}]},
        native_parser,
    )


def parse_payload(
    payload: Any,
    native_parser: Callable[[Any], Any] | None = None,
) -> list[dict[str, Any]]:
    """Adapt Betpawa JSON to the scanner schema.

    Native football events map supported full-time totals, BTTS, and Draw No
    Bet. Basketball maps full-time Moneyline and Points totals, and tennis maps
    full-time Moneyline. The normalized-list format remains supported;
    ``native_parser`` handles other Betpawa payload variants.
    """
    if is_normalized_payload(payload):
        return normalize_matches(payload, "Betpawa")
    native_matches = _parse_native_payload(payload)
    if native_matches is not None:
        return normalize_matches(native_matches, "Betpawa")
    if native_parser is None:
        raise ValueError(
            "Betpawa payload is not normalized and no native parser was provided"
        )
    return normalize_matches(native_parser(payload), "Betpawa")


def fetch_matches(
    native_parser: Callable[[Any], Any] | None = None,
) -> list[dict[str, Any]]:
    """Fetch and normalize Betpawa odds, using its configured live query URL."""
    feed_url = (
        BETPAWA_FEED_URL.strip()
        if BETPAWA_FEED_URL and BETPAWA_FEED_URL.strip()
        else DEFAULT_BETPAWA_FEED_URL
    )
    if urlparse(feed_url).scheme in {"http", "https"}:
        if urlparse(feed_url).path.rstrip("/").endswith(
            _BETPAWA_LIVE_QUERY_PATH
        ):
            return _fetch_live_query(feed_url, native_parser)

    return fetch_json_feed(
        feed_url,
        "Betpawa",
        lambda payload: parse_payload(payload, native_parser),
    )
