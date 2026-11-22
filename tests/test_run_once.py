import unittest
from unittest.mock import patch

from run_once import main


class RunOnceTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = patch("run_once.POLYMARKET_FEED_URL", "")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_skips_bet9ja_cleanly_when_feed_is_unset(self) -> None:
        with (
            patch("run_once.BET9JA_FEED_URL", ""),
            patch("run_once.BETKING_FEED_URL", ""),
            patch("run_once.fetch_betpawa_matches", return_value=[]),
            patch("run_once.fetch_msport_matches", return_value=[]),
            patch("run_once.fetch_bet9ja_matches") as fetch_bet9ja,
            patch("run_once.fetch_betking_matches") as fetch_betking,
            patch("run_once.find_arbitrage", return_value=[]) as find_arbitrage,
            patch("run_once.logger.info") as logger_info,
        ):
            result = main()

        self.assertEqual(result, 0)
        fetch_bet9ja.assert_not_called()
        fetch_betking.assert_not_called()
        self.assertEqual(find_arbitrage.call_args.args[1], [])
        self.assertIn(
            ("Skipping Bet9ja: BET9JA_FEED_URL is unset",),
            [call.args for call in logger_info.call_args_list],
        )

    def test_fetches_bet9ja_when_feed_is_configured(self) -> None:
        bet9ja_matches = [{"bookie": "Bet9ja", "home": "Team A"}]
        with (
            patch("run_once.BET9JA_FEED_URL", "https://feed.example/bet9ja"),
            patch("run_once.BETKING_FEED_URL", ""),
            patch("run_once.fetch_betpawa_matches", return_value=[]),
            patch("run_once.fetch_msport_matches", return_value=[]),
            patch(
                "run_once.fetch_bet9ja_matches",
                return_value=bet9ja_matches,
            ) as fetch_bet9ja,
            patch("run_once.fetch_betking_matches"),
            patch("run_once.find_arbitrage", return_value=[]) as find_arbitrage,
        ):
            result = main()

        self.assertEqual(result, 0)
        fetch_bet9ja.assert_called_once_with()
        self.assertEqual(find_arbitrage.call_args.args[1], bet9ja_matches)

    def test_sends_each_opportunity_and_continues_after_telegram_errors(self) -> None:
        opportunities = [
            {"home": "Team A", "away": "Team B"},
            {"home": "Team C", "away": "Team D"},
        ]
        with (
            patch("run_once.BETKING_FEED_URL", ""),
            patch("run_once.fetch_betpawa_matches", return_value=[]),
            patch("run_once.fetch_bet9ja_matches", return_value=[]),
            patch("run_once.fetch_msport_matches", return_value=[]),
            patch("run_once.fetch_betking_matches") as fetch_betking,
            patch("run_once.find_arbitrage", return_value=opportunities),
            patch(
                "run_once.send_alert",
                side_effect=RuntimeError("Telegram down"),
            ) as send_alert,
            patch("run_once.send_message") as send_message,
            patch("run_once.logger.exception"),
        ):
            result = main()

        self.assertEqual(result, 0)
        self.assertEqual(send_alert.call_count, 2)
        fetch_betking.assert_not_called()
        send_message.assert_not_called()

    def test_fetches_betking_when_feed_is_configured(self) -> None:
        betking_matches = [{"bookie": "BetKing", "home": "Team A"}]
        with (
            patch("run_once.BETKING_FEED_URL", "https://feed.example/betking"),
            patch("run_once.fetch_betpawa_matches", return_value=[]),
            patch("run_once.fetch_bet9ja_matches", return_value=[]),
            patch(
                "run_once.fetch_msport_matches",
                return_value=[{"bookie": "MSport"}],
            ),
            patch(
                "run_once.fetch_betking_matches",
                return_value=betking_matches,
            ) as fetch_betking,
            patch("run_once.count_matched_pairs", return_value=2) as count_pairs,
            patch("run_once.find_arbitrage", return_value=[]) as find_arbitrage,
            patch("run_once.logger.info") as logger_info,
            patch("run_once.send_alert"),
            patch("run_once.send_message"),
        ):
            result = main()

        self.assertEqual(result, 0)
        fetch_betking.assert_called_once_with()
        self.assertEqual(
            find_arbitrage.call_args.kwargs["betking_matches"],
            betking_matches,
        )
        count_pairs.assert_called_once()
        find_arbitrage.assert_called_once()
        self.assertIn(
            (
                "Scan summary: betking_rows=%d betpawa_rows=%d bet9ja_rows=%d "
                "msport_rows=%d polymarket_rows=%d matched_pairs=%d arbs_found=%d",
                1,
                0,
                0,
                1,
                0,
                2,
                0,
            ),
            [call.args for call in logger_info.call_args_list],
        )
        self.assertEqual(
            find_arbitrage.call_args.kwargs["max_arbitrage_profit_pct"],
            15.0,
        )
        self.assertEqual(
            find_arbitrage.call_args.kwargs["min_minutes_to_kickoff"],
            15,
        )
        self.assertEqual(
            find_arbitrage.call_args.kwargs["msport_matches"],
            [{"bookie": "MSport"}],
        )

    def test_empty_scan_message_is_controlled_by_notify_empty(self) -> None:
        for notify_empty in (False, True):
            with self.subTest(notify_empty=notify_empty):
                with (
                    patch("run_once.NOTIFY_EMPTY", notify_empty),
                    patch("run_once.BETKING_FEED_URL", ""),
                    patch("run_once.fetch_betpawa_matches", return_value=[]),
                    patch("run_once.fetch_bet9ja_matches", return_value=[]),
                    patch("run_once.fetch_msport_matches", return_value=[]),
                    patch("run_once.fetch_betking_matches") as fetch_betking,
                    patch("run_once.find_arbitrage", return_value=[]),
                    patch("run_once.send_alert") as send_alert,
                    patch("run_once.send_message") as send_message,
                ):
                    result = main()

                self.assertEqual(result, 0)
                fetch_betking.assert_not_called()
                send_alert.assert_not_called()
                self.assertEqual(send_message.call_count, int(notify_empty))
                if notify_empty:
                    message = send_message.call_args.args[0]
                    self.assertIn(
                        "SCAN HEARTBEAT — NO ARBITRAGE FOUND",
                        message,
                    )
                    self.assertIn("Opportunities found: 0", message)
                    self.assertIn("Betpawa: 0", message)
                    self.assertIn("MSport: 0", message)
                    self.assertIn("Polymarket: 0", message)
                    self.assertIn("Matched fixture pairs: 0", message)

    def test_logs_why_empty_scan_did_not_send_telegram(self) -> None:
        with (
            patch("run_once.NOTIFY_EMPTY", False),
            patch("run_once.BET9JA_FEED_URL", ""),
            patch("run_once.BETKING_FEED_URL", ""),
            patch("run_once.fetch_betpawa_matches", return_value=[]),
            patch("run_once.fetch_msport_matches", return_value=[]),
            patch("run_once.find_arbitrage", return_value=[]),
            patch(
                "run_once.validate_telegram_credentials",
                side_effect=RuntimeError("TELEGRAM_BOT_TOKEN is missing"),
            ),
            patch("run_once.logger.warning") as logger_warning,
            patch("run_once.logger.info") as logger_info,
            patch("run_once.send_message") as send_message,
        ):
            result = main()

        self.assertEqual(result, 0)
        self.assertEqual(
            logger_warning.call_args.args[0],
            "Telegram is not configured: %s",
        )
        self.assertEqual(
            str(logger_warning.call_args.args[1]),
            "TELEGRAM_BOT_TOKEN is missing",
        )
        self.assertIn(
            (
                "Telegram message skipped: no arbitrage opportunities and "
                "NOTIFY_EMPTY is false",
            ),
            [call.args for call in logger_info.call_args_list],
        )
        send_message.assert_not_called()

    def test_logs_successful_alert_delivery(self) -> None:
        opportunity = {"home": "Home FC", "away": "Away FC"}
        with (
            patch("run_once.BET9JA_FEED_URL", ""),
            patch("run_once.BETKING_FEED_URL", ""),
            patch("run_once.fetch_betpawa_matches", return_value=[]),
            patch("run_once.fetch_msport_matches", return_value=[]),
            patch("run_once.find_arbitrage", return_value=[opportunity]),
            patch("run_once.send_alert") as send_alert,
            patch("run_once.logger.info") as logger_info,
        ):
            result = main()

        self.assertEqual(result, 0)
        send_alert.assert_called_once_with(opportunity)
        self.assertIn(
            ("Telegram alert delivered for %s vs %s", "Home FC", "Away FC"),
            [call.args for call in logger_info.call_args_list],
        )

    def test_msport_fetch_failure_does_not_abort_scan(self) -> None:
        with (
            patch("run_once.BET9JA_FEED_URL", ""),
            patch("run_once.BETKING_FEED_URL", ""),
            patch("run_once.fetch_betpawa_matches", return_value=[]),
            patch("run_once.fetch_msport_matches", side_effect=RuntimeError("feed down")),
            patch("run_once.find_arbitrage", return_value=[]) as find_arbitrage,
            patch("run_once.send_message"),
            patch("run_once.logger.exception"),
        ):
            result = main()

        self.assertEqual(result, 0)
        self.assertEqual(find_arbitrage.call_args.kwargs["msport_matches"], [])

    def test_polymarket_fetch_failure_does_not_abort_scan(self) -> None:
        with (
            patch(
                "run_once.POLYMARKET_FEED_URL",
                "https://gamma-api.polymarket.com/events",
            ),
            patch("run_once.BET9JA_FEED_URL", ""),
            patch("run_once.BETKING_FEED_URL", ""),
            patch("run_once.fetch_betpawa_matches", return_value=[]),
            patch("run_once.fetch_msport_matches", return_value=[]),
            patch(
                "run_once.fetch_polymarket_matches",
                side_effect=RuntimeError("feed down"),
            ),
            patch("run_once.find_arbitrage", return_value=[]) as find_arbitrage,
            patch("run_once.send_message"),
            patch("run_once.logger.exception"),
        ):
            result = main()

        self.assertEqual(result, 0)
        self.assertEqual(
            find_arbitrage.call_args.kwargs["polymarket_matches"],
            [],
        )


if __name__ == "__main__":
    unittest.main()
