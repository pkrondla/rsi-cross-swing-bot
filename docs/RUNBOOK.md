# Runbook

## Modes

| LIVE_MODE | LIVE_ARMED | DRY_RUN | Behaviour |
|---|---|---|---|
| paper | false | true | Default. Connects, simulates fills, no `placeOrder` |
| paper | true | true | Same dry-run venue |
| paper | true | false | Paper account orders via Gateway port 4002/7497 |
| live | true | false | Live account orders via Gateway port 4001/7496 |

`/dryrun <sleeve> on|off` overrides DRY_RUN per sleeve without redeploy.

## Sleeves

Configured in `config/sleeves.yaml` (currently `tqqq`, `goog`). CD/NSSM install
`RsiCross-<id>` for each entry automatically.

Data: `data/sleeves/<id>/` (SQLite ledger, halt, day-stop, heartbeat, inbox).

List: `rsi-bot sleeves` or Telegram `/sleeves`.

## Gateway down

1. Telegram alert from serve or watchdog.
2. Log into IB Gateway on the host; approve IB Key if needed.
3. Confirm `rsi-bot check --sleeve <id>` is green for each sleeve.
4. NSSM: `nssm restart RsiCross-<id>` (or `RsiCrossWatch` / `RsiCrossCtrl`).

Weekly: after Saturday night IB reset, log in once (Sunday).

## Missed decision window

The bot does not invent a cross after the fact. If it was down at 15:58 ET with an open bot position, use `/flatten <sleeve>` to sell **only** that sleeve's quantity, or wait for the next valid exit cross.

## Position mismatch

If IB quantity for the execution symbol is **below** the sleeve ledger, that sleeve halts and will not sell. Investigate fills, then `/clearhalt <sleeve>`, or `/reconcile <sleeve>`.

## Telegram (RsiCrossCtrl)

One bot / one chat. Control process owns `getUpdates`. Sleeve serves only send alerts.

`/help` `/sleeves` `/version`  
`/status [sleeve|all]` `/positions [sleeve]`  
`/allocation <sleeve> [usd]`  
`/stop [sleeve|all]` `/start [sleeve|all]`  
`/flatten [sleeve|all]` `/dryrun <sleeve> on|off`  
`/reconcile [sleeve]` `/clearhalt [sleeve]`  
`/watch [list]` `/watch add <sym>` `/watch remove <sym>` `/watch long <sym>` `/watch flat <sym>`

`/stop` blocks new strategy orders for that New York date only; it does not sell.

## Watchlist (RsiCrossList)

`rsi-bot watch` is read-only: it scans every watched symbol hourly from the
session open through the decision time (15:58 ET, 12:58 on early closes) and
alerts on RSI(14) crossing its SMA(14) — no entry filter, no position gate, no
orders. Edit the list via Telegram (`/watch …`); state lives in
`data/watchlist/` and survives restarts.

- At most one alert per symbol per session date per direction. A forming cross
  that flips back and forth alerts once for BUY and once for SELL, not repeatedly.
- Alerts say whether the bar was **forming** (intraday) or **closing** (the
  decision-time scan, or a prior session's completed bar), with the bar date.
- The virtual position only moves on a closing-bar cross, so an intraday cross
  that fades by the close does not flip it.
- `/watch long <sym>` / `/watch flat <sym>` set the position for names held
  elsewhere; the next confirmed cross takes over again.
- `/watch remove` then `/watch add` starts the symbol fresh.
- Symbols with no data (typos, delisted) are reported once:
  `[watch] no daily bars for APPL`. Share classes are typed `BRK.B`.
- If IB Gateway is down the scan stops, Telegram gets one "IB data unavailable"
  and one "restored" message, and it retries every 5 minutes. The heartbeat
  (`data/watchlist/heartbeat.json`) is not refreshed while down, so
  `RsiCrossWatch` alerts after 2 hours.
- Own IB connection, read-only, client id `WATCH_IB_CLIENT_ID` (default 77). It
  must differ from every sleeve's `ib_client_id` and from OrbBot's.
- US-listed stocks/ETFs only: contracts are `Stock(symbol, SMART, USD)` on the
  NYSE calendar, same as the sleeves.

### Alerts-only deployment

Set `sleeves: {}` in `config/sleeves.yaml` and deploy. CD then installs only
`RsiCrossCtrl`, `RsiCrossList` and `RsiCrossWatch` (the watchdog now monitors
the watchlist heartbeat) and removes any `RsiCross-<sleeve>` services. Sleeve
Telegram commands reply "no sleeves configured (watch-only)"; `/watch` works.

## Logs

`C:\rsi-cross-swing-bot\logs\rsi-cross-tqqq.log`, `rsi-cross-goog.log`, `rsi-cross-watch.log`, `rsi-cross-ctrl.log` (+ `-error` variants).
