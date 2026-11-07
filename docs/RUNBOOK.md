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

`/stop` blocks new strategy orders for that New York date only; it does not sell.

## Logs

`C:\rsi-cross-swing-bot\logs\rsi-cross-tqqq.log`, `rsi-cross-goog.log`, `rsi-cross-watch.log`, `rsi-cross-ctrl.log` (+ `-error` variants).
