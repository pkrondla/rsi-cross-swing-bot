# Deploy the QQQ RSI bot to Windows EC2

The bot runs in **`C:\qqq-rsi-bot`** as NSSM services **`QqqRsiBot`** and **`QqqRsiWatch`**.
It does **not** stop or change `C:\orb-bot` / OrbBot.

## One-time host prerequisites

- WinRM HTTPS on 5986
- Python 3.12, Git, `nssm` on PATH
- **IB Gateway** installed, logged in, API enabled on `127.0.0.1`
  - Paper default port **4002** (TWS paper **7497**)
  - Live default port **4001** (TWS live **7496**)
  - Read-Only API unchecked when orders are wanted
  - Auto restart enabled (weekly re-login after Saturday reset)
- US equity market data that is **not** 15-minute delayed (e.g. NASDAQ Network C/UTP)
- Client Portal: Market Data API access enabled

## GitHub environment `qqq-prod`

### Secrets

| Name | Purpose |
|---|---|
| `WINRM_PASSWORD` | Windows login |
| `GH_PAT` | repo read for clone/pull |
| `TELEGRAM_BOT_TOKEN` | dedicated BotFather bot |
| `IB_ACCOUNT` | optional if set as a variable instead |

### Variables

| Name | Purpose |
|---|---|
| `WINRM_HOST` | EC2 public IP/DNS |
| `WINRM_USERNAME` | Windows user |
| `TELEGRAM_CHAT_ID` | chat id |
| `IB_HOST` | usually `127.0.0.1` |
| `IB_PORT` | `4002` paper Gateway / `4001` live |
| `IB_CLIENT_ID` | unique integer (e.g. `17`) |
| `IB_ACCOUNT` | paper `DU…` or live account id |
| `ALLOCATED_USD` | sleeve capital |
| `LIVE_MODE` | `paper` (default) or `live` |
| `LIVE_ARMED` | `false` until intentional |
| `DRY_RUN` | `true` (default) |
| `HEALTHCHECK_URL` | optional |

## Deploy

Actions → **CD - Deploy QQQ RSI bot to Windows EC2** → Run workflow (always `main`).

Rollback on the host:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File C:\qqq-rsi-bot\scripts\deploy\Rollback-QqqRsiBot.ps1
```
