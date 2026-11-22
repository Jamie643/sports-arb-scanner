import unittest
from unittest.mock import Mock, patch

import requests

from services.telegram import (
    format_empty_scan_notification,
    send_message,
    validate_telegram_credentials,
)


class TelegramTests(unittest.TestCase):
    def test_empty_scan_message_is_a_distinct_heartbeat_with_counts(self) -> None:
        message = format_empty_scan_notification(
            lookahead_hours=24,
            betking_rows=12,
            betpawa_rows=34,
            bet9ja_rows=5,
            matched_pairs=3,
            msport_rows=8,
            polymarket_rows=9,
        )

        self.assertIn("SCAN HEARTBEAT — NO ARBITRAGE FOUND", message)
        self.assertIn("Opportunities found: 0", message)
        self.assertIn("BetKing: 12", message)
        self.assertIn("Betpawa: 34", message)
        self.assertIn("Bet9ja: 5", message)
        self.assertIn("MSport: 8", message)
        self.assertIn("Polymarket: 9", message)
        self.assertIn("Matched fixture pairs: 3", message)
        self.assertIn("Arbitrage opportunities: 0", message)
        self.assertNotIn("ARBITRAGE OPPORTUNITY", message)

    def test_rejects_missing_credentials_without_sending(self) -> None:
        with (
            patch("services.telegram.TELEGRAM_BOT_TOKEN", "  "),
            patch("services.telegram.TELEGRAM_CHAT_ID", "123"),
            patch("services.telegram.requests.post") as post,
        ):
            with self.assertRaisesRegex(RuntimeError, "TELEGRAM_BOT_TOKEN is missing"):
                send_message("test")

        post.assert_not_called()

    def test_rejects_malformed_token_without_sending(self) -> None:
        with (
            patch("services.telegram.TELEGRAM_BOT_TOKEN", "not-a-token"),
            patch("services.telegram.TELEGRAM_CHAT_ID", "123"),
            patch("services.telegram.requests.post") as post,
        ):
            with self.assertRaisesRegex(RuntimeError, "invalid format"):
                validate_telegram_credentials()

        post.assert_not_called()

    def test_sends_to_telegram_and_requires_success_response(self) -> None:
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"ok": True}
        token = "123456:fake_token"
        with (
            patch("services.telegram.TELEGRAM_BOT_TOKEN", token),
            patch("services.telegram.TELEGRAM_CHAT_ID", "987654"),
            patch("services.telegram.requests.post", return_value=response) as post,
        ):
            send_message("test alert")

        post.assert_called_once_with(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": "987654", "text": "test alert"},
            timeout=10,
        )

    def test_rejects_telegram_api_ok_false_response(self) -> None:
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"ok": False}
        with (
            patch("services.telegram.TELEGRAM_BOT_TOKEN", "123456:fake_token"),
            patch("services.telegram.TELEGRAM_CHAT_ID", "987654"),
            patch("services.telegram.requests.post", return_value=response),
        ):
            with self.assertRaisesRegex(RuntimeError, "rejected the message"):
                send_message("test alert")

    def test_http_errors_are_reported_without_echoing_token(self) -> None:
        token = "123456:fake_token"
        response = Mock()
        response.status_code = 401
        http_error = requests.HTTPError(
            f"request URL included {token}",
            response=response,
        )
        with (
            patch("services.telegram.TELEGRAM_BOT_TOKEN", token),
            patch("services.telegram.TELEGRAM_CHAT_ID", "987654"),
            patch(
                "services.telegram.requests.post",
                side_effect=http_error,
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "HTTP 401") as raised:
                send_message("test alert")

        self.assertNotIn(token, str(raised.exception))


if __name__ == "__main__":
    unittest.main()
