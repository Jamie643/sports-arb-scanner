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
_BETPAWA_CATEGORY_ID = "2"
_BETPAWA_MARKET_TYPES = ("5000", "3795")
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


def _market_kind(market: dict[str, Any], row: dict[str, Any]) -> str | None:
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

    if (
        market_type_id == "3795"
        or "both teams to score" in descriptors
        or re.search(r"\bbtts\b", descriptors)
    ):
        return "btts"
    has_25_line = bool(
        re.search(r"(?<!\d)2[.,]5(?!\d)", descriptors + " " + line_details)
    )
    is_goal_total = any(term in descriptors for term in ("goal", "over/under", "total"))
    if has_25_line and (market_type_id == "5000" or is_goal_total):
        return "over_under_25"
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


def _parse_native_payload(payload: Any) -> list[dict[str, Any]] | None:
    events = _native_events(payload)
    if events is None:
        return None

    matches: list[dict[str, Any]] = []
    for event in events:
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
                kind = _market_kind(market, row)
                selections = _row_prices(row)
                if kind == "over_under_25":
                    outcome_a, outcome_b = selections.get("over"), selections.get(
                        "under"
                    )
                    market_name = "Over/Under 2.5 Goals"
                elif kind == "btts":
                    outcome_a = selections.get("yes", selections.get("gg"))
                    outcome_b = selections.get("no", selections.get("ng"))
                    market_name = "Both Teams to Score"
                else:
                    continue
                if outcome_a is None or outcome_b is None:
                    continue
                matches.append(
                    {
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
    market_types = list(_BETPAWA_MARKET_TYPES)
    return {
        "queries": [
            {
                "query": {
                    "eventType": "UPCOMING",
                    "categories": [_BETPAWA_CATEGORY_ID],
                    "hasOdds": True,
                    "marketTypes": market_types,
                },
                "view": {"marketTypes": market_types},
                "skip": skip,
                "take": _BETPAWA_QUERY_TAKE,
            }
        ]
    }


def _event_identity(event: dict[str, Any]) -> tuple[str, ...]:
    event_id = event.get("id")
    if event_id is not None:
        return "id", str(event_id)
    teams = _event_teams(event)
    kickoff = event.get("startTime")
    if teams is not None and isinstance(kickoff, str):
        return (
            "match",
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

    Native event responses are mapped for full-time Over/Under 2.5 and BTTS.
    The normalized-list format remains supported. ``native_parser`` can still
    be supplied for other Betpawa payload variants.
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
