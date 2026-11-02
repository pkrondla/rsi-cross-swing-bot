# QQQ RSI → TQQQ Bot

Long-only bot: **QQQ** daily indicators drive the signal; **TQQQ** is the execution symbol.
Paper / dry-run by default. Real orders need `LIVE_ARMED=true` and `DRY_RUN=false`.

## Rules

- Wilder RSI(14) and SMA(14) of RSI on QQQ daily RTH bars; EMA(200) trend filter.
- Enter on RSI crossing above its SMA when RSI &lt; 50 **or** QQQ close &gt; EMA(200).
- Exit on RSI crossing below its SMA. No price stop.
- Orders only at **15:58 America/New_York** (12:58 on NYSE early closes).
- Each entry spends a configured `ALLOCATED_USD` sleeve (whole shares).
- Sells **only shares this bot bought** (local fill ledger + `orderRef` prefix `qqq-rsi:`). Other TQQQ in the IB account is left alone.

## Setup

```powershell
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 setup
copy .env.example .env
# fill IB_*, ALLOCATED_USD, optional Telegram
```

IB Gateway must already be logged in on the host (API socket on `IB_PORT`). No API keys.

```
qqq-bot check
qqq-bot serve
qqq-bot watchdog
qqq-bot replay --last 60
qqq-bot status
qqq-bot flatten
```

Quality gates: `scripts\dev.ps1 ci` (ruff, mypy strict, import-linter, pytest coverage ≥ 90).

Deploy: [docs/DEPLOY.md](docs/DEPLOY.md). Ops: [docs/RUNBOOK.md](docs/RUNBOOK.md).
