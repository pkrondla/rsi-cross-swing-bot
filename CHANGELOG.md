# Changelog

## 0.2.0

- Rename package/CLI/deploy path to `rsi-cross-swing-bot` / `rsi-bot` / `C:\rsi-cross-swing-bot`.
- Multi-sleeve config (`config/sleeves.yaml`): `tqqq` (QQQ→TQQQ) and `goog` (GOOG→GOOG).
- Per-sleeve NSSM services (`RsiCross-tqqq`, `RsiCross-goog`), shared watchdog, and Telegram control process (`RsiCrossCtrl`) as the sole `getUpdates` poller.
- Sleeve-aware Telegram commands (`/status tqqq`, `/flatten goog`, …); serve drains a per-sleeve inbox.

## 0.1.0

- Initial QQQ RSI → TQQQ long-only bot with IB Gateway adapter, dry-run default, Telegram alerts, SQLite fill ledger (bot-owned quantity only), CI, and WinRM CD.
