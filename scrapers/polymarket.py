import json
import logging
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
from settings import DEFAULT_POLYMARKET_FEED_URL, POLYMARKET_FEED_URL


_GAMMA_HEADERS = {
    "Accept": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}
_CLOB_BASE_URL = "https://clob.polymarket.com"
_POLYMARKET_HOME_URL = "https://polymarket.com/event/"
_EVENT_PAGE_SIZE = 100
_MAX_EVENT_PAGES = 5
_MAX_MARKETS = 500
_CLOB_BOOK_BATCH_SIZE = 100
_MATCHUP_PATTERN = re.compile(r"^\s*(.+?)\s+vs\.?\s+(.+?)\s*$", re.IGNORECASE)
_TOTAL_LINE_PATTERN = re.compile(
    r"(?:over\s*/\s*under|o\s*/\s*u)\s*(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
logger = logging.getLogger(__name__)


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except ValueError:
            return []
        return decoded if isinstance(decoded, list) else []
    return []


def _event_sport(event: dict[str, Any]) -> str | None:
    tags = event.get("tags")
    if not isinstance(tags, list):
        return None
    labels = {
        str(tag.get("label") or "").strip().casefold()
        for tag in tags
        if isinstance(tag, dict)
    }
    if "basketball" in labels:
        return "Basketball"
    if "tennis" in labels or "atp" in labels or "wta" in labels:
        return "Tennis"
    if "football" in labels or "soccer" in labels:
        return "Football"
    return None


def _event_matchup(title: Any) -> tuple[str, str] | None:
    if not isinstance(title, str):
        return None
    match = _MATCHUP_PATTERN.fullmatch(title)
    if match is None:
        return None
    home, away = match.group(1).strip(), match.group(2).strip()
    if not home or not away or home.casefold() == away.casefold():
        return None
    return home, away


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _market_line(market: dict[str, Any]) -> str | None:
    line = market.get("line")
    if line is None:
        line = market.get("groupItemTitle")
    if line is None:
        line = market.get("question")
    match = _TOTAL_LINE_PATTERN.search(str(line or ""))
    if match is None:
        if isinstance(line, (float, int)) and not isinstance(line, bool):
            try:
                number = float(line)
            except (TypeError, ValueError):
                return None
        elif isinstance(line, str):
            try:
                number = float(line.strip())
            except ValueError:
                return None
        else:
            return None
    else:
        try:
            number = float(match.group(1))
        except ValueError:
            return None
    if not math.isfinite(number) or number <= 0:
        return None
    return f"{number:g}"


def _supported_market(
    sport: str,
    market: dict[str, Any],
) -> tuple[str, tuple[str, str]] | None:
    market_type = str(market.get("sportsMarketType") or "").strip().casefold()
    if market_type == "moneyline" and sport in {"Basketball", "Tennis"}:
        return "Match Winner", ("home", "away")

    if market_type != "totals":
        return None
    details = " ".join(
        str(market.get(key) or "")
        for key in ("question", "groupItemTitle")
    ).casefold()
    if re.search(
        r"\b(?:1st|2nd|3rd|4th|first|second|third|fourth)\s*"
        r"(?:half|quarter|period|q(?:tr)?)\b"
        r"|\b(?:1h|2h|1q|2q|3q|4q)\b"
        r"|\bteam\s+total\b",
        details,
    ):
        return None
    line = _market_line(market)
    if line is None:
        return None
    if sport == "Football":
        if line not in {"1.5", "2.5", "3.5"}:
            return None
        return f"Over/Under {line} Goals", ("over", "under")
    if sport == "Basketball":
        return f"Over/Under {line} Points", ("over", "under")
    return None


def _active(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in {"true", "1"}


def _candidate_markets(
    payload: Any,
    now_utc: datetime,
) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        events = payload.get("events")
        if events is None and isinstance(payload.get("data"), dict):
            events = payload["data"].get("events")
    else:
        events = payload
    if not isinstance(events, list):
        raise ValueError("Polymarket Gamma feed must contain an events list")

    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    latest = now_utc + timedelta(days=7)
    for event in events:
        if not isinstance(event, dict):
            continue
        if not _active(event.get("active")) or _active(event.get("closed")):
            continue
        sport = _event_sport(event)
        matchup = _event_matchup(event.get("title"))
        markets = event.get("markets")
        if sport is None or matchup is None or not isinstance(markets, list):
            continue
        kickoff = _parse_time(event.get("startTime") or event.get("eventDate"))
        if kickoff is None or not now_utc < kickoff <= latest:
            continue

        event_id = str(event.get("id") or event.get("slug") or event.get("title"))
        for market in markets:
            if not isinstance(market, dict):
                continue
            if not _active(market.get("active")) or _active(market.get("closed")):
                continue
            supported = _supported_market(sport, market)
            if supported is None:
                continue
            market_name, side_keys = supported
            outcomes = _json_list(market.get("outcomes"))
            token_ids = _json_list(market.get("clobTokenIds"))
            if len(outcomes) != 2 or len(token_ids) != 2:
                continue
            token_by_side: dict[str, str] = {}
            home, away = matchup
            for outcome, token_id in zip(outcomes, token_ids, strict=True):
                if not isinstance(outcome, str) or not isinstance(token_id, str):
                    token_by_side = {}
                    break
                normalized_outcome = outcome.strip().casefold()
                if market_name == "Match Winner":
                    if normalized_outcome == home.casefold():
                        side = "home"
                    elif normalized_outcome == away.casefold():
                        side = "away"
                    else:
                        token_by_side = {}
                        break
                else:
                    side = {
                        "over": "over",
                        "under": "under",
                    }.get(normalized_outcome, "")
                    if not side:
                        token_by_side = {}
                        break
                if side in token_by_side:
                    token_by_side = {}
                    break
                token_by_side[side] = token_id
            if set(token_by_side) != set(side_keys):
                continue

            identity = (event_id, market_name)
            if identity in seen:
                continue
            seen.add(identity)
            candidates.append(
                {
                    "sport": sport,
                    "home": home,
                    "away": away,
                    "kickoff": kickoff.isoformat(),
                    "market": market_name,
                    "token_a": token_by_side[side_keys[0]],
                    "token_b": token_by_side[side_keys[1]],
                    "url": _POLYMARKET_HOME_URL
                    + str(event.get("slug") or market.get("slug") or ""),
                }
            )
            if len(candidates) >= _MAX_MARKETS:
                logger.warning(
                    "Polymarket candidate market cap reached (%d)",
                    _MAX_MARKETS,
                )
                return candidates
    return candidates


def _fetch_event_pages(
    feed_url: str,
    now_utc: datetime,
) -> list[dict[str, Any]]:
    start_min = now_utc.isoformat(timespec="seconds").replace("+00:00", "Z")
    start_max = (now_utc + timedelta(days=7)).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")
    events: list[dict[str, Any]] = []
    seen: set[str] = set()
    for page in range(_MAX_EVENT_PAGES):
        response = curl_requests.get(
            feed_url,
            params={
                "active": "true",
                "closed": "false",
                "version": "v2",
                "tag_id": "1",
                "start_time_min": start_min,
                "start_time_max": start_max,
                "limit": _EVENT_PAGE_SIZE,
                "offset": page * _EVENT_PAGE_SIZE,
            },
            headers=_GAMMA_HEADERS,
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise ValueError("Polymarket Gamma response must be a JSON list")
        new_count = 0
        for event in payload:
            if not isinstance(event, dict):
                continue
            identity = str(event.get("id") or event.get("slug") or "")
            if not identity or identity in seen:
                continue
            seen.add(identity)
            events.append(event)
            new_count += 1
        if len(payload) < _EVENT_PAGE_SIZE or new_count == 0:
            break
    return events


def _fetch_best_asks(token_ids: list[str]) -> dict[str, float]:
    best_asks: dict[str, float] = {}
    for start in range(0, len(token_ids), _CLOB_BOOK_BATCH_SIZE):
        batch = token_ids[start : start + _CLOB_BOOK_BATCH_SIZE]
        response = curl_requests.post(
            f"{_CLOB_BASE_URL}/books",
            json=[{"token_id": token_id} for token_id in batch],
            headers=_GAMMA_HEADERS,
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise ValueError("Polymarket CLOB response must be a JSON list")
        for book in payload:
            if not isinstance(book, dict):
                continue
            token_id = str(book.get("asset_id") or book.get("token_id") or "")
            asks = book.get("asks")
            if not token_id or not isinstance(asks, list):
                continue
            prices: list[float] = []
            for ask in asks:
                if not isinstance(ask, dict):
                    continue
                try:
                    price = float(ask.get("price"))
                except (TypeError, ValueError):
                    continue
                if math.isfinite(price) and 0.01 < price < 0.99:
                    prices.append(price)
            if prices:
                best_asks[token_id] = min(prices)
    return best_asks


def _rows_from_candidates(
    candidates: list[dict[str, Any]],
    best_asks: dict[str, float],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        price_a = best_asks.get(candidate["token_a"])
        price_b = best_asks.get(candidate["token_b"])
        if (
            price_a is None
            or price_b is None
            or not math.isfinite(price_a)
            or not math.isfinite(price_b)
            or not 0.01 < price_a < 0.99
            or not 0.01 < price_b < 0.99
        ):
            continue
        rows.append(
            {
                "sport": candidate["sport"],
                "home": candidate["home"],
                "away": candidate["away"],
                "kickoff": candidate["kickoff"],
                "market": candidate["market"],
                "outcome_a": 1 / price_a,
                "outcome_b": 1 / price_b,
                "url": candidate["url"],
                "league": "",
            }
        )
    return normalize_matches(rows, "Polymarket")


def parse_payload(
    payload: Any,
    *,
    best_asks: dict[str, float] | None = None,
    now_utc: datetime | None = None,
) -> list[dict[str, Any]]:
    """Map normalized rows or Gamma events with supplied CLOB BUY asks."""
    if is_normalized_payload(payload):
        return normalize_matches(payload, "Polymarket")
    scan_time = now_utc or datetime.now(timezone.utc)
    if scan_time.tzinfo is None:
        scan_time = scan_time.replace(tzinfo=timezone.utc)
    candidates = _candidate_markets(payload, scan_time.astimezone(timezone.utc))
    return _rows_from_candidates(candidates, best_asks or {})


def fetch_matches() -> list[dict[str, Any]]:
    """Fetch upcoming Gamma events and actionable CLOB best-ask prices."""
    feed_url = (
        POLYMARKET_FEED_URL.strip()
        if POLYMARKET_FEED_URL and POLYMARKET_FEED_URL.strip()
        else DEFAULT_POLYMARKET_FEED_URL
    )
    parsed_url = urlparse(feed_url)
    if parsed_url.scheme == "file":
        return fetch_json_feed(feed_url, "Polymarket", parse_payload)

    scan_time = datetime.now(timezone.utc)
    events = _fetch_event_pages(feed_url, scan_time)
    candidates = _candidate_markets(events, scan_time)
    token_ids = list(
        dict.fromkeys(
            token_id
            for candidate in candidates
            for token_id in (candidate["token_a"], candidate["token_b"])
        )
    )
    if not token_ids:
        return []
    return _rows_from_candidates(candidates, _fetch_best_asks(token_ids))
