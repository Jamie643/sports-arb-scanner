import unittest
from unittest.mock import patch

from run_once import main


class RunOnceTests(unittest.TestCase):
    def test_skips_bet9ja_cleanly_when_feed_is_unset(self) -> None:
        with (
            patch("run_once.BET9JA_FEED_URL", ""),
            patch("run_once.BETKING_FEED_URL", ""),
            patch("run_once.fetch_betpawa_matches", return_value=[]),
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
                "Scan summary: betking_rows=%d betpawa_rows=%d matched_pairs=%d "
                "arbs_found=%d",
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

    def test_empty_scan_message_is_controlled_by_notify_empty(self) -> None:
        for notify_empty in (False, True):
            with self.subTest(notify_empty=notify_empty):
                with (
                    patch("run_once.NOTIFY_EMPTY", notify_empty),
                    patch("run_once.BETKING_FEED_URL", ""),
                    patch("run_once.fetch_betpawa_matches", return_value=[]),
                    patch("run_once.fetch_bet9ja_matches", return_value=[]),
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
                    self.assertIn(
                        "no arbitrage opportunities",
                        send_message.call_args.args[0],
                    )


if __name__ == "__main__":
    unittest.main()
