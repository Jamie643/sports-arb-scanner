import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

from scrapers.polymarket import (
    _fetch_best_asks,
    _fetch_event_pages,
    fetch_matches,
    parse_payload,
)


class PolymarketScraperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime.now(timezone.utc)
        self.kickoff = (self.now + timedelta(hours=5)).isoformat()

    def _event(
        self,
        *,
        sport: str,
        title: str,
        markets: list[dict[str, object]],
        event_id: str = "event-1",
        slug: str | None = None,
        kickoff: str | None = None,
        teams: list[dict[str, str]] | None = None,
    ) -> dict[str, object]:
        return {
            "id": event_id,
            "slug": slug or f"event-{event_id}",
            "title": title,
            "startTime": kickoff or self.kickoff,
            "active": True,
            "closed": False,
            "tags": [{"label": sport}],
            "teams": teams or [],
            "markets": markets,
        }

    def _market(
        self,
        *,
        market_type: str,
        outcomes: list[str],
        tokens: list[str],
        question: str,
        group_title: str | None = None,
        line: float | None = None,
    ) -> dict[str, object]:
        return {
            "sportsMarketType": market_type,
            "question": question,
            "groupItemTitle": group_title,
            "line": line,
            "outcomes": outcomes,
            "clobTokenIds": tokens,
            "active": True,
            "closed": False,
        }

    def test_maps_moneyline_by_outcome_labels_not_array_order(self) -> None:
        market = self._market(
            market_type="moneyline",
            outcomes=["Away Hoops", "Home Hoops"],
            tokens=["away-token", "home-token"],
            question="Home Hoops vs. Away Hoops",
        )
        event = self._event(
            sport="Basketball",
            title="Home Hoops vs. Away Hoops",
            markets=[market],
        )

        rows = parse_payload(
            [event],
            best_asks={"home-token": 0.4, "away-token": 0.5},
            now_utc=self.now,
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["bookie"], "Polymarket")
        self.assertEqual(rows[0]["sport"], "Basketball")
        self.assertEqual(rows[0]["home"], "Home Hoops")
        self.assertEqual(rows[0]["away"], "Away Hoops")
        self.assertEqual(rows[0]["market"], "Match Winner")
        self.assertEqual((rows[0]["outcome_a"], rows[0]["outcome_b"]), (2.5, 2.0))

    def test_maps_tennis_match_winner_and_rejects_ambiguous_moneyline(self) -> None:
        tennis = self._event(
            sport="Tennis",
            title="Player One vs. Player Two",
            markets=[
                self._market(
                    market_type="moneyline",
                    outcomes=["Player One", "Player Two"],
                    tokens=["player-one", "player-two"],
                    question="Player One vs. Player Two",
                )
            ],
        )
        ambiguous = self._event(
            sport="Basketball",
            title="Home Hoops vs. Away Hoops",
            event_id="ambiguous",
            markets=[
                self._market(
                    market_type="moneyline",
                    outcomes=["Yes", "No"],
                    tokens=["yes-token", "no-token"],
                    question="Home Hoops to win?",
                )
            ],
        )

        rows = parse_payload(
            [tennis, ambiguous],
            best_asks={
                "player-one": 0.4,
                "player-two": 0.5,
                "yes-token": 0.2,
                "no-token": 0.8,
            },
            now_utc=self.now,
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["sport"], "Tennis")
        self.assertEqual(rows[0]["market"], "Match Winner")
        self.assertEqual((rows[0]["outcome_a"], rows[0]["outcome_b"]), (2.5, 2.0))

    def test_normalizes_nba_home_away_from_verified_slug_abbreviations(self) -> None:
        event = self._event(
            sport="Basketball",
            title="Mia vs. Washington Wizards",
            slug="nba-mia-was-2026-11-22",
            teams=[
                {"name": "Washington Wizards", "abbreviation": "WAS"},
                {"name": "Miami Heat", "abbreviation": "MIA"},
            ],
            markets=[
                self._market(
                    market_type="moneyline",
                    outcomes=["Mia", "Was"],
                    tokens=["miami-token", "washington-token"],
                    question="Mia vs. Washington Wizards",
                )
            ],
        )

        rows = parse_payload(
            [event],
            best_asks={"miami-token": 0.5, "washington-token": 0.4},
            now_utc=self.now,
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["home"], "Washington Wizards")
        self.assertEqual(rows[0]["away"], "Miami Heat")
        self.assertEqual((rows[0]["outcome_a"], rows[0]["outcome_b"]), (2.5, 2.0))

    def test_strips_tennis_tournament_prefix_using_team_metadata(self) -> None:
        event = self._event(
            sport="Tennis",
            title="Ankara (Doubles): Hernandez/Wehnelt vs. Oetzbach/Wiskandt",
            teams=[
                {"name": "Hernandez/Wehnelt"},
                {"name": "Oetzbach/Wiskandt"},
            ],
            markets=[
                self._market(
                    market_type="moneyline",
                    outcomes=["Oetzbach/Wiskandt", "Hernandez/Wehnelt"],
                    tokens=["team-two-token", "team-one-token"],
                    question="Hernandez/Wehnelt vs. Oetzbach/Wiskandt",
                )
            ],
        )

        rows = parse_payload(
            [event],
            best_asks={"team-one-token": 0.4, "team-two-token": 0.5},
            now_utc=self.now,
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["home"], "Hernandez/Wehnelt")
        self.assertEqual(rows[0]["away"], "Oetzbach/Wiskandt")
        self.assertEqual((rows[0]["outcome_a"], rows[0]["outcome_b"]), (2.5, 2.0))

    def test_uses_eight_minute_kickoff_boundary_and_parses_utc_offsets(self) -> None:
        market = self._market(
            market_type="moneyline",
            outcomes=["Home Hoops", "Away Hoops"],
            tokens=["home-token", "away-token"],
            question="Home Hoops vs. Away Hoops",
        )
        events = [
            self._event(
                sport="Basketball",
                title="Home Hoops vs. Away Hoops",
                event_id=f"event-{minutes}",
                kickoff=(self.now + timedelta(minutes=minutes)).isoformat(),
                markets=[market],
            )
            for minutes in (7, 8, 10)
        ]

        with patch("scrapers.polymarket.MIN_MINUTES_TO_KICKOFF", 8):
            rows = parse_payload(
                events,
                best_asks={"home-token": 0.4, "away-token": 0.5},
                now_utc=self.now,
            )

        self.assertEqual(len(rows), 2)
        self.assertEqual(
            {row["kickoff"] for row in rows},
            {
                (self.now + timedelta(minutes=8)).isoformat(),
                (self.now + timedelta(minutes=10)).isoformat(),
            },
        )

    def test_maps_unambiguous_totals_and_rejects_other_sports_or_lines(self) -> None:
        basketball = self._event(
            sport="Basketball",
            title="Home Hoops vs. Away Hoops",
            markets=[
                self._market(
                    market_type="totals",
                    outcomes=["Under", "Over"],
                    tokens=["under-token", "over-token"],
                    question="Home Hoops vs. Away Hoops: O/U 160.5",
                    group_title="O/U 160.5",
                ),
                self._market(
                    market_type="totals",
                    outcomes=["Over", "Under"],
                    tokens=["unsupported-over", "unsupported-under"],
                    question="Home Hoops vs. Away Hoops: O/U 160.5 1st Half",
                    group_title="1st Half O/U 160.5",
                ),
            ],
        )
        football = self._event(
            sport="Soccer",
            title="Home FC vs. Away FC",
            event_id="football",
            markets=[
                self._market(
                    market_type="totals",
                    outcomes=["Over", "Under"],
                    tokens=["over-goals", "under-goals"],
                    question="Home FC vs. Away FC: O/U 2.5",
                    group_title="O/U 2.5",
                ),
                self._market(
                    market_type="totals",
                    outcomes=["Over", "Under"],
                    tokens=["over-unsupported", "under-unsupported"],
                    question="Home FC vs. Away FC: O/U 4.5",
                    group_title="O/U 4.5",
                ),
            ],
        )
        tennis = self._event(
            sport="Tennis",
            title="Player One vs. Player Two",
            event_id="tennis",
            markets=[
                self._market(
                    market_type="totals",
                    outcomes=["Over", "Under"],
                    tokens=["tennis-over", "tennis-under"],
                    question="Player One vs. Player Two: O/U 22.5",
                    group_title="O/U 22.5",
                )
            ],
        )

        rows = parse_payload(
            [basketball, football, tennis],
            best_asks={
                "under-token": 0.5,
                "over-token": 0.4,
                "over-goals": 0.45,
                "under-goals": 0.55,
                "over-unsupported": 0.3,
                "under-unsupported": 0.7,
                "tennis-over": 0.4,
                "tennis-under": 0.6,
            },
            now_utc=self.now,
        )

        self.assertEqual(
            [(row["sport"], row["market"]) for row in rows],
            [
                ("Basketball", "Over/Under 160.5 Points"),
                ("Football", "Over/Under 2.5 Goals"),
            ],
        )
        self.assertEqual((rows[0]["outcome_a"], rows[0]["outcome_b"]), (2.5, 2.0))

    def test_missing_or_out_of_range_buy_asks_are_not_actionable(self) -> None:
        market = self._market(
            market_type="moneyline",
            outcomes=["Home Hoops", "Away Hoops"],
            tokens=["home-token", "away-token"],
            question="Home Hoops vs. Away Hoops",
        )
        event = self._event(
            sport="Basketball",
            title="Home Hoops vs. Away Hoops",
            markets=[market],
        )

        self.assertEqual(
            parse_payload(
                [event],
                best_asks={"home-token": 0.4},
                now_utc=self.now,
            ),
            [],
        )
        for invalid_price in (0.0, 0.01, 0.99, 1.0):
            with self.subTest(invalid_price=invalid_price):
                self.assertEqual(
                    parse_payload(
                        [event],
                        best_asks={
                            "home-token": invalid_price,
                            "away-token": 0.5,
                        },
                        now_utc=self.now,
                    ),
                    [],
                )

    def test_fetches_books_in_batches_and_uses_lowest_ask(self) -> None:
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = [
            {
                "asset_id": "token-a",
                "asks": [{"price": "0.5"}, {"price": "0.4"}],
            },
            {"asset_id": "token-b", "asks": []},
        ]
        with patch(
            "scrapers.polymarket.curl_requests.post",
            return_value=response,
        ) as post:
            asks = _fetch_best_asks(["token-a", "token-b"])

        self.assertEqual(asks, {"token-a": 0.4})
        post.assert_called_once()
        self.assertEqual(
            post.call_args.kwargs["json"],
            [{"token_id": "token-a"}, {"token_id": "token-b"}],
        )

    def test_gamma_event_pages_are_bounded_and_offset(self) -> None:
        first = Mock()
        first.raise_for_status.return_value = None
        first.json.return_value = [{"id": "event-1"}, {"id": "event-2"}]
        second = Mock()
        second.raise_for_status.return_value = None
        second.json.return_value = [{"id": "event-3"}]
        with (
            patch("scrapers.polymarket._EVENT_PAGE_SIZE", 2),
            patch(
                "scrapers.polymarket.curl_requests.get",
                side_effect=[first, second],
            ) as get,
        ):
            events = _fetch_event_pages(
                "https://gamma-api.polymarket.com/events",
                self.now,
                tag_id="864",
            )

        self.assertEqual([event["id"] for event in events], [
            "event-1",
            "event-2",
            "event-3",
        ])
        self.assertEqual(
            [call.kwargs["params"]["offset"] for call in get.call_args_list],
            [0, 2],
        )
        self.assertEqual(
            [call.kwargs["params"]["tag_id"] for call in get.call_args_list],
            ["864", "864"],
        )

    def test_fetch_matches_combines_gamma_events_and_clob_best_asks(self) -> None:
        event = self._event(
            sport="Basketball",
            title="Home Hoops vs. Away Hoops",
            markets=[
                self._market(
                    market_type="moneyline",
                    outcomes=["Home Hoops", "Away Hoops"],
                    tokens=["home-token", "away-token"],
                    question="Home Hoops vs. Away Hoops",
                )
            ],
        )
        gamma_response = Mock()
        gamma_response.raise_for_status.return_value = None
        gamma_response.json.return_value = [event]
        books_response = Mock()
        books_response.raise_for_status.return_value = None
        books_response.json.return_value = [
            {"asset_id": "home-token", "asks": [{"price": "0.4"}]},
            {"asset_id": "away-token", "asks": [{"price": "0.5"}]},
        ]
        with (
            patch(
                "scrapers.polymarket.POLYMARKET_FEED_URL",
                "https://gamma-api.polymarket.com/events",
            ),
            patch(
                "scrapers.polymarket.curl_requests.get",
                return_value=gamma_response,
            ),
            patch(
                "scrapers.polymarket.curl_requests.post",
                return_value=books_response,
            ),
        ):
            rows = fetch_matches()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["market"], "Match Winner")
        self.assertEqual((rows[0]["outcome_a"], rows[0]["outcome_b"]), (2.5, 2.0))


if __name__ == "__main__":
    unittest.main()
