from typing import Any

import requests

from settings import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


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
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError("Telegram bot token and chat ID must be configured")
    if (
        TELEGRAM_BOT_TOKEN == "replace_with_bot_token"
        or TELEGRAM_CHAT_ID == "replace_with_chat_id"
    ):
        raise RuntimeError("Replace the Telegram placeholder values in .env")

    response = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        json={"chat_id": TELEGRAM_CHAT_ID, "text": message},
        timeout=10,
    )
    response.raise_for_status()


def send_alert(opportunity: dict[str, Any]) -> None:
    send_message(format_alert(opportunity))
