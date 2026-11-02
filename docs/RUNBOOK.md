# Runbook

## Modes

| LIVE_MODE | LIVE_ARMED | DRY_RUN | Behaviour |
|---|---|---|---|
| paper | false | true | Default. Connects, simulates fills, no `placeOrder` |
| paper | true | true | Same dry-run venue |
| paper | true | false | Paper account orders via Gateway port 4002/7497 |
| live | true | false | Live account orders via Gateway port 4001/7496 |

## Gateway down

1. Telegram alert from serve or watchdog.
2. Log into IB Gateway on the host; approve IB Key if needed.
3. Confirm `qqq-bot check` is green.
4. NSSM: `nssm restart QqqRsiBot`.

Weekly: after Saturday night IB reset, log in once (Sunday).

## Missed decision window

The bot does not invent a cross after the fact. If it was down at 15:58 ET with an open bot position, use `/flatten` to sell **only** the bot quantity, or wait for the next valid exit cross.

## Position mismatch

If IB TQQQ quantity is **below** the bot ledger, the bot halts and will not sell. Investigate fills, then `/clearhalt` after fixing, or `/reconcile`.

## Telegram

`/help` `/status` `/mode` `/version` `/positions` `/allocation` `/stop` `/start` `/flatten` `/dryrun` `/reconcile` `/clearhalt`

`/stop` blocks new strategy orders for that New York date only; it does not sell.

## Logs

`C:\qqq-rsi-bot\logs\qqq-rsi-bot.log`, `qqq-rsi-bot-error.log`, `qqq-rsi-watch.log`.
