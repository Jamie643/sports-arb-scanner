import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from engine.arbitrage import count_matched_pairs, find_arbitrage
from services.telegram import format_alert
from main import scan_once


def _future_kickoff(hours: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


class ArbitrageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.betpawa = [
            {
                "bookie": "Betpawa",
                "home": "Arsenal FC",
                "away": "Manchester City",
                "kickoff": _future_kickoff(6),
                "market": "Over/Under 2.5 Goals",
                "outcome_a": 2.10,
                "outcome_b": 1.80,
                "url": "https://example.test/betpawa",
            }
        ]
        self.bet9ja = [
            {
                "bookie": "Bet9ja",
                "home": "Arsenal",
                "away": "Manchester City FC",
                "kickoff": self.betpawa[0]["kickoff"],
                "market": "Over/Under 2.5 Goals",
                "outcome_a": 1.95,
                "outcome_b": 2.05,
                "url": "https://example.test/bet9ja",
            }
        ]

    def test_detects_arb_and_allocates_rounded_stakes(self) -> None:
        opportunities = find_arbitrage(self.betpawa, self.bet9ja, 10_000)

        self.assertEqual(len(opportunities), 1)
        opportunity = opportunities[0]
        self.assertEqual(opportunity["leg_a"]["bookie"], "Betpawa")
        self.assertEqual(opportunity["leg_a"]["outcome"], "Over 2.5")
        self.assertEqual(opportunity["leg_b"]["bookie"], "Bet9ja")
        self.assertEqual(opportunity["leg_b"]["outcome"], "Under 2.5")
        self.assertEqual(opportunity["total_stake_ngn"], 10_000)
        self.assertEqual(opportunity["leg_a"]["stake_ngn"] % 100, 0)
        self.assertEqual(opportunity["leg_b"]["stake_ngn"] % 100, 0)
        self.assertGreater(opportunity["guaranteed_profit_ngn"], 0)

    def test_rejects_opportunity_below_required_edge(self) -> None:
        self.betpawa[0]["outcome_a"] = 2.0
        self.betpawa[0]["outcome_b"] = 2.05
        self.bet9ja[0]["outcome_a"] = 1.9
        self.bet9ja[0]["outcome_b"] = 2.0

        self.assertEqual(find_arbitrage(self.betpawa, self.bet9ja), [])

    def test_rejects_unmatched_events(self) -> None:
        self.bet9ja[0]["home"] = "Chelsea"
        self.bet9ja[0]["away"] = "Tottenham"

        self.assertEqual(find_arbitrage(self.betpawa, self.bet9ja), [])

    def test_rejects_reversed_home_and_away_fixtures(self) -> None:
        self.bet9ja[0]["home"] = self.betpawa[0]["away"]
        self.bet9ja[0]["away"] = self.betpawa[0]["home"]

        self.assertEqual(find_arbitrage(self.betpawa, self.bet9ja), [])
        self.assertEqual(count_matched_pairs(self.betpawa, self.bet9ja), 0)

    def test_requires_kickoffs_within_thirty_minutes(self) -> None:
        now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        first_kickoff = now + timedelta(hours=5)

        self.betpawa[0]["kickoff"] = first_kickoff.isoformat()
        self.bet9ja[0]["kickoff"] = (first_kickoff + timedelta(minutes=30)).isoformat()
        self.assertEqual(count_matched_pairs(self.betpawa, self.bet9ja, now_utc=now), 1)

        self.bet9ja[0]["kickoff"] = (first_kickoff + timedelta(minutes=31)).isoformat()
        self.assertEqual(count_matched_pairs(self.betpawa, self.bet9ja, now_utc=now), 0)
        self.assertEqual(find_arbitrage(self.betpawa, self.bet9ja, now_utc=now), [])

    def test_matches_leagues_only_when_both_are_present_and_compatible(self) -> None:
        self.betpawa[0]["league"] = "Czech - 1.Liga"
        self.bet9ja[0]["league"] = "Czech - U19 1st Division"
        self.assertEqual(count_matched_pairs(self.betpawa, self.bet9ja), 0)

        self.bet9ja[0]["league"] = "Czech 1 Liga"
        self.assertEqual(count_matched_pairs(self.betpawa, self.bet9ja), 1)

        self.bet9ja[0].pop("league")
        self.assertEqual(count_matched_pairs(self.betpawa, self.bet9ja), 1)

    def test_supports_both_teams_to_score(self) -> None:
        self.betpawa[0]["market"] = "Both Teams to Score"
        self.bet9ja[0]["market"] = "Both Teams to Score"

        opportunities = find_arbitrage(self.betpawa, self.bet9ja)

        self.assertEqual(len(opportunities), 1)
        self.assertEqual(opportunities[0]["leg_a"]["outcome"], "Yes")
        self.assertEqual(opportunities[0]["leg_b"]["outcome"], "No")

    def test_arbitrages_new_goal_lines_and_draw_no_bet(self) -> None:
        cases = (
            ("Over/Under 1.5 Goals", 2.10, 1.80, 1.90, 2.10, "Over 1.5", "Under 1.5"),
            ("Over/Under 3.5 Goals", 2.10, 1.80, 1.90, 2.10, "Over 3.5", "Under 3.5"),
            ("Draw No Bet", 2.20, 1.60, 1.70, 2.20, "Home", "Away"),
        )
        for market, a_home, a_away, b_home, b_away, outcome_a, outcome_b in cases:
            with self.subTest(market=market):
                betpawa = [{
                    **self.betpawa[0],
                    "market": market,
                    "outcome_a": a_home,
                    "outcome_b": a_away,
                }]
                bet9ja = [{
                    **self.bet9ja[0],
                    "market": market,
                    "outcome_a": b_home,
                    "outcome_b": b_away,
                }]

                opportunities = find_arbitrage(betpawa, bet9ja)

                self.assertEqual(len(opportunities), 1)
                opportunity = opportunities[0]
                self.assertEqual(opportunity["market"], market)
                self.assertEqual(opportunity["leg_a"]["outcome"], outcome_a)
                self.assertEqual(opportunity["leg_b"]["outcome"], outcome_b)
                self.assertEqual(opportunity["total_stake_ngn"], 10_000)
                self.assertGreater(opportunity["roi_pct"], 0)
                if market == "Draw No Bet":
                    self.assertEqual(opportunity["guaranteed_profit_ngn"], 0)
                    self.assertEqual(
                        opportunity["profit_on_decisive_result_ngn"],
                        1_000,
                    )
                    self.assertEqual(opportunity["draw_refund_ngn"], 10_000)
                    self.assertTrue(opportunity["draw_voids_both"])

    def test_different_canonical_markets_never_cross_match(self) -> None:
        for first_market, second_market in (
            ("Over/Under 1.5 Goals", "Over/Under 2.5 Goals"),
            ("Over/Under 2.5 Goals", "Over/Under 3.5 Goals"),
            ("Over/Under 1.5 Goals", "Over/Under 3.5 Goals"),
            ("Over/Under 1.5 Goals", "over/under 1.5 Goals"),
            ("Draw No Bet", "Over/Under 3.5 Goals"),
        ):
            with self.subTest(markets=(first_market, second_market)):
                betpawa = [{**self.betpawa[0], "market": first_market}]
                bet9ja = [{**self.bet9ja[0], "market": second_market}]

                self.assertEqual(find_arbitrage(betpawa, bet9ja), [])

    def test_compares_betking_matches_when_provided(self) -> None:
        betking = [
            {
                **self.bet9ja[0],
                "bookie": "BetKing",
                "outcome_a": 1.95,
                "outcome_b": 2.05,
            }
        ]

        opportunities = find_arbitrage(
            self.betpawa,
            [],
            betking_matches=betking,
        )

        self.assertEqual(len(opportunities), 1)
        self.assertEqual(opportunities[0]["leg_a"]["bookie"], "Betpawa")
        self.assertEqual(opportunities[0]["leg_b"]["bookie"], "BetKing")

    def test_rejects_extreme_arbitrage_roi_above_configured_maximum(self) -> None:
        betpawa = [{**self.betpawa[0], "outcome_a": 3.0, "outcome_b": 3.0}]
        bet9ja = [{**self.bet9ja[0], "outcome_a": 3.0, "outcome_b": 3.0}]

        self.assertEqual(
            find_arbitrage(
                betpawa,
                bet9ja,
                max_arbitrage_profit_pct=15.0,
            ),
            [],
        )
        self.assertEqual(
            len(
                find_arbitrage(
                    betpawa,
                    bet9ja,
                    max_arbitrage_profit_pct=50.0,
                )
            ),
            2,
        )

    def test_skips_matches_kicking_off_inside_minimum_buffer(self) -> None:
        now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        betpawa = []
        bet9ja = []
        for home, minutes in (("Soon", 14), ("Ready", 15)):
            kickoff = (now + timedelta(minutes=minutes)).isoformat()
            betpawa.append(
                {
                    **self.betpawa[0],
                    "home": home,
                    "away": f"{home} FC",
                    "kickoff": kickoff,
                }
            )
            bet9ja.append(
                {
                    **self.bet9ja[0],
                    "home": home,
                    "away": f"{home} FC",
                    "kickoff": kickoff,
                }
            )

        opportunities = find_arbitrage(betpawa, bet9ja, now_utc=now)

        self.assertEqual(
            {opportunity["home"] for opportunity in opportunities},
            {"Ready"},
        )
        self.assertEqual(
            count_matched_pairs(betpawa, bet9ja, now_utc=now),
            1,
        )

    def test_realistic_over_under_and_btts_odds_for_two_bookmakers(self) -> None:
        betpawa = [
            {
                "bookie": "Betpawa",
                "home": "Lagos United",
                "away": "Abuja FC",
                "kickoff": _future_kickoff(5),
                "market": "Over/Under 2.5 Goals",
                "outcome_a": 1.95,
                "outcome_b": 2.10,
                "url": "https://betpawa.example/match/lagos-abuja/ou",
            },
            {
                "bookie": "Betpawa",
                "home": "Enugu Rangers",
                "away": "Kano Pillars",
                "kickoff": _future_kickoff(7),
                "market": "Both Teams to Score",
                "outcome_a": 1.88,
                "outcome_b": 2.10,
                "url": "https://betpawa.example/match/enugu-kano/btts",
            },
        ]
        bet9ja = [
            {
                "bookie": "Bet9ja",
                "home": "Lagos United",
                "away": "Abuja FC",
                "kickoff": betpawa[0]["kickoff"],
                "market": "Over/Under 2.5 Goals",
                "outcome_a": 2.15,
                "outcome_b": 1.90,
                "url": "https://bet9ja.example/match/lagos-abuja/ou",
            },
            {
                "bookie": "Bet9ja",
                "home": "Enugu Rangers",
                "away": "Kano Pillars",
                "kickoff": betpawa[1]["kickoff"],
                "market": "Both Teams to Score",
                "outcome_a": 2.05,
                "outcome_b": 1.90,
                "url": "https://bet9ja.example/match/enugu-kano/btts",
            },
        ]

        opportunities = find_arbitrage(betpawa, bet9ja, 10_000)

        self.assertEqual(len(opportunities), 2)
        markets = {item["market"] for item in opportunities}
        self.assertEqual(
            markets,
            {"Over/Under 2.5 Goals", "Both Teams to Score"},
        )
        for opportunity in opportunities:
            self.assertEqual(opportunity["total_stake_ngn"], 10_000)
            self.assertGreater(opportunity["guaranteed_profit_ngn"], 0)
            self.assertEqual(opportunity["leg_a"]["stake_ngn"] % 100, 0)
            self.assertEqual(opportunity["leg_b"]["stake_ngn"] % 100, 0)

    def test_ignores_already_started_or_past_kickoff_events(self) -> None:
        betpawa = [
            {
                "bookie": "Betpawa",
                "home": "Lagos United",
                "away": "Abuja FC",
                "kickoff": "2020-01-01T16:00:00Z",
                "market": "Over/Under 2.5 Goals",
                "outcome_a": 2.10,
                "outcome_b": 1.80,
                "url": "https://betpawa.example/match/past",
            }
        ]
        bet9ja = [
            {
                "bookie": "Bet9ja",
                "home": "Lagos United",
                "away": "Abuja FC",
                "kickoff": "2020-01-01T16:00:00Z",
                "market": "Over/Under 2.5 Goals",
                "outcome_a": 1.95,
                "outcome_b": 2.05,
                "url": "https://bet9ja.example/match/past",
            }
        ]

        self.assertEqual(find_arbitrage(betpawa, bet9ja, 10_000), [])

    def test_enforces_24_hour_lookahead_cutoff(self) -> None:
        now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        kickoff_cases = (
            ("Inside", "Inside FC", now + timedelta(hours=23)),
            ("Boundary", "Boundary FC", now + timedelta(hours=24)),
            ("Beyond", "Beyond FC", now + timedelta(hours=24, seconds=1)),
            ("At now", "At now FC", now),
        )
        betpawa = []
        bet9ja = []
        for home, away, kickoff in kickoff_cases:
            betpawa.append(
                {
                    **self.betpawa[0],
                    "home": home,
                    "away": away,
                    "kickoff": kickoff.isoformat(),
                }
            )
            bet9ja.append(
                {
                    **self.bet9ja[0],
                    "home": home,
                    "away": away,
                    "kickoff": kickoff.isoformat(),
                }
            )

        opportunities = find_arbitrage(betpawa, bet9ja, now_utc=now)

        self.assertEqual(
            {opportunity["home"] for opportunity in opportunities},
            {"Inside", "Boundary"},
        )

    def test_alert_format_contains_odds_stakes_profit_and_roi(self) -> None:
        opportunity = {
            "home": "Lagos United",
            "away": "Abuja FC",
            "kickoff": "2026-12-01T16:00:00Z",
            "market": "Over/Under 2.5 Goals",
            "match_score": 96,
            "leg_a": {
                "bookie": "Betpawa",
                "outcome": "Over 2.5",
                "odds": 2.15,
                "stake_ngn": 4700,
            },
            "leg_b": {
                "bookie": "Bet9ja",
                "outcome": "Under 2.5",
                "odds": 2.05,
                "stake_ngn": 5300,
            },
            "total_stake_ngn": 10_000,
            "guaranteed_profit_ngn": 125.0,
            "roi_pct": 1.25,
        }

        message = format_alert(opportunity)

        self.assertIn("Lagos United vs Abuja FC", message)
        self.assertIn("Betpawa — Over 2.5 @ 2.15", message)
        self.assertIn("Stake: ₦4,700", message)
        self.assertIn("Bet9ja — Under 2.5 @ 2.05", message)
        self.assertIn("Stake: ₦5,300", message)
        self.assertIn("Guaranteed profit*: ₦125.00", message)
        self.assertIn("ROI: 1.25%", message)

    def test_draw_no_bet_alert_explains_draw_refund(self) -> None:
        opportunity = {
            "home": "Home FC",
            "away": "Away FC",
            "kickoff": "2026-12-01T16:00:00Z",
            "market": "Draw No Bet",
            "match_score": 99,
            "leg_a": {
                "bookie": "BetKing",
                "outcome": "Home",
                "odds": 2.2,
                "stake_ngn": 5000,
            },
            "leg_b": {
                "bookie": "Betpawa",
                "outcome": "Away",
                "odds": 2.2,
                "stake_ngn": 5000,
            },
            "total_stake_ngn": 10_000,
            "guaranteed_profit_ngn": 0,
            "profit_on_decisive_result_ngn": 1_000,
            "draw_refund_ngn": 10_000,
            "draw_voids_both": True,
            "roi_pct": 10,
        }

        message = format_alert(opportunity)

        self.assertIn("Profit on decisive result*: ₦1,000.00", message)
        self.assertIn("Draw: both stakes refunded (₦10,000)", message)
        self.assertNotIn("Guaranteed profit", message)

    def test_scanner_fetches_betking_when_feed_is_configured(self) -> None:
        betking_matches = [
            {
                **self.bet9ja[0],
                "bookie": "BetKing",
            }
        ]
        with (
            patch("main.BETKING_FEED_URL", "https://feed.example/betking"),
            patch("main.fetch_betpawa_matches", return_value=[]),
            patch("main.fetch_bet9ja_matches", return_value=[]),
            patch(
                "main.fetch_betking_matches",
                return_value=betking_matches,
            ) as fetch_betking,
            patch("main.find_arbitrage", return_value=[]) as find_arbitrage,
        ):
            asyncio.run(scan_once(set()))

        fetch_betking.assert_called_once_with()
        self.assertEqual(
            find_arbitrage.call_args.kwargs["betking_matches"],
            betking_matches,
        )

    def test_scanner_uses_empty_betking_feed_when_unconfigured(self) -> None:
        with (
            patch("main.BETKING_FEED_URL", ""),
            patch("main.fetch_betpawa_matches", return_value=[]),
            patch("main.fetch_bet9ja_matches", return_value=[]),
            patch("main.fetch_betking_matches") as fetch_betking,
            patch("main.find_arbitrage", return_value=[]) as find_arbitrage,
        ):
            asyncio.run(scan_once(set()))

        fetch_betking.assert_not_called()
        self.assertEqual(
            find_arbitrage.call_args.kwargs["betking_matches"],
            [],
        )

    def test_failed_telegram_send_keeps_batch_running_and_is_not_deduplicated(self) -> None:
        betpawa = [
            {
                "bookie": "Betpawa",
                "home": "Lagos United",
                "away": "Abuja FC",
                "kickoff": _future_kickoff(5),
                "market": "Over/Under 2.5 Goals",
                "outcome_a": 2.10,
                "outcome_b": 1.80,
                "url": "https://betpawa.example/match/lagos-abuja/ou",
            },
            {
                "bookie": "Betpawa",
                "home": "Enugu Rangers",
                "away": "Kano Pillars",
                "kickoff": _future_kickoff(7),
                "market": "Both Teams to Score",
                "outcome_a": 1.88,
                "outcome_b": 2.10,
                "url": "https://betpawa.example/match/enugu-kano/btts",
            },
        ]
        bet9ja = [
            {
                "bookie": "Bet9ja",
                "home": "Lagos United",
                "away": "Abuja FC",
                "kickoff": betpawa[0]["kickoff"],
                "market": "Over/Under 2.5 Goals",
                "outcome_a": 1.95,
                "outcome_b": 2.05,
                "url": "https://bet9ja.example/match/lagos-abuja/ou",
            },
            {
                "bookie": "Bet9ja",
                "home": "Enugu Rangers",
                "away": "Kano Pillars",
                "kickoff": betpawa[1]["kickoff"],
                "market": "Both Teams to Score",
                "outcome_a": 2.05,
                "outcome_b": 1.90,
                "url": "https://bet9ja.example/match/enugu-kano/btts",
            },
        ]

        alerted = set()
        with (
            patch("main.BETKING_FEED_URL", ""),
            patch(
                "main.fetch_betpawa_matches",
                return_value=betpawa,
            ),
            patch(
                "main.fetch_bet9ja_matches",
                return_value=bet9ja,
            ),
            patch(
                "main.send_alert",
                side_effect=RuntimeError("Telegram unavailable"),
            ) as mocked_send,
        ):
            asyncio.run(scan_once(alerted))

        self.assertEqual(mocked_send.call_count, 2)
        self.assertEqual(alerted, set())


if __name__ == "__main__":
    unittest.main()
