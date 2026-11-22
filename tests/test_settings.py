import os
import unittest
from unittest.mock import patch

from settings import (
    DEFAULT_BETKING_FEED_URL,
    DEFAULT_BETPAWA_FEED_URL,
    DEFAULT_MSPORT_FEED_URL,
    DEFAULT_POLYMARKET_FEED_URL,
    _read_feed_url,
    _read_notify_empty,
)


class FeedUrlSettingsTests(unittest.TestCase):
    def test_blank_or_whitespace_feed_urls_use_defaults(self) -> None:
        for value in ("", "   \t"):
            with self.subTest(value=repr(value)):
                with patch.dict(os.environ, {"TEST_FEED_URL": value}):
                    self.assertEqual(
                        _read_feed_url("TEST_FEED_URL", DEFAULT_BETKING_FEED_URL),
                        DEFAULT_BETKING_FEED_URL,
                    )

        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                _read_feed_url("TEST_FEED_URL", DEFAULT_BETPAWA_FEED_URL),
                DEFAULT_BETPAWA_FEED_URL,
            )

    def test_valid_feed_url_overrides_are_trimmed(self) -> None:
        with patch.dict(
            os.environ,
            {"TEST_FEED_URL": "  https://feed.example/events  "},
        ):
            self.assertEqual(
                _read_feed_url("TEST_FEED_URL", DEFAULT_BETKING_FEED_URL),
                "https://feed.example/events",
            )

    def test_invalid_nonempty_feed_url_fails_with_setting_name(self) -> None:
        for value in ("ftp://feed.example/events", "https://["):
            with self.subTest(value=value):
                with patch.dict(os.environ, {"TEST_FEED_URL": value}):
                    with self.assertRaisesRegex(ValueError, "TEST_FEED_URL"):
                        _read_feed_url("TEST_FEED_URL", DEFAULT_BETKING_FEED_URL)

    def test_defaults_are_provider_endpoints(self) -> None:
        self.assertEqual(
            DEFAULT_BETKING_FEED_URL,
            "https://sportsapicdn-desktop.betking.com/api/feeds/prematch/"
            "GetEvents/en/{date}/0/0/1",
        )
        self.assertEqual(
            DEFAULT_BETPAWA_FEED_URL,
            "https://www.betpawa.ng/api/sportsbook/v4/events/lists/by-queries",
        )
        self.assertEqual(
            DEFAULT_MSPORT_FEED_URL,
            "https://www.msport.com/api/ng/facts-center/query/frontend/"
            "all-matches/next-7-days",
        )
        self.assertEqual(
            DEFAULT_POLYMARKET_FEED_URL,
            "https://gamma-api.polymarket.com/events",
        )


class NotifyEmptySettingsTests(unittest.TestCase):
    def test_defaults_to_true_when_unset_or_blank(self) -> None:
        for environment in ({}, {"NOTIFY_EMPTY": "  "}):
            with self.subTest(environment=environment):
                with patch.dict(os.environ, environment, clear=True):
                    self.assertTrue(_read_notify_empty())

    def test_explicit_false_disables_empty_notifications(self) -> None:
        with patch.dict(os.environ, {"NOTIFY_EMPTY": " false "}, clear=True):
            self.assertFalse(_read_notify_empty())


if __name__ == "__main__":
    unittest.main()
