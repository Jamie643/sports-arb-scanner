import math
import os

from dotenv import load_dotenv

load_dotenv()


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


DEFAULT_STAKE_NGN = _read_default_stake()
MAX_LOOKAHEAD_HOURS = _read_max_lookahead_hours()
MAX_ARBITRAGE_PROFIT_PCT = _read_max_arbitrage_profit_pct()
MIN_MINUTES_TO_KICKOFF = _read_min_minutes_to_kickoff()
MAX_KICKOFF_DIFF_MINUTES = 30
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
BETPAWA_FEED_URL = os.getenv("BETPAWA_FEED_URL")
BET9JA_FEED_URL = os.getenv("BET9JA_FEED_URL")
BETKING_FEED_URL = os.getenv("BETKING_FEED_URL")
