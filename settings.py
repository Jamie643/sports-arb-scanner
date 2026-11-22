import math
import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()

DEFAULT_BETKING_FEED_URL = (
    "https://sportsapicdn-desktop.betking.com/api/feeds/prematch/"
    "GetEvents/en/{date}/0/0/1"
)
DEFAULT_BETPAWA_FEED_URL = (
    "https://www.betpawa.ng/api/sportsbook/v4/events/lists/by-queries"
)
DEFAULT_MSPORT_FEED_URL = (
    "https://www.msport.com/api/ng/facts-center/query/frontend/"
    "all-matches/next-7-days"
)


def _read_feed_url(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default

    feed_url = value.strip()
    if any(character.isspace() for character in feed_url):
        raise ValueError(f"{name} must be a valid HTTP, HTTPS, or file URL")
    try:
        parsed_url = urlparse(feed_url)
    except ValueError as exc:
        raise ValueError(
            f"{name} must be a valid HTTP, HTTPS, or file URL"
        ) from exc
    if parsed_url.scheme in {"http", "https"}:
        try:
            valid_http_url = bool(
                parsed_url.hostname
                and parsed_url.port != 0
                and not parsed_url.netloc.endswith(":")
                and parsed_url.username is None
                and parsed_url.password is None
            )
        except ValueError:
            valid_http_url = False
        if valid_http_url:
            return feed_url
    elif (
        parsed_url.scheme == "file"
        and parsed_url.netloc in {"", "localhost"}
        and Path(parsed_url.path).is_absolute()
        and not parsed_url.query
        and not parsed_url.fragment
    ):
        return feed_url

    raise ValueError(f"{name} must be a valid HTTP, HTTPS, or file URL")


def _read_default_stake() -> int:
    value = os.getenv("DEFAULT_STAKE_NGN", "10000")
    try:
        stake = int(value)
    except ValueError as exc:
        raise ValueError("DEFAULT_STAKE_NGN must be a positive whole number") from exc
    if stake <= 0:
        raise ValueError("DEFAULT_STAKE_NGN must be greater than zero")
    return stake


def _read_max_lookahead_hours() -> float:
    value = os.getenv("MAX_LOOKAHEAD_HOURS", "24.0")
    try:
        hours = float(value)
    except ValueError as exc:
        raise ValueError("MAX_LOOKAHEAD_HOURS must be a positive number") from exc
    if not math.isfinite(hours) or hours <= 0:
        raise ValueError("MAX_LOOKAHEAD_HOURS must be greater than zero")
    return hours


def _read_max_arbitrage_profit_pct() -> float:
    value = os.getenv("MAX_ARBITRAGE_PROFIT_PCT", "15.0")
    try:
        profit_pct = float(value)
    except ValueError as exc:
        raise ValueError(
            "MAX_ARBITRAGE_PROFIT_PCT must be a positive number"
        ) from exc
    if not math.isfinite(profit_pct) or profit_pct <= 0:
        raise ValueError("MAX_ARBITRAGE_PROFIT_PCT must be greater than zero")
    return profit_pct


def _read_min_minutes_to_kickoff() -> int:
    value = os.getenv("MIN_MINUTES_TO_KICKOFF", "15")
    try:
        minutes = int(value)
    except ValueError as exc:
        raise ValueError(
            "MIN_MINUTES_TO_KICKOFF must be a non-negative integer"
        ) from exc
    if minutes < 0:
        raise ValueError("MIN_MINUTES_TO_KICKOFF must be a non-negative integer")
    return minutes


def _read_notify_empty() -> bool:
    value = os.getenv("NOTIFY_EMPTY")
    if value is None or not value.strip():
        return True

    normalized = value.strip().casefold()
    if normalized not in {"true", "false"}:
        raise ValueError("NOTIFY_EMPTY must be true or false")
    return normalized == "true"


DEFAULT_STAKE_NGN = _read_default_stake()
MAX_LOOKAHEAD_HOURS = _read_max_lookahead_hours()
MAX_ARBITRAGE_PROFIT_PCT = _read_max_arbitrage_profit_pct()
MIN_MINUTES_TO_KICKOFF = _read_min_minutes_to_kickoff()
NOTIFY_EMPTY = _read_notify_empty()
MAX_KICKOFF_DIFF_MINUTES = 30
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
BETPAWA_FEED_URL = _read_feed_url(
    "BETPAWA_FEED_URL",
    DEFAULT_BETPAWA_FEED_URL,
)
BET9JA_FEED_URL = os.getenv("BET9JA_FEED_URL")
BETKING_FEED_URL = _read_feed_url(
    "BETKING_FEED_URL",
    DEFAULT_BETKING_FEED_URL,
)
MSPORT_FEED_URL = _read_feed_url(
    "MSPORT_FEED_URL",
    DEFAULT_MSPORT_FEED_URL,
)
