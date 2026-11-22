import math
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from curl_cffi import requests as curl_requests

from scrapers.common import (
    fetch_json_feed,
    is_normalized_payload,
    normalize_matches,
)
from settings import DEFAULT_MSPORT_FEED_URL, MSPORT_FEED_URL


_MSPORT_HOME_URL = "https://www.msport.com/ng/"
_MSPORT_HEADERS = {
    "Accept": "application/json",
    "OperId": "2",
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}
_MSPORT_SPORTS = {
    "sr:sport:1": "Football",
    "sr:sport:2": "Basketball",
    "sr:sport:5": "Tennis",
}


def _native_events(payload: Any) -> list[dict[str, Any]] | None:
    if isinstance(payload, list):
        return [event for event in payload if isinstance(event, dict)]
    if not isinstance(payload, dict):
        return None

    data = payload.get("data")
    if isinstance(data, dict):
        payload = data
    events = payload.get("events")
    if isinstance(events, list):
        return [event for event in events if isinstance(event, dict)]

    tournaments = payload.get("tournaments")
    if isinstance(tournaments, list):
        return [
            event
            for tournament in tournaments
            if isinstance(tournament, dict)
            for event in tournament.get("events", [])
            if isinstance(event, dict)
        ]
    return None


def _kickoff(value: Any) -> str | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(value):
            return None
        try:
            return datetime.fromtimestamp(
                value / 1000,
                timezone.utc,
            ).isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _market_kind(market: dict[str, Any], sport: str) -> tuple[str, str] | None:
    market_id = str(market.get("id", ""))
    name = " ".join(
        str(market.get("name") or market.get("description") or "")
        .casefold()
        .split()
    )

    if sport == "Football":
        if market_id == "18" and name == "over/under":
            specifiers = str(market.get("specifiers") or "")
            line_match = re.search(r"(?:^|&)total=(\d+(?:\.\d+)?)", specifiers)
            if line_match and line_match.group(1) in {"1.5", "2.5", "3.5"}:
                line = line_match.group(1)
                return f"Over/Under {line} Goals", line
        if market_id == "29" and name == "gg/ng":
            return "Both Teams to Score", ""
        if market_id == "11" and name in {"dnb", "draw no bet"}:
            return "Draw No Bet", ""
        return None

    if sport == "Basketball":
        if market_id == "219" and name == "winner (incl. ot)":
            return "Match Winner", ""
        if market_id == "225" and name == "o/u (incl. ot)":
            specifiers = str(market.get("specifiers") or "")
            line_match = re.search(r"(?:^|&)total=(\d+(?:\.\d+)?)", specifiers)
            if line_match:
                line = line_match.group(1)
                return f"Over/Under {line} Points", line
        return None

    if (
        sport == "Tennis"
        and market_id == "186"
        and name == "winner"
        and not market.get("specifiers")
    ):
        return "Match Winner", ""
    return None


def _market_prices(
    market: dict[str, Any],
    sport: str,
    line: str,
) -> tuple[float, float] | None:
    outcomes = market.get("outcomes")
    if not isinstance(outcomes, list) or len(outcomes) != 2:
        return None

    prices: dict[str, float] = {}
    for outcome in outcomes:
        if not isinstance(outcome, dict):
            return None
        if str(outcome.get("isActive", "")).strip().casefold() not in {
            "1",
            "true",
        }:
            return None
        description = str(outcome.get("description") or "").strip().casefold()
        if line and sport in {"Football", "Basketball"}:
            if description == f"over {line}":
                selection = "over"
            elif description == f"under {line}":
                selection = "under"
            else:
                return None
        elif sport == "Football" and market.get("id") == 29:
            selection = {"yes": "yes", "no": "no"}.get(description, "")
        else:
            selection = {"home": "home", "away": "away"}.get(description, "")
        if not selection or selection in prices:
            return None
        try:
            odds = float(outcome.get("odds"))
        except (TypeError, ValueError):
            return None
        if not math.isfinite(odds) or odds <= 1:
            return None
        prices[selection] = odds

    if line and sport in {"Football", "Basketball"}:
        keys = ("over", "under")
    elif sport == "Football" and market.get("id") == 29:
        keys = ("yes", "no")
    else:
        keys = ("home", "away")
    if set(prices) != set(keys):
        return None
    return prices[keys[0]], prices[keys[1]]


def _parse_native_payload(payload: Any) -> list[dict[str, Any]] | None:
    events = _native_events(payload)
    if events is None:
        return None

    matches: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for event in events:
        sport = _MSPORT_SPORTS.get(str(event.get("sportId", "")))
        if sport is None or str(event.get("status", "")) != "0":
            continue
        booking_status = str(event.get("bookingStatus") or "").casefold()
        if booking_status and booking_status not in {"booked", "buyable"}:
            continue

        home = event.get("homeTeam")
        away = event.get("awayTeam")
        kickoff = _kickoff(event.get("startTime"))
        markets = event.get("markets")
        if (
            not isinstance(home, str)
            or not home.strip()
            or not isinstance(away, str)
            or not away.strip()
            or kickoff is None
            or not isinstance(markets, list)
        ):
            continue

        for market in markets:
            if not isinstance(market, dict):
                continue
            kind = _market_kind(market, sport)
            if kind is None:
                continue
            market_name, line = kind
            prices = _market_prices(market, sport, line)
            if prices is None:
                continue
            identity = (
                str(
                    event.get("eventId")
                    or "|".join((home.strip(), away.strip(), kickoff))
                ),
                market_name,
            )
            if identity in seen:
                continue
            seen.add(identity)
            tournament = event.get("tournament")
            league = (
                tournament.strip()
                if isinstance(tournament, str)
                else ""
            )
            matches.append(
                {
                    "sport": sport,
                    "home": home.strip(),
                    "away": away.strip(),
                    "kickoff": kickoff,
                    "market": market_name,
                    "outcome_a": prices[0],
                    "outcome_b": prices[1],
                    "url": _MSPORT_HOME_URL,
                    "league": league,
                }
            )
    return matches


def parse_payload(payload: Any) -> list[dict[str, Any]]:
    """Map MSport event JSON or normalized sample rows to scanner records."""
    if is_normalized_payload(payload):
        return normalize_matches(payload, "MSport")
    native_matches = _parse_native_payload(payload)
    if native_matches is None:
        raise ValueError("MSport feed must contain an events list")
    return normalize_matches(native_matches, "MSport")


def _deduplicate_matches(
    matches: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    unique: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    for match in matches:
        key = (
            match["sport"],
            match["home"].casefold(),
            match["away"].casefold(),
            match["kickoff"],
            match["market"],
        )
        unique.setdefault(key, match)
    return list(unique.values())


def fetch_matches() -> list[dict[str, Any]]:
    """Fetch MSport's Nigerian soccer, basketball, and tennis event lists."""
    feed_url = (
        MSPORT_FEED_URL.strip()
        if MSPORT_FEED_URL and MSPORT_FEED_URL.strip()
        else DEFAULT_MSPORT_FEED_URL
    )
    if urlparse(feed_url).scheme == "file":
        return fetch_json_feed(feed_url, "MSport", parse_payload)

    matches: list[dict[str, Any]] = []
    for sport_id in _MSPORT_SPORTS:
        response = curl_requests.get(
            feed_url,
            params={"sportId": sport_id},
            headers=_MSPORT_HEADERS,
            timeout=15,
        )
        response.raise_for_status()
        matches.extend(parse_payload(response.json()))
    return _deduplicate_matches(matches)
