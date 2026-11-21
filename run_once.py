import logging
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from engine.arbitrage import count_matched_pairs, find_arbitrage
from scrapers.bet9ja import fetch_matches as fetch_bet9ja_matches
from scrapers.betking import fetch_matches as fetch_betking_matches
from scrapers.betpawa import fetch_matches as fetch_betpawa_matches
from services.telegram import (
    format_empty_scan_notification,
    send_alert,
    send_message,
    validate_telegram_credentials,
)
from settings import (
    BET9JA_FEED_URL,
    BETKING_FEED_URL,
    DEFAULT_STAKE_NGN,
    MAX_ARBITRAGE_PROFIT_PCT,
    MAX_LOOKAHEAD_HOURS,
    MIN_MINUTES_TO_KICKOFF,
    NOTIFY_EMPTY,
)


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _fetch_matches(
    bookie: str,
    fetcher: Callable[[], list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    try:
        matches = fetcher()
        logger.info("Fetched %d %s matches", len(matches), bookie)
        return matches
    except Exception:
        logger.exception("%s feed fetch failed", bookie)
        return []


def main() -> int:
    betpawa_matches = _fetch_matches("Betpawa", fetch_betpawa_matches)
    if BET9JA_FEED_URL:
        bet9ja_matches = _fetch_matches("Bet9ja", fetch_bet9ja_matches)
    else:
        logger.info("Skipping Bet9ja: BET9JA_FEED_URL is unset")
        bet9ja_matches = []
    if BETKING_FEED_URL:
        betking_matches = _fetch_matches("BetKing", fetch_betking_matches)
    else:
        logger.info("Skipping BetKing: BETKING_FEED_URL is unset")
        betking_matches = []

    scan_time = datetime.now(timezone.utc)
    try:
        matched_pairs = count_matched_pairs(
            betpawa_matches,
            bet9ja_matches,
            betking_matches=betking_matches,
            max_lookahead_hours=MAX_LOOKAHEAD_HOURS,
            min_minutes_to_kickoff=MIN_MINUTES_TO_KICKOFF,
            now_utc=scan_time,
        )
        opportunities = find_arbitrage(
            betpawa_matches,
            bet9ja_matches,
            DEFAULT_STAKE_NGN,
            MAX_LOOKAHEAD_HOURS,
            now_utc=scan_time,
            betking_matches=betking_matches,
            max_arbitrage_profit_pct=MAX_ARBITRAGE_PROFIT_PCT,
            min_minutes_to_kickoff=MIN_MINUTES_TO_KICKOFF,
        )
    except Exception:
        logger.exception("Arbitrage scan failed")
        return 0

    logger.info(
        "Scan summary: betking_rows=%d betpawa_rows=%d matched_pairs=%d "
        "arbs_found=%d",
        len(betking_matches),
        len(betpawa_matches),
        matched_pairs,
        len(opportunities),
    )
    for opportunity in opportunities:
        try:
            send_alert(opportunity)
            logger.info(
                "Telegram alert delivered for %s vs %s",
                opportunity.get("home", "unknown team"),
                opportunity.get("away", "unknown team"),
            )
        except Exception:
            logger.exception(
                "Could not send Telegram alert for %s vs %s",
                opportunity.get("home", "unknown team"),
                opportunity.get("away", "unknown team"),
            )

    if not opportunities and NOTIFY_EMPTY:
        try:
            send_message(
                format_empty_scan_notification(
                    lookahead_hours=MAX_LOOKAHEAD_HOURS,
                    betking_rows=len(betking_matches),
                    betpawa_rows=len(betpawa_matches),
                    bet9ja_rows=len(bet9ja_matches),
                    matched_pairs=matched_pairs,
                )
            )
            logger.info("Telegram empty-scan notification delivered")
        except Exception:
            logger.exception("Could not send empty-scan Telegram notification")
    elif not opportunities:
        try:
            validate_telegram_credentials()
        except RuntimeError as exc:
            logger.warning("Telegram is not configured: %s", exc)
        logger.info(
            "Telegram message skipped: no arbitrage opportunities and "
            "NOTIFY_EMPTY is false"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
