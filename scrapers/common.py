import json
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import url2pathname

from curl_cffi import requests as curl_requests


REQUIRED_FIELDS = {
    "home",
    "away",
    "kickoff",
    "market",
    "outcome_a",
    "outcome_b",
    "url",
}


def _feed_records(payload: Any, bookie: str) -> list[Any]:
    if isinstance(payload, dict):
        payload = payload.get("matches")
    if not isinstance(payload, list):
        raise ValueError(f"{bookie} feed must contain a JSON list of matches")
    return payload


def is_normalized_payload(payload: Any) -> bool:
    """Return whether every record has the scanner's common input fields."""
    if isinstance(payload, dict):
        payload = payload.get("matches")
    if not isinstance(payload, list):
        return False
    records = payload
    return all(
        isinstance(item, dict) and REQUIRED_FIELDS.issubset(item)
        for item in records
    )


def normalize_matches(payload: Any, bookie: str) -> list[dict[str, Any]]:
    """Validate common-schema records and attach the canonical bookmaker name."""
    records = _feed_records(payload, bookie)
    matches: list[dict[str, Any]] = []
    for index, item in enumerate(records):
        if not isinstance(item, dict):
            raise ValueError(f"{bookie} match at index {index} must be an object")
        missing = REQUIRED_FIELDS.difference(item)
        if missing:
            names = ", ".join(sorted(missing))
            raise ValueError(f"{bookie} match at index {index} is missing: {names}")

        try:
            outcome_a = float(item["outcome_a"])
            outcome_b = float(item["outcome_b"])
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"{bookie} match at index {index} has non-numeric odds"
            ) from exc
        if (
            not math.isfinite(outcome_a)
            or not math.isfinite(outcome_b)
            or outcome_a <= 1
            or outcome_b <= 1
        ):
            raise ValueError(f"{bookie} match at index {index} has invalid odds")

        matches.append(
            {
                "bookie": bookie,
                "sport": (
                    str(item.get("sport") or "Football").strip() or "Football"
                ),
                "home": str(item["home"]),
                "away": str(item["away"]),
                "kickoff": str(item["kickoff"]),
                "market": str(item["market"]),
                "outcome_a": outcome_a,
                "outcome_b": outcome_b,
                "url": str(item["url"]),
                "league": str(item.get("league") or ""),
            }
        )
    return matches


def fetch_json_feed(
    feed_url: str | None,
    bookie: str,
    parser: Callable[[Any], list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    """Load JSON from a local file or fetch it over HTTP for provider mapping."""
    if not feed_url:
        raise ValueError(f"{bookie} feed URL is not configured")

    parsed_url = urlparse(feed_url)
    if parsed_url.scheme == "file":
        if (
            parsed_url.netloc not in {"", "localhost"}
            or parsed_url.query
            or parsed_url.fragment
        ):
            raise ValueError(f"{bookie} file URL must refer to a local file")
        local_path = Path(url2pathname(parsed_url.path))
        if not local_path.is_absolute():
            raise ValueError(f"{bookie} file URL must use an absolute path")
        with local_path.open(encoding="utf-8") as feed_file:
            payload = json.load(feed_file)
    elif parsed_url.scheme in {"http", "https"}:
        response = curl_requests.get(
            feed_url,
            headers={"Accept": "application/json"},
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
    else:
        raise ValueError(f"{bookie} feed URL must use HTTP, HTTPS, or file")

    if parser is not None:
        return parser(payload)
    return normalize_matches(payload, bookie)
