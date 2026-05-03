# FXTrader

Automated EUR/USD trading on OANDA (demo first, live-ready). Python backend
runs the strategy + risk controls; React PWA is the dashboard / kill switch.

## Architecture

```
┌────────────────────┐    HTTP + WebSocket     ┌────────────────────┐
│  PWA (Vite/React)  │ ◀─────────────────────▶ │  FastAPI backend   │
│  Dashboard, kill   │                          │  Strategy loop,    │
│  switch, P&L       │                          │  risk, OANDA conn  │
└────────────────────┘                          └────────┬───────────┘
                                                         │ v20 REST + Stream
                                                         ▼
                                                 ┌──────────────┐
                                                 │    OANDA     │
                                                 └──────────────┘
```

The **backend** is the trading engine — it runs continuously and is the only
thing that talks to OANDA. The **frontend** is a viewer/controller; closing
the browser does not stop trading.

## Strategy

EUR/USD M5 mean reversion during the London-NY overlap (12:00–16:00 UTC),
filtered by ADX (no-trend regime) and sized by ATR. See
[`backend/app/strategy.py`](backend/app/strategy.py) for the full logic.

Risk controls (all hard-enforced):

- Risk per trade: 0.5% of equity
- Max 4 trades / day, 1 concurrent position
- Daily loss kill switch: -2%
- Max drawdown stop: -5%
- 4 consecutive losses → 24h pause
- `TRADING_ENABLED=false` master flag (orders are simulated unless true)

## First-time setup

### 1. Get a fresh OANDA API token

If you ever pasted an old token anywhere (chat, email, screenshot), revoke
it now at <https://www.oanda.com/account/manage-api-tokens> and generate a
new one.

### 2. Configure `.env`

```bash
cd ~/Documents/Trading/FXTrader
cp .env.example .env
# open .env in any editor, paste your new OANDA_API_KEY
open -e .env
```

### 3. Install backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 4. Install frontend

```bash
cd ../frontend
npm install
```

## Running

### Backtest (no API orders, uses historical data)

```bash
cd backend
source .venv/bin/activate
python -m scripts.run_backtest --days 365
```

Results are written to `backend/data/backtest_results/` and printed.

### Live (demo) trading

Two terminals:

```bash
# terminal 1 - backend
cd backend && source .venv/bin/activate
python -m app.main

# terminal 2 - frontend
cd frontend && npm run dev
```

Open <http://localhost:5179>. Strategy is paused on boot — flip the
`TRADING_ENABLED` toggle in the UI (or set the env var to `true`) to start.

## Promoting to live

**Do not do this until the demo account shows a positive equity curve over
at least 4 weeks of real demo trading.** Edit `.env`:

```
OANDA_ACCOUNT_ID=001-003-21383094-002
OANDA_ENV=live
```

Restart the backend.

## Safety notes

- The kill switch in the UI calls `POST /api/kill` and immediately closes
  all open positions and sets `TRADING_ENABLED=false` in memory.
- The daily-loss and drawdown limits trip automatically and cannot be
  reset without a manual restart.
- All trades are logged to `backend/data/trades.db` (SQLite).
