# RSI Cross Swing Bot

Long-only multi-sleeve bot: daily RSI crosses on a **signal** symbol drive entries/exits on an **execution** symbol.

Default sleeves ([`config/sleeves.yaml`](config/sleeves.yaml)):

| Sleeve | Signal | Execution |
|---|---|---|
| `tqqq` | QQQ | TQQQ |
| `goog` | GOOG | GOOG |

Paper / dry-run by default. Real orders need `LIVE_ARMED=true` and `DRY_RUN=false` (or `/dryrun <sleeve> off`).

## Rules

- Wilder RSI(14) and SMA(14) of RSI on the signal symbol's daily RTH bars; EMA(200) trend filter.
- Enter on RSI crossing above its SMA when RSI &lt; 50 **or** close &gt; EMA(200).
- Exit on RSI crossing below its SMA. No price stop.
- Orders only at **15:58 America/New_York** (12:58 on NYSE early closes).
- Each sleeve spends its own `allocated_usd` (whole shares).
- Sells **only shares that sleeve bought** (local fill ledger + `orderRef` prefix). Other holdings in the IB account are left alone.

## Setup

```powershell
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 setup
copy .env.example .env
# fill IB_*, optional Telegram; sleeve capital defaults live in config/sleeves.yaml
```

IB Gateway must already be logged in on the host (API socket on `IB_PORT`). No API keys.

```
rsi-bot sleeves
rsi-bot check --sleeve tqqq
rsi-bot serve --sleeve tqqq
rsi-bot serve --sleeve goog
rsi-bot watchdog
rsi-bot telegram
rsi-bot replay --sleeve tqqq --last 60
rsi-bot status --all
rsi-bot flatten --sleeve tqqq
```

Quality gates: `scripts\dev.ps1 ci` (ruff, mypy strict, import-linter, pytest coverage ≥ 90).

Deploy: [docs/DEPLOY.md](docs/DEPLOY.md). Ops: [docs/RUNBOOK.md](docs/RUNBOOK.md).

## Add a sleeve

1. Add an entry under `sleeves:` in [`config/sleeves.yaml`](config/sleeves.yaml) (unique `ib_client_id`).
2. Merge and run CD — launchers and NSSM services are generated from that file.
3. Optional capital override via GitHub var `SLEEVE_ALLOCATIONS` JSON, or Telegram `/allocation <sleeve> <usd>`.
