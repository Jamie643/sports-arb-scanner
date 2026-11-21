# Sports Arbitrage Scanner

A lightweight FastAPI scanner for pre-match two-way football markets. It compares
configured Betpawa Nigeria and Bet9ja Nigeria JSON feeds, and optionally BetKing
Nigeria, matches events with RapidFuzz, calculates stakes from a ₦10,000 default
bankroll, and sends new opportunities to Telegram. No browser automation is used.

## Setup

1. Use Python 3.10 or later and install dependencies with `pip install -r requirements.txt`.
2. Copy `.env.example` to `.env`, then set the Telegram credentials and feed
   URLs. BetKing is optional.
3. Start the server with `uvicorn main:app --host 0.0.0.0 --port 8000`.
4. Configure an external uptime monitor to request `GET /health` every five
   minutes. The endpoint returns `{"status":"ok"}`.

The scanner polls configured feeds every 45 seconds. Feed URLs must be public
JSON endpoints you are authorized to access.

## Daily batch scan

Run one scan pass with `python run_once.py`. It checks pre-match opportunities
from the current UTC time through `MAX_LOOKAHEAD_HOURS` (default `24.0`) and
sends alerts to Telegram. Set `NOTIFY_EMPTY=true` to send a Telegram note when
a successful scan finds no opportunities; it defaults to `false`.
Opportunities above `MAX_ARBITRAGE_PROFIT_PCT` ROI (default `15.0%`) and
matches kicking off in less than `MIN_MINUTES_TO_KICKOFF` (default `15`)
minutes are skipped. Fixtures match only when home and away names match in
their respective positions; kickoff times are at most 30 minutes apart. When
both feeds provide a league, those names must also fuzzy-match.

The GitHub Actions workflow runs four times daily:

| WAT | UTC |
| --- | --- |
| 08:00 | 07:00 |
| 12:00 | 11:00 |
| 15:30 | 14:30 |
| 19:30 | 18:30 |

Manual runs are also available through `workflow_dispatch`. Each Actions
invocation is an independent one-shot scan: it does not persist Telegram alert
deduplication between runs, so an opportunity still present at a later scan may
be alerted again. The long-running FastAPI scanner only deduplicates in memory
for the lifetime of its process. No cache is needed for the stateless batch
workflow.

Betpawa and BetKing use built-in public feed URLs by default, so their URLs do
not need to be configured in GitHub Actions. To override them locally, set
`BETPAWA_FEED_URL` or `BETKING_FEED_URL` to a valid HTTP, HTTPS, or local file
URL. Blank or whitespace-only values use the defaults. Configure
`BET9JA_FEED_URL`, `TELEGRAM_BOT_TOKEN`, and `TELEGRAM_CHAT_ID` as repository
Actions secrets (the chat ID can also be a repository variable). When
`BET9JA_FEED_URL` is unset, the batch scan logs a skip and proceeds with an
empty Bet9ja feed. Optional secrets
`DEFAULT_STAKE_NGN`, `MAX_LOOKAHEAD_HOURS`,
`MAX_ARBITRAGE_PROFIT_PCT`, `MIN_MINUTES_TO_KICKOFF`, and `NOTIFY_EMPTY`
default to `10000`, `24.0`, `15.0`, `15`, and `false`, respectively.

## Feed format

Each URL should return either a list of records or an object containing a
`matches` list. A record uses this schema:

```json
{
  "home": "Arsenal",
  "away": "Manchester City",
  "kickoff": "2026-11-20T18:00:00Z",
  "market": "Over/Under 2.5 Goals",
  "outcome_a": 2.1,
  "outcome_b": 1.8,
  "url": "https://sportsbook.example/event",
  "league": "English Premier League"
}
```

`outcome_a` must consistently mean Over/Home/Yes and `outcome_b`
Under/Away/No on both providers. Supported markets include Over/Under 1.5,
2.5, and 3.5 Goals, Both Teams to Score, and Draw No Bet. `league` is optional
and defaults to an empty string. The adapter overwrites `bookie` with the
configured provider name.

The BetKing adapter maps the public `AreaMatches` / `Items` /
`OddsCollection` structure, including full-match Total Goals 2.5 and `GG/NG`
(Both Teams to Score), Total Goals 1.5/3.5, and Draw No Bet selections.
Date-wide BetKing URLs fetch the current and
next UTC date. It defaults to the public date-wide feed; set `BETKING_FEED_URL`
only to override it. Local `file://` feeds and normalized records are supported
as well. Its matches are compared against Betpawa and Bet9ja by both scanners.

Betpawa defaults to `/api/sportsbook/v4/events/lists/by-queries` and uses the
built-in upcoming-football query for Over/Under 1.5/2.5/3.5, Both Teams to
Score, and Draw No Bet.
Set `BETPAWA_FEED_URL` only to override the endpoint. The adapter sends the
`X-Pawa-Brand` header and maps the native event response. Normalized and
`file://` inputs remain supported.
Bet9ja retains normalized-list support and accepts an optional provider parser
through `parse_payload(payload, native_parser=...)`; unknown native payloads
fail explicitly instead of being guessed.

Arbitrage is emitted only when the two-way implied probability is below 0.99
and the rounded stakes still leave positive profit. Stakes use ₦100 increments
and the total cannot exceed the configured bankroll. Prices can change before
placement, so calculated profit is only guaranteed if both displayed odds are
still available. For Draw No Bet, profit is positive when the match has a
decisive result; if it is drawn, both stakes are refunded. Fees and limits are
not modeled.

## Validation

Run the mock engine cases with `python -m unittest discover -s tests`. Check
the running service with `curl http://localhost:8000/health`.
