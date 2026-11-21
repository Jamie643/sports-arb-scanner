import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

from scrapers.bet9ja import (
    fetch_matches as fetch_bet9ja_matches,
    parse_payload as parse_bet9ja_payload,
)
from scrapers.betking import (
    fetch_matches as fetch_betking_matches,
    parse_payload as parse_betking_payload,
)
from scrapers.betpawa import (
    fetch_matches as fetch_betpawa_matches,
    parse_payload as parse_betpawa_payload,
)


class ScraperAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.normalized_match = {
            "bookie": "untrusted feed value",
            "home": "Lagos United",
            "away": "Abuja FC",
            "kickoff": "2026-12-01T16:00:00Z",
            "market": "Over/Under 2.5 Goals",
            "outcome_a": "2.10",
            "outcome_b": 1.95,
            "url": "https://sportsbook.example/event",
        }

    def test_betpawa_normalized_payload_fallback(self) -> None:
        parsed = parse_betpawa_payload({"matches": [self.normalized_match]})

        self.assertEqual(
            parsed,
            [
                {
                    "bookie": "Betpawa",
                    "home": "Lagos United",
                    "away": "Abuja FC",
                    "kickoff": "2026-12-01T16:00:00Z",
                    "market": "Over/Under 2.5 Goals",
                    "outcome_a": 2.10,
                    "outcome_b": 1.95,
                    "url": "https://sportsbook.example/event",
                    "league": "",
                }
            ],
        )

    def test_bet9ja_native_parser_maps_to_normalized_schema(self) -> None:
        native_payload = {"eventData": {"events": [{"event_id": "event-1"}]}}

        def native_parser(payload: dict[str, Any]) -> list[dict[str, Any]]:
            event = payload["eventData"]["events"][0]
            return [{**self.normalized_match, "home": event["event_id"]}]

        parsed = parse_bet9ja_payload(native_payload, native_parser=native_parser)

        self.assertEqual(parsed[0]["bookie"], "Bet9ja")
        self.assertEqual(parsed[0]["home"], "event-1")

    def test_unknown_native_payload_fails_explicitly(self) -> None:
        with self.assertRaisesRegex(ValueError, "no native parser was provided"):
            parse_betpawa_payload({"events": []})

    def test_betpawa_fetches_normalized_json_from_file_url(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.json"
            path.write_text(
                json.dumps({"matches": [self.normalized_match]}),
                encoding="utf-8",
            )
            with patch("scrapers.betpawa.BETPAWA_FEED_URL", path.as_uri()):
                matches = fetch_betpawa_matches()

        self.assertEqual(matches[0]["bookie"], "Betpawa")
        self.assertEqual(matches[0]["home"], "Lagos United")
        self.assertEqual(matches[0]["outcome_a"], 2.10)

    def test_betpawa_parses_native_event_markets_and_odds(self) -> None:
        payload = {
            "responses": [
                {
                    "requestOrder": 0,
                    "responses": [
                        {
                            "id": "event-42",
                            "name": "Lagos United - Abuja FC",
                            "competition": {"name": "Nigeria - Premier League"},
                            "participants": [
                                {"id": "away", "name": "Abuja FC", "position": 2},
                                {"id": "home", "name": "Lagos United", "position": 1},
                            ],
                            "startTime": "2026-12-01T16:00:00Z",
                            "markets": [
                                {
                                    "marketType": {
                                        "id": "5000",
                                        "name": "Total Score Over/Under - FT",
                                    },
                                    "row": [
                                        {
                                            "specifier": {"total": "1.5"},
                                            "prices": [
                                                {"name": "Over", "odds": 1.3},
                                                {"name": "Under", "odds": 3.1},
                                            ]
                                        }
                                    ],
                                },
                                {
                                    "marketType": {
                                        "id": "5000",
                                        "name": "Total Score Over/Under - FT",
                                    },
                                    "row": [
                                        {
                                            "specifier": {"total": "2.5"},
                                            "prices": [
                                                {"name": "Over", "odds": 2.0},
                                                {"name": "Under", "odds": 1.9},
                                            ]
                                        }
                                    ],
                                },
                                {
                                    "marketType": {
                                        "id": "3795",
                                        "name": "Both Teams To Score - FT",
                                    },
                                    "row": [
                                        {
                                            "prices": [
                                                {"name": "Yes", "odds": 1.8},
                                                {"name": "No", "odds": 2.1},
                                            ]
                                        }
                                    ],
                                },
                                {
                                    "marketType": {"id": "1x2", "name": "1X2 - FT"},
                                    "row": [
                                        {
                                            "prices": [
                                                {"name": "1", "odds": 2.0},
                                                {"name": "X", "odds": 3.0},
                                                {"name": "2", "odds": 4.0},
                                            ]
                                        }
                                    ],
                                },
                            ],
                        }
                    ],
                }
            ],
            "outrights": [],
        }

        parsed = parse_betpawa_payload(payload)

        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0]["bookie"], "Betpawa")
        self.assertEqual(parsed[0]["home"], "Lagos United")
        self.assertEqual(parsed[0]["away"], "Abuja FC")
        self.assertEqual(parsed[0]["kickoff"], "2026-12-01T16:00:00Z")
        self.assertEqual(parsed[0]["market"], "Over/Under 2.5 Goals")
        self.assertEqual(parsed[0]["league"], "Nigeria - Premier League")
        self.assertEqual((parsed[0]["outcome_a"], parsed[0]["outcome_b"]), (2.0, 1.9))
        self.assertEqual(parsed[0]["url"], "https://www.betpawa.ng/")
        self.assertEqual(parsed[1]["market"], "Both Teams to Score")
        self.assertEqual((parsed[1]["outcome_a"], parsed[1]["outcome_b"]), (1.8, 2.1))

    def test_betpawa_maps_native_json_loaded_from_file_url(self) -> None:
        payload = {
            "responses": [
                {
                    "requestOrder": 0,
                    "responses": [
                        {
                            "name": "Lagos United - Abuja FC",
                            "participants": [
                                {"name": "Lagos United", "position": 1},
                                {"name": "Abuja FC", "position": 2},
                            ],
                            "startTime": "2026-12-01T16:00:00Z",
                            "markets": [
                                {
                                    "marketType": {
                                        "name": "Total Goals Over/Under 2.5"
                                    },
                                    "row": [
                                        {
                                            "prices": [
                                                {"name": "Over", "odds": 2.0},
                                                {"name": "Under", "odds": 1.9},
                                            ]
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ]
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with patch("scrapers.betpawa.BETPAWA_FEED_URL", path.as_uri()):
                matches = fetch_betpawa_matches()

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["bookie"], "Betpawa")
        self.assertEqual(matches[0]["market"], "Over/Under 2.5 Goals")
        self.assertEqual(matches[0]["outcome_a"], 2.0)

    def test_betpawa_live_feed_queries_configured_markets(self) -> None:
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"responses": [], "outrights": []}
        feed_url = (
            "https://www.betpawa.ng/api/sportsbook/v4/events/lists/by-queries"
        )
        with (
            patch("scrapers.betpawa.BETPAWA_FEED_URL", feed_url),
            patch(
                "scrapers.betpawa.curl_requests.get",
                return_value=response,
            ) as mocked_get,
        ):
            matches = fetch_betpawa_matches()

        self.assertEqual(matches, [])
        args, kwargs = mocked_get.call_args
        self.assertEqual(args[0], feed_url)
        self.assertEqual(kwargs["headers"]["X-Pawa-Brand"], "betpawa-nigeria")
        query = json.loads(kwargs["params"]["q"])
        request = query["queries"][0]
        self.assertEqual(request["query"]["categories"], ["2"])
        self.assertEqual(request["query"]["marketTypes"], ["5000", "3795"])
        self.assertEqual(request["view"]["marketTypes"], ["5000", "3795"])
        self.assertEqual(request["take"], 40)

    def test_betpawa_live_fetch_paginates_and_deduplicates_by_event_id(self) -> None:
        def event(event_id: str | None, home: str) -> dict[str, Any]:
            return {
                **({"id": event_id} if event_id is not None else {}),
                "name": f"{home} - Abuja FC",
                "participants": [
                    {"name": home, "position": 1},
                    {"name": "Abuja FC", "position": 2},
                ],
                "startTime": "2026-12-01T16:00:00Z",
                "markets": [
                    {
                        "marketType": {
                            "id": "3795",
                            "name": "Both Teams To Score - FT",
                        },
                        "row": [
                            {
                                "prices": [
                                    {"name": "Yes", "odds": 1.8},
                                    {"name": "No", "odds": 2.1},
                                ]
                            }
                        ],
                    }
                ],
            }

        page_one = Mock()
        page_one.raise_for_status.return_value = None
        page_one.json.return_value = {
            "responses": [
                {
                    "responses": [
                        event("event-1", "Lagos United"),
                        event(None, "Enugu Rangers"),
                    ]
                }
            ]
        }
        page_two = Mock()
        page_two.raise_for_status.return_value = None
        page_two.json.return_value = {
            "responses": [
                {
                    "responses": [
                        event(None, "Enugu Rangers"),
                        event("event-3", "Kano Pillars"),
                    ]
                }
            ]
        }
        page_three = Mock()
        page_three.raise_for_status.return_value = None
        page_three.json.return_value = {
            "responses": [{"responses": [event("event-3", "Kano Pillars")]}]
        }
        feed_url = (
            "https://www.betpawa.ng/api/sportsbook/v4/events/lists/by-queries"
        )
        with (
            patch("scrapers.betpawa.BETPAWA_FEED_URL", feed_url),
            patch("scrapers.betpawa._BETPAWA_QUERY_TAKE", 2),
            patch("scrapers.betpawa._BETPAWA_MAX_QUERY_PAGES", 5),
            patch(
                "scrapers.betpawa.curl_requests.get",
                side_effect=[page_one, page_two, page_three],
            ) as mocked_get,
        ):
            matches = fetch_betpawa_matches()

        self.assertEqual(len(matches), 3)
        self.assertEqual(
            {match["home"] for match in matches},
            {"Lagos United", "Enugu Rangers", "Kano Pillars"},
        )
        self.assertEqual(mocked_get.call_count, 3)
        skips = [
            json.loads(call.kwargs["params"]["q"])["queries"][0]["skip"]
            for call in mocked_get.call_args_list
        ]
        self.assertEqual(skips, [0, 2, 4])

    def test_bet9ja_maps_native_json_loaded_from_file_url(self) -> None:
        native_payload = {"eventData": {"events": [{"event_id": "event-1"}]}}

        def native_parser(payload: dict[str, Any]) -> list[dict[str, Any]]:
            event = payload["eventData"]["events"][0]
            return [{**self.normalized_match, "home": event["event_id"]}]

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.json"
            path.write_text(json.dumps(native_payload), encoding="utf-8")
            with patch("scrapers.bet9ja.BET9JA_FEED_URL", path.as_uri()):
                matches = fetch_bet9ja_matches(native_parser=native_parser)

        self.assertEqual(matches[0]["bookie"], "Bet9ja")
        self.assertEqual(matches[0]["home"], "event-1")

    def test_betking_maps_goal_markets_from_native_payload(self) -> None:
        payload = {
            "AreaMatches": [
                {
                    "AreaName": "Nigeria - Premier League",
                    "Items": [
                        {
                            "ItemName": "Lagos United - Abuja FC",
                            "ItemDate": "2026-12-01T16:00:00+01:00",
                            "ItemID": 123,
                            "Teams": [
                                {"Name": "Abuja FC", "ItemOrder": 2},
                                {"Name": "Lagos United", "ItemOrder": 1},
                            ],
                            "OddsCollection": [
                                {
                                    "OddsType": {"OddsTypeName": "Total Goals 3.5"},
                                    "SpecialBetValue": 3.5,
                                    "MatchOdds": [
                                        {
                                            "OddAttribute": {"OddName": "Over"},
                                            "Outcome": {"OddOutcome": 2.4},
                                        },
                                        {
                                            "OddAttribute": {"OddName": "Under"},
                                            "Outcome": {"OddOutcome": 1.6},
                                        },
                                    ],
                                },
                                {
                                    "OddsType": {"OddsTypeName": "Total Goals 2.5"},
                                    "SpecialBetValue": 2.5,
                                    "MatchOdds": [
                                        {
                                            "OddAttribute": {
                                                "OddName": "Over",
                                                "SpecialValue": 2.5,
                                            },
                                            "Outcome": {"OddOutcome": 1.9},
                                        },
                                        {
                                            "OddAttribute": {
                                                "OddName": "Under",
                                                "SpecialValue": 2.5,
                                            },
                                            "Outcome": {"OddOutcome": 2.0},
                                        },
                                    ],
                                },
                                {
                                    "OddsType": {
                                        "OddsTypeName": "Both Teams to Score"
                                    },
                                    "MatchOdds": [
                                        {
                                            "OddAttribute": {"OddName": "Yes"},
                                            "Outcome": {"OddOutcome": 1.8},
                                        },
                                        {
                                            "OddAttribute": {"OddName": "No"},
                                            "Outcome": {"OddOutcome": 2.1},
                                        },
                                    ],
                                },
                            ],
                        }
                    ]
                }
            ]
        }

        parsed = parse_betking_payload(payload)

        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0]["bookie"], "BetKing")
        self.assertEqual(parsed[0]["home"], "Lagos United")
        self.assertEqual(parsed[0]["away"], "Abuja FC")
        self.assertEqual(parsed[0]["market"], "Over/Under 2.5 Goals")
        self.assertEqual(parsed[0]["league"], "Nigeria - Premier League")
        self.assertEqual((parsed[0]["outcome_a"], parsed[0]["outcome_b"]), (1.9, 2.0))
        self.assertEqual(parsed[0]["url"], "https://www.betking.com/")
        self.assertEqual(parsed[1]["market"], "Both Teams to Score")
        self.assertEqual((parsed[1]["outcome_a"], parsed[1]["outcome_b"]), (1.8, 2.1))

    def test_betking_maps_gg_ng_to_btts(self) -> None:
        payload = {
            "AreaMatches": [
                {
                    "Items": [
                        {
                            "ItemName": "Lagos United - Abuja FC",
                            "ItemDate": "2026-12-01T16:00:00Z",
                            "Teams": [
                                {"Name": "Lagos United", "ItemOrder": 1},
                                {"Name": "Abuja FC", "ItemOrder": 2},
                            ],
                            "OddsCollection": [
                                {
                                    "OddsType": {"OddsTypeName": "GG/NG"},
                                    "MatchOdds": [
                                        {
                                            "OddAttribute": {"OddName": "GG"},
                                            "Outcome": {"OddOutcome": 1.51},
                                        },
                                        {
                                            "OddAttribute": {"OddName": "NG"},
                                            "Outcome": {"OddOutcome": 2.48},
                                        },
                                    ],
                                }
                            ],
                        }
                    ]
                }
            ]
        }

        parsed = parse_betking_payload(payload)

        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["market"], "Both Teams to Score")
        self.assertEqual((parsed[0]["outcome_a"], parsed[0]["outcome_b"]), (1.51, 2.48))

    def test_betking_supports_normalized_file_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.json"
            path.write_text(
                json.dumps({"matches": [self.normalized_match]}),
                encoding="utf-8",
            )
            with patch("scrapers.betking.BETKING_FEED_URL", path.as_uri()):
                matches = fetch_betking_matches()

        self.assertEqual(matches[0]["bookie"], "BetKing")
        self.assertEqual(matches[0]["home"], "Lagos United")

    def test_betking_maps_native_payload_loaded_from_file(self) -> None:
        payload = {
            "AreaMatches": [
                {
                    "Items": [
                        {
                            "ItemName": "Lagos United - Abuja FC",
                            "ItemDate": "2026-12-01T16:00:00Z",
                            "Teams": [
                                {"Name": "Lagos United", "ItemOrder": 1},
                                {"Name": "Abuja FC", "ItemOrder": 2},
                            ],
                            "OddsCollection": [
                                {
                                    "OddsType": {"OddsTypeName": "Total Goals 2.5"},
                                    "SpecialBetValue": 2.5,
                                    "MatchOdds": [
                                        {
                                            "OddAttribute": {"OddName": "Over"},
                                            "Outcome": {"OddOutcome": 2.0},
                                        },
                                        {
                                            "OddAttribute": {"OddName": "Under"},
                                            "Outcome": {"OddOutcome": 1.9},
                                        },
                                    ],
                                }
                            ],
                        }
                    ]
                }
            ]
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with patch("scrapers.betking.BETKING_FEED_URL", path.as_uri()):
                matches = fetch_betking_matches()

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["bookie"], "BetKing")
        self.assertEqual(matches[0]["market"], "Over/Under 2.5 Goals")

    def test_betking_date_wide_feed_fetches_two_utc_dates_and_deduplicates(self) -> None:
        shared_match = {
            "AreaMatches": [
                {
                    "Items": [
                        {
                            "ItemName": "Lagos United - Abuja FC",
                            "ItemDate": "2026-12-01T16:00:00Z",
                            "Teams": [
                                {"Name": "Lagos United", "ItemOrder": 1},
                                {"Name": "Abuja FC", "ItemOrder": 2},
                            ],
                            "OddsCollection": [
                                {
                                    "OddsType": {"OddsTypeName": "Total Goals 2.5"},
                                    "SpecialBetValue": 2.5,
                                    "MatchOdds": [
                                        {
                                            "OddAttribute": {"OddName": "Over"},
                                            "Outcome": {"OddOutcome": 2.0},
                                        },
                                        {
                                            "OddAttribute": {"OddName": "Under"},
                                            "Outcome": {"OddOutcome": 1.9},
                                        },
                                    ],
                                }
                            ],
                        }
                    ]
                }
            ]
        }
        first_response = Mock()
        first_response.raise_for_status.return_value = None
        first_response.json.return_value = shared_match
        second_response = Mock()
        second_response.raise_for_status.return_value = None
        second_response.json.return_value = shared_match

        template = (
            "https://sportsapicdn-desktop.betking.com/api/feeds/"
            "prematch/GetEvents/en/{date}/0/0/1"
        )
        with (
            patch("scrapers.betking.BETKING_FEED_URL", template),
            patch(
                "scrapers.betking._utc_dates",
                return_value=("2026-12-01", "2026-12-02"),
            ),
            patch(
                "scrapers.betking.curl_requests.get",
                side_effect=[first_response, second_response],
            ) as mocked_get,
        ):
            matches = fetch_betking_matches()

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["home"], "Lagos United")
        self.assertEqual(matches[0]["away"], "Abuja FC")
        self.assertEqual(mocked_get.call_count, 2)
        requested_urls = [call.args[0] for call in mocked_get.call_args_list]
        self.assertIn("2026-12-01", requested_urls[0])
        self.assertIn("2026-12-02", requested_urls[1])

    def test_betking_single_date_url_expands_both_dates(self) -> None:
        feed_url = (
            "https://sportsapicdn-desktop.betking.com/api/feeds/"
            "prematch/GetEvents/en/2026-12-01/0/0/1"
        )
        with patch(
            "scrapers.betking._utc_dates",
            return_value=("2026-12-01", "2026-12-02"),
        ):
            response_one = Mock()
            response_one.raise_for_status.return_value = None
            response_one.json.return_value = {"AreaMatches": []}
            response_two = Mock()
            response_two.raise_for_status.return_value = None
            response_two.json.return_value = {"AreaMatches": []}
            with (
                patch("scrapers.betking.BETKING_FEED_URL", feed_url),
                patch(
                    "scrapers.betking.curl_requests.get",
                    side_effect=[response_one, response_two],
                ) as mocked_get,
            ):
                matches = fetch_betking_matches()

        self.assertEqual(matches, [])
        self.assertEqual(mocked_get.call_count, 2)


if __name__ == "__main__":
    unittest.main()
