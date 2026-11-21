import math
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from typing import Any

from rapidfuzz import fuzz

from settings import (
    MAX_ARBITRAGE_PROFIT_PCT,
    MAX_KICKOFF_DIFF_MINUTES,
    MAX_LOOKAHEAD_HOURS,
    MIN_MINUTES_TO_KICKOFF,
)


MIN_MATCH_SCORE = 85
MIN_LEAGUE_MATCH_SCORE = 75
MAX_IMPLIED_PROBABILITY = 0.99
STAKE_INCREMENT_NGN = 100


def _is_pre_match(
    kickoff: Any,
    now_utc: datetime,
    earliest_utc: datetime,
    cutoff_utc: datetime,
) -> bool:
    kickoff_utc = _parse_kickoff(kickoff)
    return (
        kickoff_utc is not None
        and now_utc < kickoff_utc
        and earliest_utc <= kickoff_utc <= cutoff_utc
    )


def _parse_kickoff(kickoff: Any) -> datetime | None:
    if not isinstance(kickoff, str):
        return None
    try:
        parsed = datetime.fromisoformat(kickoff.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _scan_window(
    max_lookahead_hours: float,
    min_minutes_to_kickoff: int,
    now_utc: datetime | None,
) -> tuple[datetime, datetime, datetime]:
    if not math.isfinite(max_lookahead_hours) or max_lookahead_hours <= 0:
        raise ValueError("max_lookahead_hours must be greater than zero")
    if min_minutes_to_kickoff < 0:
        raise ValueError("min_minutes_to_kickoff cannot be negative")

    scan_time = now_utc or datetime.now(timezone.utc)
    if scan_time.tzinfo is None:
        scan_time = scan_time.replace(tzinfo=timezone.utc)
    scan_time = scan_time.astimezone(timezone.utc)
    return (
        scan_time,
        scan_time + timedelta(minutes=min_minutes_to_kickoff),
        scan_time + timedelta(hours=max_lookahead_hours),
    )


def _event_match_score(first: dict[str, Any], second: dict[str, Any]) -> int | None:
    home_score = fuzz.token_set_ratio(str(first["home"]), str(second["home"]))
    away_score = fuzz.token_set_ratio(str(first["away"]), str(second["away"]))
    if min(home_score, away_score) < MIN_MATCH_SCORE:
        return None

    first_league = str(first.get("league", "")).strip()
    second_league = str(second.get("league", "")).strip()
    if (
        first_league
        and second_league
        and fuzz.token_set_ratio(first_league, second_league)
        < MIN_LEAGUE_MATCH_SCORE
    ):
        return None

    first_kickoff = _parse_kickoff(first.get("kickoff"))
    second_kickoff = _parse_kickoff(second.get("kickoff"))
    if (
        first_kickoff is None
        or second_kickoff is None
        or abs(first_kickoff - second_kickoff)
        > timedelta(minutes=MAX_KICKOFF_DIFF_MINUTES)
    ):
        return None

    return int(min(home_score, away_score))


def _market_outcomes(market: str) -> tuple[str, str] | None:
    return {
        "Over/Under 1.5 Goals": ("Over 1.5", "Under 1.5"),
        "Over/Under 2.5 Goals": ("Over 2.5", "Under 2.5"),
        "Over/Under 3.5 Goals": ("Over 3.5", "Under 3.5"),
        "Both Teams to Score": ("Yes", "No"),
        "Draw No Bet": ("Home", "Away"),
    }.get(market)


def _rounded_stakes(
    odds_a: float, odds_b: float, bankroll: int
) -> tuple[int, int, float]:
    total_stake = bankroll // STAKE_INCREMENT_NGN * STAKE_INCREMENT_NGN
    units = total_stake // STAKE_INCREMENT_NGN
    if units < 2:
        return 0, 0, 0.0

    ideal_a = total_stake * odds_b / (odds_a + odds_b)
    lower_units = math.floor(ideal_a / STAKE_INCREMENT_NGN)
    candidates = {
        max(1, min(units - 1, lower_units)),
        max(1, min(units - 1, lower_units + 1)),
    }

    best: tuple[int, int, float] | None = None
    for stake_a_units in candidates:
        stake_a = stake_a_units * STAKE_INCREMENT_NGN
        stake_b = total_stake - stake_a
        profit = min(stake_a * odds_a, stake_b * odds_b) - total_stake
        candidate = (stake_a, stake_b, profit)
        if best is None or candidate[2] > best[2]:
            best = candidate

    assert best is not None
    return best


def _build_opportunity(
    first: dict[str, Any],
    second: dict[str, Any],
    score: int,
    first_outcome_key: str,
    second_outcome_key: str,
    first_outcome_name: str,
    second_outcome_name: str,
    bankroll: int,
) -> dict[str, Any] | None:
    odds_a = float(first[first_outcome_key])
    odds_b = float(second[second_outcome_key])
    if (
        not math.isfinite(odds_a)
        or not math.isfinite(odds_b)
        or odds_a <= 1
        or odds_b <= 1
    ):
        return None
    implied_probability = 1 / odds_a + 1 / odds_b
    if implied_probability >= MAX_IMPLIED_PROBABILITY:
        return None

    stake_a, stake_b, decisive_profit = _rounded_stakes(odds_a, odds_b, bankroll)
    market = str(first["market"])
    is_draw_no_bet = market == "Draw No Bet"
    if decisive_profit <= 0:
        return None
    guaranteed_profit = 0.0 if is_draw_no_bet else decisive_profit
    opportunity = {
        "home": first["home"],
        "away": first["away"],
        "kickoff": first["kickoff"],
        "market": market,
        "match_score": score,
        "leg_a": {
            "bookie": first["bookie"],
            "outcome": first_outcome_name,
            "odds": odds_a,
            "stake_ngn": stake_a,
            "url": first["url"],
        },
        "leg_b": {
            "bookie": second["bookie"],
            "outcome": second_outcome_name,
            "odds": odds_b,
            "stake_ngn": stake_b,
            "url": second["url"],
        },
        "total_stake_ngn": stake_a + stake_b,
        "guaranteed_profit_ngn": guaranteed_profit,
        "roi_pct": decisive_profit / (stake_a + stake_b) * 100,
    }
    if is_draw_no_bet:
        opportunity["profit_on_decisive_result_ngn"] = decisive_profit
        opportunity["draw_refund_ngn"] = stake_a + stake_b
        opportunity["draw_voids_both"] = True
    return opportunity


def _matching_pairs(
    feeds: tuple[tuple[str, list[dict[str, Any]]], ...],
    scan_time: datetime,
    earliest_utc: datetime,
    cutoff_utc: datetime,
) -> Iterator[tuple[dict[str, Any], dict[str, Any], int]]:
    for first_index, (first_bookie, first_feed) in enumerate(feeds):
        for second_bookie, second_feed in feeds[first_index + 1 :]:
            for first in first_feed:
                if str(first.get("bookie", "")).casefold() != first_bookie.casefold():
                    continue
                if not _is_pre_match(
                    first.get("kickoff"), scan_time, earliest_utc, cutoff_utc
                ):
                    continue
                first_market = str(first.get("market", ""))
                if _market_outcomes(first_market) is None:
                    continue
                for second in second_feed:
                    if (
                        str(second.get("bookie", "")).casefold()
                        != second_bookie.casefold()
                    ):
                        continue
                    if not _is_pre_match(
                        second.get("kickoff"), scan_time, earliest_utc, cutoff_utc
                    ):
                        continue
                    if first_market != second.get("market"):
                        continue

                    score = _event_match_score(first, second)
                    if score is not None:
                        yield first, second, score


def _feeds(
    betpawa_matches: list[dict[str, Any]],
    bet9ja_matches: list[dict[str, Any]],
    betking_matches: list[dict[str, Any]] | None,
) -> tuple[tuple[str, list[dict[str, Any]]], ...]:
    return (
        ("Betpawa", betpawa_matches),
        ("Bet9ja", bet9ja_matches),
        ("BetKing", betking_matches or []),
    )


def count_matched_pairs(
    betpawa_matches: list[dict[str, Any]],
    bet9ja_matches: list[dict[str, Any]],
    *,
    betking_matches: list[dict[str, Any]] | None = None,
    max_lookahead_hours: float = MAX_LOOKAHEAD_HOURS,
    min_minutes_to_kickoff: int = MIN_MINUTES_TO_KICKOFF,
    now_utc: datetime | None = None,
) -> int:
    """Count distinct supported-market fixture pairs across configured feeds."""
    scan_time, earliest_utc, cutoff_utc = _scan_window(
        max_lookahead_hours,
        min_minutes_to_kickoff,
        now_utc,
    )
    fixture_pairs = {
        (
            str(first["bookie"]).casefold(),
            str(first["home"]).casefold(),
            str(first["away"]).casefold(),
            str(first["kickoff"]),
            str(second["bookie"]).casefold(),
            str(second["home"]).casefold(),
            str(second["away"]).casefold(),
            str(second["kickoff"]),
        )
        for first, second, _ in _matching_pairs(
            _feeds(betpawa_matches, bet9ja_matches, betking_matches),
            scan_time,
            earliest_utc,
            cutoff_utc,
        )
    }
    return len(fixture_pairs)


def find_arbitrage(
    betpawa_matches: list[dict[str, Any]],
    bet9ja_matches: list[dict[str, Any]],
    bankroll: int = 10_000,
    max_lookahead_hours: float = MAX_LOOKAHEAD_HOURS,
    *,
    now_utc: datetime | None = None,
    betking_matches: list[dict[str, Any]] | None = None,
    max_arbitrage_profit_pct: float = MAX_ARBITRAGE_PROFIT_PCT,
    min_minutes_to_kickoff: int = MIN_MINUTES_TO_KICKOFF,
) -> list[dict[str, Any]]:
    """Find cross-bookmaker two-way arbitrage with rounded Naira stakes.

    Each feed must use canonical market names and put Over/Home/Yes in
    outcome_a and Under/Away/No in outcome_b.
    Odds must remain available at placement time; the probability threshold
    provides an edge buffer but cannot protect against a changed price. Events
    must start at least the configured minimum minutes from now and no later
    than the UTC lookahead cutoff. Opportunities above the configured ROI cap
    are discarded. Draw No Bet opportunities break even if drawn because both
    stakes are refunded; their reported profit applies to decisive results.
    When provided, BetKing matches are compared against both existing feeds.
    """
    if bankroll <= 0:
        raise ValueError("bankroll must be greater than zero")
    if (
        not math.isfinite(max_arbitrage_profit_pct)
        or max_arbitrage_profit_pct <= 0
    ):
        raise ValueError("max_arbitrage_profit_pct must be greater than zero")
    scan_time, earliest_utc, cutoff_utc = _scan_window(
        max_lookahead_hours,
        min_minutes_to_kickoff,
        now_utc,
    )

    opportunities: list[dict[str, Any]] = []
    for first, second, score in _matching_pairs(
        _feeds(betpawa_matches, bet9ja_matches, betking_matches),
        scan_time,
        earliest_utc,
        cutoff_utc,
    ):
        market_outcomes = _market_outcomes(str(first["market"]))
        assert market_outcomes is not None
        outcome_a, outcome_b = market_outcomes
        for candidate in (
            _build_opportunity(
                first,
                second,
                score,
                "outcome_a",
                "outcome_b",
                outcome_a,
                outcome_b,
                bankroll,
            ),
            _build_opportunity(
                second,
                first,
                score,
                "outcome_a",
                "outcome_b",
                outcome_a,
                outcome_b,
                bankroll,
            ),
        ):
            if (
                candidate is not None
                and candidate["roi_pct"] <= max_arbitrage_profit_pct
            ):
                opportunities.append(candidate)

    return opportunities
