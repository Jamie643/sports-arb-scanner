import re
from typing import Any

import requests

from settings import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


_BOT_TOKEN_PATTERN = re.compile(r"^\d+:[A-Za-z0-9_-]+$")


def validate_telegram_credentials() -> tuple[str, str]:
    token = (TELEGRAM_BOT_TOKEN or "").strip()
    chat_id = (TELEGRAM_CHAT_ID or "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing")
    if not chat_id:
        raise RuntimeError("TELEGRAM_CHAT_ID is missing")
    if token == "replace_with_bot_token" or chat_id == "replace_with_chat_id":
        raise RuntimeError("Telegram placeholder credentials must be replaced")
    if not _BOT_TOKEN_PATTERN.fullmatch(token):
        raise RuntimeError("TELEGRAM_BOT_TOKEN has an invalid format")
    if any(character.isspace() for character in chat_id):
        raise RuntimeError("TELEGRAM_CHAT_ID must not contain whitespace")
    return token, chat_id


def format_alert(opportunity: dict[str, Any]) -> str:
    leg_a = opportunity["leg_a"]
    leg_b = opportunity["leg_b"]
    if opportunity.get("draw_voids_both"):
        profit_text = (
            "Profit on decisive result*: "
            f"₦{opportunity['profit_on_decisive_result_ngn']:,.2f}\n"
            f"Draw: both stakes refunded (₦{opportunity['draw_refund_ngn']:,.0f})\n"
            f"ROI on decisive result: {opportunity['roi_pct']:.2f}%"
        )
    else:
        profit_text = (
            f"Guaranteed profit*: ₦{opportunity['guaranteed_profit_ngn']:,.2f}\n"
            f"ROI: {opportunity['roi_pct']:.2f}%"
        )
    return (
        "⚽ ARBITRAGE OPPORTUNITY\n\n"
        f"Match: {opportunity['home']} vs {opportunity['away']}\n"
        f"Market: {opportunity['market']}\n"
        f"Team match: {opportunity['match_score']}% confidence\n\n"
        f"{leg_a['bookie']} — {leg_a['outcome']} @ {leg_a['odds']:.2f}\n"
        f"Stake: ₦{leg_a['stake_ngn']:,.0f}\n"
        f"{leg_b['bookie']} — {leg_b['outcome']} @ {leg_b['odds']:.2f}\n"
        f"Stake: ₦{leg_b['stake_ngn']:,.0f}\n\n"
        f"Total stake: ₦{opportunity['total_stake_ngn']:,.0f}\n"
        f"{profit_text}\n\n"
        f"Kickoff: {opportunity['kickoff']}\n"
        "*Only if both quoted odds remain available at placement."
    )


def send_message(message: str) -> None:
    token, chat_id = validate_telegram_credentials()

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message},
            timeout=10,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status is not None:
            raise RuntimeError(f"Telegram API returned HTTP {status}") from None
        raise RuntimeError(
            f"Telegram API request failed ({type(exc).__name__})"
        ) from None

    try:
        result = response.json()
    except ValueError:
        raise RuntimeError("Telegram API returned invalid JSON") from None
    if not isinstance(result, dict) or result.get("ok") is not True:
        raise RuntimeError("Telegram API rejected the message (ok was not true)")


def send_alert(opportunity: dict[str, Any]) -> None:
    send_message(format_alert(opportunity))
