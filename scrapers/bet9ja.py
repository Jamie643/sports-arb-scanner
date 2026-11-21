from collections.abc import Callable
from typing import Any

from scrapers.common import (
    fetch_json_feed,
    is_normalized_payload,
    normalize_matches,
)
from settings import BET9JA_FEED_URL


def parse_payload(
    payload: Any,
    native_parser: Callable[[Any], Any] | None = None,
) -> list[dict[str, Any]]:
    """Adapt Bet9ja JSON to the scanner schema.

    The normalized-list format remains supported. Supply ``native_parser`` when
    the provider's source schema is known; it must return normalized records.
    """
    if is_normalized_payload(payload):
        return normalize_matches(payload, "Bet9ja")
    if native_parser is None:
        raise ValueError(
            "Bet9ja payload is not normalized and no native parser was provided"
        )
    return normalize_matches(native_parser(payload), "Bet9ja")


def fetch_matches(
    native_parser: Callable[[Any], Any] | None = None,
) -> list[dict[str, Any]]:
    """Fetch Bet9ja matches, optionally mapping its native payload schema."""
    return fetch_json_feed(
        BET9JA_FEED_URL,
        "Bet9ja",
        lambda payload: parse_payload(payload, native_parser),
    )
