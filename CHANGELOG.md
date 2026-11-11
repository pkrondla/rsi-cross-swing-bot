# Changelog

## Unreleased

- Read-only watchlist alerts: new `rsi-bot watch` process (NSSM `RsiCrossList`) scans watched symbols hourly through the NYSE session and Telegrams the first RSI×SMA-of-RSI cross per direction per day. Read-only IB connection on `WATCH_IB_CLIENT_ID` (default 77); no order path.
- Telegram `/watch` commands: `/watch [list]`, `/watch add <sym>`, `/watch remove <sym>`, `/watch long <sym>`, `/watch flat <sym>` (list + marks in `data/watchlist/watchlist.json`, alert dedupe + virtual position in `data/watchlist/state.json`, both written atomically).
- Watch-only deployments: `sleeves: {}` is now valid; control, watchdog and deploy scripts run with no sleeves. The watchdog also monitors the watchlist heartbeat.
- `IbClient` reconnects after the gateway drops instead of failing every call until restart (sleeves benefit too).
- CD stops `RsiCrossList` and any `RsiCross-*` service before updating code.

## 0.2.0

- Rename package/CLI/deploy path to `rsi-cross-swing-bot` / `rsi-bot` / `C:\rsi-cross-swing-bot`.
- Multi-sleeve config (`config/sleeves.yaml`): `tqqq` (QQQ→TQQQ) and `goog` (GOOG→GOOG).
- Per-sleeve NSSM services (`RsiCross-tqqq`, `RsiCross-goog`), shared watchdog, and Telegram control process (`RsiCrossCtrl`) as the sole `getUpdates` poller.
- Sleeve-aware Telegram commands (`/status tqqq`, `/flatten goog`, …); serve drains a per-sleeve inbox.

## 0.1.0

- Initial QQQ RSI → TQQQ long-only bot with IB Gateway adapter, dry-run default, Telegram alerts, SQLite fill ledger (bot-owned quantity only), CI, and WinRM CD.
