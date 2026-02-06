# Bitget Short Bot — Project Context

## Overview
This is an automated futures trading bot for Bitget exchange. It opens **short positions only** on USDT perpetual futures. The goal is small, frequent profits (~5% per trade) with strict risk management.

## Trading Strategy

### Coin Selection (runs every cycle)
1. Fetch all USDT perpetual futures pairs from Bitget (~200-300 pairs)
2. **Liquidity filter**: keep only pairs with 24h volume > $5M
3. **Volatility filter**: remove pairs with daily ATR(14) > 15%
4. Remaining pool: ~30-50 pairs

### Entry Signals (minimum 3 of 4 required)
- **RSI(14) > 70** — overbought condition
- **EMA(9) crosses below EMA(21)** — bearish crossover
- **MACD line crosses below signal line** — bearish momentum
- **Funding rate > +0.01%** — market overloaded with longs

### Timeframe
- Default: 15-minute candles (configurable to 1h)
- Bot runs main cycle every 15 minutes

### Position Sizing
- Max simultaneous positions: 5
- Each position: total_balance / 5
- Leverage: 10x (configurable)
- Margin mode: Cross

### Stop-Loss (Variant 3: Hybrid ATR)
- Calculate: 1.5 × ATR(14) as percentage
- Stop-loss = max(2%, 1.5 × ATR)
- This ensures stop is never tighter than 2%, but widens for volatile coins

### Take-Profit (Hybrid ATR)
- Calculate: 2.5 × ATR(14) as percentage
- Take-profit = max(5%, 2.5 × ATR)
- Ensures minimum 5% target, wider for volatile coins

### Trailing Stop
- When position profit reaches +3%: move stop to breakeven (entry price)
- When profit reaches +4%: move stop to +2%
- Continue trailing with 2% distance

## Safety Mechanisms (checked BEFORE every trade)

### 1. Daily Loss Limit
- If daily P&L drops below -5% of starting balance → stop trading until next day (00:00 UTC reset)

### 2. Bull Market Protection
- If BTC/USDT price change over 24h > +5% → no new shorts

### 3. News Calendar
- No new positions 30 minutes before or after major events
- Events: FOMC decisions, CPI releases, Non-Farm Payrolls
- Calendar stored in `config.json`, updated manually or via API

### 4. Position Limit
- Max 5 open positions at any time

### Pre-trade checklist (ALL must pass):
1. ✅ Daily loss < 5%
2. ✅ BTC 24h change < +5%
3. ✅ Not in news blackout window
4. ✅ Open positions < 5
5. ✅ Signal has 3+ indicators confirming

## Restart Safety
- Bot saves state to `state.json` every cycle
- On startup: reads state file, syncs with Bitget open positions
- Duplicate protection: won't open second position on same pair
- Trailing stop recovery: recalculates trailing levels on restart

## Project Structure
```
bitget-short-bot/
├── CLAUDE.md          # This file — project context
├── README.md          # Setup and usage instructions
├── config.json        # API keys, parameters, news calendar
├── requirements.txt   # Python dependencies
├── bot.py             # Main bot entry point and loop
├── exchange.py        # Bitget API wrapper
├── strategy.py        # Indicators, signals, filters
├── risk.py            # Safety checks, position sizing, SL/TP
├── state.py           # State persistence and recovery
└── logs/              # Trade logs directory
```

## Tech Stack
- Python 3.10+
- `ccxt` library for Bitget API
- `pandas` + `ta` for technical indicators
- No external databases — JSON file for state

## Configuration (config.json)
- `api_key`, `api_secret`, `passphrase` — Bitget API credentials
- `leverage` — default 10
- `max_positions` — default 5
- `timeframe` — default "15m"
- `min_volume_usd` — default 5000000
- `max_atr_pct` — default 15.0
- `min_stop_pct` — default 2.0
- `min_tp_pct` — default 5.0
- `daily_loss_limit_pct` — default 5.0
- `btc_bull_limit_pct` — default 5.0
- `cycle_minutes` — default 15
- `demo` — default true (use Bitget demo/testnet)

## Key Commands
- `python bot.py` — start the bot
- `python bot.py --dry-run` — run without placing real orders (logging only)
- Logs are written to `logs/` directory with daily rotation

## Development Notes
- Always test on Bitget demo account first (set `demo: true` in config)
- The bot is designed to be restarted safely at any time
- All API calls include error handling and retry logic
- Rate limiting: respect Bitget's 20 requests/second limit
