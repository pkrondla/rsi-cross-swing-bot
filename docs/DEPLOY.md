# Deploy the RSI cross swing bot to Windows EC2

The bot runs in **`C:\rsi-cross-swing-bot`**. Sleeve serve services are created
**automatically from** [`config/sleeves.yaml`](../config/sleeves.yaml):

| Service | Process |
|---|---|
| `RsiCross-<sleeve>` | `rsi-bot serve --sleeve <sleeve>` (one per sleeve) |
| `RsiCrossWatch` | `rsi-bot watchdog` (all sleeve heartbeats) |
| `RsiCrossCtrl` | `rsi-bot telegram` (sole Telegram poller) |

Adding a sleeve = edit `sleeves.yaml`, merge, redeploy. No CD/NSSM edits.

It does **not** stop or change `C:\orb-bot` / OrbBot. First deploy migrates `C:\qqq-rsi-bot\data` if present.

## One-time host prerequisites

- WinRM HTTPS on 5986
- Python 3.12, Git, `nssm` on PATH
- **IB Gateway** installed, logged in, API enabled on `127.0.0.1`
  - Paper default port **4002** (TWS paper **7497**)
  - Live default port **4001** (TWS live **7496**)
  - Read-Only API unchecked when orders are wanted
  - Auto restart enabled (weekly re-login after Saturday reset)
- US equity market data that is **not** 15-minute delayed
- Client Portal: Market Data API access enabled

## GitHub environment `prod`

Put **only credentials** in Secrets. Everything else is a Variable.

### Secrets

| Name | Purpose |
|---|---|
| `WINRM_PASSWORD` | Windows login password |
| `GH_PAT` | PAT with repo read (git clone/pull on the host) |
| `TELEGRAM_BOT_TOKEN` | BotFather bot token |

### Variables

| Name | Purpose |
|---|---|
| `WINRM_HOST` | EC2 public IP/DNS |
| `WINRM_USERNAME` | Windows user (e.g. `Administrator`) |
| `TELEGRAM_CHAT_ID` | Telegram chat id |
| `IB_HOST` | usually `127.0.0.1` |
| `IB_PORT` | `4002` paper Gateway / `4001` live |
| `IB_ACCOUNT` | paper `DU…` or live account id |
| `SLEEVE_ALLOCATIONS` | optional JSON capital overrides, e.g. `{"tqqq":"10000","aapl":"5000"}` |
| `LIVE_MODE` | `paper` (default) or `live` |
| `LIVE_ARMED` | `false` until intentional |
| `DRY_RUN` | `true` (default) |
| `HEALTHCHECK_URL` | optional |
| `WATCH_IB_CLIENT_ID` | optional IB client id for `RsiCrossList` (default 77); must not clash with sleeves or OrbBot |

Default capital and IB client ids come from [`config/sleeves.yaml`](../config/sleeves.yaml). Each sleeve needs a **unique** `ib_client_id`.

## Add a symbol

1. Add a block under `sleeves:` in `config/sleeves.yaml` (unique `ib_client_id`).
2. Merge to `main` and run CD.
3. Confirm market data, keep dry-run, then `/status <sleeve>` / `/dryrun <sleeve> off` when ready.

Orphan `RsiCross-*` services for sleeves removed from the YAML are deleted on the next deploy.

## Deploy

Actions → **CD - Deploy RSI cross swing bot to Windows EC2** → Run workflow (always `main`).

Rollback on the host:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File C:\rsi-cross-swing-bot\scripts\deploy\Rollback-RsiCrossBot.ps1
```
