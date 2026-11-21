import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from typing import Any

from fastapi import FastAPI

from engine.arbitrage import find_arbitrage
from scrapers.bet9ja import fetch_matches as fetch_bet9ja_matches
from scrapers.betking import fetch_matches as fetch_betking_matches
from scrapers.betpawa import fetch_matches as fetch_betpawa_matches
from services.telegram import send_alert
from settings import BETKING_FEED_URL, DEFAULT_STAKE_NGN


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
SCAN_INTERVAL_SECONDS = 45


async def _fetch_feed(
    bookie: str, fetcher: Any
) -> tuple[str, list[dict[str, Any]] | Exception]:
    try:
        return bookie, await asyncio.to_thread(fetcher)
    except Exception as exc:
        return bookie, exc


def _opportunity_key(opportunity: dict[str, Any]) -> tuple[str, ...]:
    return (
        str(opportunity["home"]).casefold(),
        str(opportunity["away"]).casefold(),
        str(opportunity["kickoff"]),
        str(opportunity["market"]).casefold(),
        str(opportunity["leg_a"]["bookie"]),
        str(opportunity["leg_a"]["outcome"]),
        str(opportunity["leg_b"]["bookie"]),
        str(opportunity["leg_b"]["outcome"]),
    )


async def scan_once(
    alerted: set[tuple[str, ...]],
) -> None:
    fetches = [
        _fetch_feed("Betpawa", fetch_betpawa_matches),
        _fetch_feed("Bet9ja", fetch_bet9ja_matches),
    ]
    if BETKING_FEED_URL:
        fetches.append(_fetch_feed("BetKing", fetch_betking_matches))
    else:
        logger.info("Skipping BetKing: BETKING_FEED_URL is unset")
    results = await asyncio.gather(*fetches)
    feeds: dict[str, list[dict[str, Any]]] = {}
    all_feeds_succeeded = True
    for bookie, result in results:
        if isinstance(result, Exception):
            all_feeds_succeeded = False
            logger.error(
                "%s scrape failed: %s",
                bookie,
                result,
                exc_info=(type(result), result, result.__traceback__),
            )
        else:
            feeds[bookie] = result

    opportunities = find_arbitrage(
        feeds.get("Betpawa", []),
        feeds.get("Bet9ja", []),
        DEFAULT_STAKE_NGN,
        betking_matches=feeds.get("BetKing", []),
    )
    current_keys = {_opportunity_key(item) for item in opportunities}

    for opportunity in opportunities:
        key = _opportunity_key(opportunity)
        if key in alerted:
            continue
        try:
            await asyncio.to_thread(send_alert, opportunity)
            alerted.add(key)
            logger.info(
                "Telegram alert sent for %s vs %s",
                opportunity["home"],
                opportunity["away"],
            )
        except Exception:
            logger.exception(
                "Could not send Telegram alert for %s vs %s",
                opportunity["home"],
                opportunity["away"],
            )

    if all_feeds_succeeded:
        alerted.intersection_update(current_keys)


async def scanner_loop() -> None:
    alerted: set[tuple[str, ...]] = set()
    while True:
        try:
            await scan_once(alerted)
        except Exception:
            logger.exception("Unexpected scanner iteration failure")
        await asyncio.sleep(SCAN_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(_: FastAPI):
    task = asyncio.create_task(scanner_loop())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="Sports Arbitrage Scanner", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
