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
from scrapers.msport import (
    fetch_matches as fetch_msport_matches,
    parse_payload as parse_msport_payload,
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
                    "sport": "Football",
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
                                        "id": "5000",
                                        "name": "Total Score Over/Under - FT",
                                    },
                                    "row": [
                                        {
                                            "specifier": {"total": "3.5"},
                                            "prices": [
                                                {"name": "Over", "odds": 2.5},
                                                {"name": "Under", "odds": 1.5},
                                            ],
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
                                    "marketType": {
                                        "id": "4703",
                                        "name": "Draw No Bet - FT",
                                    },
                                    "row": [
                                        {
                                            "prices": [
                                                {"name": "1", "odds": 1.7},
                                                {"name": "2", "odds": 2.2},
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

        self.assertEqual(len(parsed), 5)
        self.assertEqual(parsed[0]["bookie"], "Betpawa")
        self.assertEqual(parsed[0]["home"], "Lagos United")
        self.assertEqual(parsed[0]["away"], "Abuja FC")
        self.assertEqual(parsed[0]["kickoff"], "2026-12-01T16:00:00Z")
        self.assertEqual(parsed[0]["market"], "Over/Under 1.5 Goals")
        self.assertEqual(parsed[0]["league"], "Nigeria - Premier League")
        self.assertEqual((parsed[0]["outcome_a"], parsed[0]["outcome_b"]), (1.3, 3.1))
        self.assertEqual(parsed[0]["url"], "https://www.betpawa.ng/")
        self.assertEqual(parsed[1]["market"], "Over/Under 2.5 Goals")
        self.assertEqual((parsed[1]["outcome_a"], parsed[1]["outcome_b"]), (2.0, 1.9))
        self.assertEqual(parsed[2]["market"], "Over/Under 3.5 Goals")
        self.assertEqual((parsed[2]["outcome_a"], parsed[2]["outcome_b"]), (2.5, 1.5))
        self.assertEqual(parsed[3]["market"], "Both Teams to Score")
        self.assertEqual((parsed[3]["outcome_a"], parsed[3]["outcome_b"]), (1.8, 2.1))
        self.assertEqual(parsed[4]["market"], "Draw No Bet")
        self.assertEqual((parsed[4]["outcome_a"], parsed[4]["outcome_b"]), (1.7, 2.2))

    def test_betpawa_parses_basketball_and_tennis_markets(self) -> None:
        payload = {
            "responses": [
                {
                    "responses": [
                        {
                            "category": {"id": "3", "name": "Basketball"},
                            "name": "Home Hoops - Away Hoops",
                            "participants": [
                                {"name": "Home Hoops", "position": 1},
                                {"name": "Away Hoops", "position": 2},
                            ],
                            "startTime": "2026-12-01T16:00:00Z",
                            "markets": [
                                {
                                    "marketType": {
                                        "id": "4791",
                                        "name": "Moneyline - FT incl OT",
                                    },
                                    "row": [
                                        {
                                            "prices": [
                                                {"name": "1", "odds": 1.8},
                                                {"name": "2", "odds": 2.1},
                                            ]
                                        }
                                    ],
                                },
                                {
                                    "marketType": {
                                        "id": "5009",
                                        "name": "Total Score Over/Under - FT incl OT",
                                    },
                                    "row": [
                                        {
                                            "specifier": {"total": "161.5"},
                                            "prices": [
                                                {"name": "Over", "odds": 1.9},
                                                {"name": "Under", "odds": 1.9},
                                            ],
                                        }
                                    ],
                                },
                                {
                                    "marketType": {
                                        "id": "4973",
                                        "name": "Total Score Over/Under - 1Q",
                                    },
                                    "row": [
                                        {
                                            "specifier": {"total": "35.5"},
                                            "prices": [
                                                {"name": "Over", "odds": 1.9},
                                                {"name": "Under", "odds": 1.9},
                                            ],
                                        }
                                    ],
                                },
                            ],
                        },
                        {
                            "category": {"id": "452", "name": "Tennis"},
                            "name": "Player One - Player Two",
                            "participants": [
                                {"name": "Player One", "position": 1},
                                {"name": "Player Two", "position": 2},
                            ],
                            "startTime": "2026-12-01T17:00:00Z",
                            "markets": [
                                {
                                    "marketType": {
                                        "id": "2043818",
                                        "name": "Moneyline - FT",
                                    },
                                    "row": [
                                        {
                                            "prices": [
                                                {"name": "1", "odds": 1.7},
                                                {"name": "2", "odds": 2.2},
                                            ]
                                        }
                                    ],
                                }
                            ],
                        },
                        {
                            "category": {"id": "101", "name": "eFootball"},
                            "name": "Virtual One - Virtual Two",
                            "participants": [
                                {"name": "Virtual One", "position": 1},
                                {"name": "Virtual Two", "position": 2},
                            ],
                            "startTime": "2026-12-01T18:00:00Z",
                            "markets": [
                                {
                                    "marketType": {
                                        "id": "3743",
                                        "name": "1X2 - FT",
                                    },
                                    "row": [
                                        {
                                            "prices": [
                                                {"name": "1", "odds": 2.0},
                                                {"name": "X", "odds": 3.0},
                                                {"name": "2", "odds": 4.0},
                                            ]
                                        }
                                    ],
                                }
                            ],
                        },
                    ]
                }
            ]
        }

        parsed = parse_betpawa_payload(payload)

        self.assertEqual(
            [(row["sport"], row["market"]) for row in parsed],
            [
                ("Basketball", "Match Winner"),
                ("Basketball", "Over/Under 161.5 Points"),
                ("Tennis", "Match Winner"),
            ],
        )
        self.assertEqual(
            [(row["outcome_a"], row["outcome_b"]) for row in parsed],
            [(1.8, 2.1), (1.9, 1.9), (1.7, 2.2)],
        )

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
        requests = query["queries"]
        self.assertEqual(
            [request["query"]["categories"] for request in requests],
            [["2"], ["3"], ["452"]],
        )
        self.assertEqual(
            [request["query"]["marketTypes"] for request in requests],
            [["5000", "3795", "4703"], ["4791", "5009"], ["2043818"]],
        )
        self.assertEqual(
            [request["view"]["marketTypes"] for request in requests],
            [["5000", "3795", "4703"], ["4791", "5009"], ["2043818"]],
        )
        self.assertEqual([request["take"] for request in requests], [40, 40, 40])

    def test_betpawa_blank_feed_url_uses_default_endpoint(self) -> None:
        with (
            patch("scrapers.betpawa.BETPAWA_FEED_URL", "  "),
            patch("scrapers.betpawa._fetch_live_query", return_value=[]) as fetch,
        ):
            matches = fetch_betpawa_matches()

        self.assertEqual(matches, [])
        self.assertEqual(
            fetch.call_args.args[0],
            "https://www.betpawa.ng/api/sportsbook/v4/events/lists/by-queries",
        )

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
            tuple(
                request["skip"]
                for request in json.loads(call.kwargs["params"]["q"])["queries"]
            )
            for call in mocked_get.call_args_list
        ]
        self.assertEqual(skips, [(0, 0, 0), (2, 2, 2), (4, 4, 4)])

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
                                    "OddsType": {"OddsTypeName": "Total Goals 1.5"},
                                    "SpecialBetValue": 1.5,
                                    "MatchOdds": [
                                        {
                                            "OddAttribute": {"OddName": "Over"},
                                            "Outcome": {"OddOutcome": 1.4},
                                        },
                                        {
                                            "OddAttribute": {"OddName": "Under"},
                                            "Outcome": {"OddOutcome": 2.8},
                                        },
                                    ],
                                },
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
                                {
                                    "OddsType": {"OddsTypeName": "Draw No Bet"},
                                    "MatchOdds": [
                                        {
                                            "OddAttribute": {"OddName": "1 DNB"},
                                            "Outcome": {"OddOutcome": 1.7},
                                        },
                                        {
                                            "OddAttribute": {"OddName": "2 DNB"},
                                            "Outcome": {"OddOutcome": 2.2},
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

        self.assertEqual(len(parsed), 5)
        self.assertEqual(parsed[0]["bookie"], "BetKing")
        self.assertEqual(parsed[0]["home"], "Lagos United")
        self.assertEqual(parsed[0]["away"], "Abuja FC")
        self.assertEqual(parsed[0]["market"], "Over/Under 1.5 Goals")
        self.assertEqual((parsed[0]["outcome_a"], parsed[0]["outcome_b"]), (1.4, 2.8))
        self.assertEqual(parsed[1]["market"], "Over/Under 3.5 Goals")
        self.assertEqual((parsed[1]["outcome_a"], parsed[1]["outcome_b"]), (2.4, 1.6))
        self.assertEqual(parsed[2]["market"], "Over/Under 2.5 Goals")
        self.assertEqual(
            (parsed[2]["outcome_a"], parsed[2]["outcome_b"]),
            (1.9, 2.0),
        )
        self.assertEqual(parsed[3]["market"], "Both Teams to Score")
        self.assertEqual((parsed[3]["outcome_a"], parsed[3]["outcome_b"]), (1.8, 2.1))
        self.assertEqual(parsed[4]["market"], "Draw No Bet")
        self.assertEqual((parsed[4]["outcome_a"], parsed[4]["outcome_b"]), (1.7, 2.2))
        self.assertEqual(parsed[0]["league"], "Nigeria - Premier League")
        self.assertEqual(parsed[0]["url"], "https://www.betking.com/")

    def test_betking_parses_basketball_tennis_and_points_totals(self) -> None:
        def collection(name: str, selection_a: str, selection_b: str) -> dict[str, Any]:
            return {
                "OddsType": {
                    "OddsTypeID": {"Moneyline": 9300, "1-2": 9388}.get(name),
                    "OddsTypeName": name,
                },
                "SpecialBetValue": 161.5 if "Points" in name else 0,
                "MatchOdds": [
                    {
                        "OddAttribute": {"OddName": selection_a},
                        "Outcome": {"OddOutcome": 1.9},
                    },
                    {
                        "OddAttribute": {"OddName": selection_b},
                        "Outcome": {"OddOutcome": 2.0},
                    },
                ],
            }

        payload = {
            "AreaMatches": [
                {
                    "SportName": "Basketball",
                    "Items": [
                        {
                            "ItemName": "Home Hoops - Away Hoops",
                            "ItemDate": "2026-12-01T16:00:00Z",
                            "Teams": [
                                {"Name": "Home Hoops", "ItemOrder": 1},
                                {"Name": "Away Hoops", "ItemOrder": 2},
                            ],
                            "OddsCollection": [
                                collection("Moneyline", "1", "2"),
                                collection("Total Points Over/Under", "Over", "Under"),
                            ],
                        }
                    ],
                },
                {
                    "SportName": "Tennis",
                    "Items": [
                        {
                            "ItemName": "Player One - Player Two",
                            "ItemDate": "2026-12-01T17:00:00Z",
                            "Teams": [
                                {"Name": "Player One", "ItemOrder": 1},
                                {"Name": "Player Two", "ItemOrder": 2},
                            ],
                            "OddsCollection": [collection("1-2", "1", "2")],
                        }
                    ],
                },
                {
                    "SportName": "FootballGO",
                    "Items": [
                        {
                            "ItemName": "Virtual One - Virtual Two",
                            "ItemDate": "2026-12-01T18:00:00Z",
                            "Teams": [
                                {"Name": "Virtual One", "ItemOrder": 1},
                                {"Name": "Virtual Two", "ItemOrder": 2},
                            ],
                            "OddsCollection": [collection("Moneyline", "1", "2")],
                        }
                    ],
                },
            ]
        }

        parsed = parse_betking_payload(payload)

        self.assertEqual(
            [(row["sport"], row["market"]) for row in parsed],
            [
                ("Basketball", "Match Winner"),
                ("Basketball", "Over/Under 161.5 Points"),
                ("Tennis", "Match Winner"),
            ],
        )

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
        responses = []
        for _ in range(6):
            response = Mock()
            response.raise_for_status.return_value = None
            response.json.return_value = shared_match
            responses.append(response)

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
                side_effect=responses,
            ) as mocked_get,
        ):
            matches = fetch_betking_matches()

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["home"], "Lagos United")
        self.assertEqual(matches[0]["away"], "Abuja FC")
        self.assertEqual(mocked_get.call_count, 6)
        requested_urls = [call.args[0] for call in mocked_get.call_args_list]
        self.assertEqual(
            {url.rsplit("/", 1)[-1] for url in requested_urls},
            {"1", "2", "5"},
        )
        self.assertEqual(
            {url.split("/GetEvents/en/")[1].split("/")[0] for url in requested_urls},
            {"2026-12-01", "2026-12-02"},
        )

    def test_betking_single_date_url_expands_both_dates(self) -> None:
        feed_url = (
            "https://sportsapicdn-desktop.betking.com/api/feeds/"
            "prematch/GetEvents/en/2026-12-01/0/0/1"
        )
        with patch(
            "scrapers.betking._utc_dates",
            return_value=("2026-12-01", "2026-12-02"),
        ):
            responses = []
            for _ in range(6):
                response = Mock()
                response.raise_for_status.return_value = None
                response.json.return_value = {"AreaMatches": []}
                responses.append(response)
            with (
                patch("scrapers.betking.BETKING_FEED_URL", feed_url),
                patch(
                    "scrapers.betking.curl_requests.get",
                    side_effect=responses,
                ) as mocked_get,
            ):
                matches = fetch_betking_matches()

        self.assertEqual(matches, [])
        self.assertEqual(mocked_get.call_count, 6)

    def test_betking_blank_feed_url_uses_default_endpoint(self) -> None:
        with (
            patch("scrapers.betking.BETKING_FEED_URL", " \t"),
            patch("scrapers.betking._date_wide_urls", return_value=None),
            patch("scrapers.betking.fetch_json_feed", return_value=[]) as fetch,
        ):
            matches = fetch_betking_matches()

        self.assertEqual(matches, [])
        self.assertEqual(
            fetch.call_args.args[0],
            "https://sportsapicdn-desktop.betking.com/api/feeds/prematch/"
            "GetEvents/en/{date}/0/0/1",
        )

    def test_msport_maps_live_schema_for_supported_sports_and_markets(self) -> None:
        def market(
            market_id: int,
            name: str,
            specifiers: str,
            outcome_a: tuple[str, str, int],
            outcome_b: tuple[str, str, int],
        ) -> dict[str, Any]:
            return {
                "id": market_id,
                "name": name,
                "specifiers": specifiers,
                "outcomes": [
                    {
                        "description": outcome_a[0],
                        "odds": outcome_a[1],
                        "isActive": outcome_a[2],
                    },
                    {
                        "description": outcome_b[0],
                        "odds": outcome_b[1],
                        "isActive": outcome_b[2],
                    },
                ],
            }

        def event(
            event_id: str,
            sport_id: str,
            home: str,
            away: str,
            markets: list[dict[str, Any]],
            *,
            status: int = 0,
            booking_status: str = "Booked",
        ) -> dict[str, Any]:
            return {
                "eventId": event_id,
                "sportId": sport_id,
                "status": status,
                "bookingStatus": booking_status,
                "homeTeam": home,
                "awayTeam": away,
                "startTime": 1_796_140_800_000,
                "tournament": "Test League",
                "markets": markets,
            }

        payload = {
            "bizCode": 10000,
            "data": {
                "events": [
                    event(
                        "football-1",
                        "sr:sport:1",
                        "Lagos United",
                        "Abuja FC",
                        [
                            market(18, "Over/Under", "total=1.5", ("Over 1.5", "1.40", 1), ("Under 1.5", "2.80", 1)),
                            market(18, "Over/Under", "total=2.5", ("Over 2.5", "2.00", 1), ("Under 2.5", "1.90", 1)),
                            market(18, "Over/Under", "total=3.5", ("Over 3.5", "2.50", 1), ("Under 3.5", "1.50", 1)),
                            market(29, "GG/NG", "", ("Yes", "1.80", 1), ("No", "2.10", 1)),
                            market(11, "Draw No Bet", "", ("Home", "1.70", 1), ("Away", "2.20", 1)),
                            market(18, "Over/Under", "total=2.5", ("Over 2.5", "2.00", 0), ("Under 2.5", "1.90", 1)),
                            market(1, "1x2", "", ("Home", "2.00", 1), ("Draw", "3.00", 1)),
                        ],
                    ),
                    event(
                        "basketball-1",
                        "sr:sport:2",
                        "Home Hoops",
                        "Away Hoops",
                        [
                            market(219, "Winner (incl. OT)", "", ("Home", "1.80", 1), ("Away", "2.10", 1)),
                            market(225, "O/U (incl. OT)", "total=161.5", ("Over 161.5", "1.90", 1), ("Under 161.5", "1.90", 1)),
                            market(227, "Home O/U (incl. OT)", "total=80.5", ("Over 80.5", "1.90", 1), ("Under 80.5", "1.90", 1)),
                        ],
                    ),
                    event(
                        "tennis-1",
                        "sr:sport:5",
                        "Player One",
                        "Player Two",
                        [
                            market(186, "Winner", "", ("Home", "1.70", 1), ("Away", "2.20", 1)),
                            market(202, "Set Winner", "setnr=1", ("Home", "1.70", 1), ("Away", "2.20", 1)),
                        ],
                    ),
                    event(
                        "live-1",
                        "sr:sport:1",
                        "Live Home",
                        "Live Away",
                        [market(18, "Over/Under", "total=2.5", ("Over 2.5", "2.00", 1), ("Under 2.5", "1.90", 1))],
                        status=1,
                    ),
                    event(
                        "unavailable-1",
                        "sr:sport:1",
                        "Unavailable Home",
                        "Unavailable Away",
                        [market(29, "GG/NG", "", ("Yes", "1.80", 1), ("No", "2.10", 1))],
                        booking_status="Unavailable",
                    ),
                ]
            },
        }

        parsed = parse_msport_payload(payload)

        self.assertEqual(
            [(row["sport"], row["market"]) for row in parsed],
            [
                ("Football", "Over/Under 1.5 Goals"),
                ("Football", "Over/Under 2.5 Goals"),
                ("Football", "Over/Under 3.5 Goals"),
                ("Football", "Both Teams to Score"),
                ("Football", "Draw No Bet"),
                ("Basketball", "Match Winner"),
                ("Basketball", "Over/Under 161.5 Points"),
                ("Tennis", "Match Winner"),
            ],
        )
        self.assertEqual(parsed[0]["bookie"], "MSport")
        self.assertEqual(
            (parsed[0]["outcome_a"], parsed[0]["outcome_b"]),
            (1.4, 2.8),
        )
        self.assertEqual(parsed[3]["league"], "Test League")
        self.assertEqual(parsed[5]["home"], "Home Hoops")
        self.assertEqual(parsed[7]["away"], "Player Two")

    def test_msport_fetches_each_supported_sport_and_passes_operator_header(self) -> None:
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"bizCode": 10000, "data": {"events": []}}
        feed_url = (
            "https://www.msport.com/api/ng/facts-center/query/frontend/"
            "all-matches/next-7-days"
        )
        with (
            patch("scrapers.msport.MSPORT_FEED_URL", feed_url),
            patch(
                "scrapers.msport.curl_requests.get",
                return_value=response,
            ) as mocked_get,
        ):
            matches = fetch_msport_matches()

        self.assertEqual(matches, [])
        self.assertEqual(mocked_get.call_count, 3)
        self.assertEqual(
            [call.kwargs["params"]["sportId"] for call in mocked_get.call_args_list],
            ["sr:sport:1", "sr:sport:2", "sr:sport:5"],
        )
        for call in mocked_get.call_args_list:
            self.assertEqual(call.kwargs["headers"]["OperId"], "2")
            self.assertEqual(call.kwargs["headers"]["Accept"], "application/json")

    def test_msport_loads_normalized_records_from_file_url(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.json"
            path.write_text(
                json.dumps({"matches": [self.normalized_match]}),
                encoding="utf-8",
            )
            with patch("scrapers.msport.MSPORT_FEED_URL", path.as_uri()):
                matches = fetch_msport_matches()

        self.assertEqual(matches[0]["bookie"], "MSport")
        self.assertEqual(matches[0]["home"], "Lagos United")


if __name__ == "__main__":
    unittest.main()
