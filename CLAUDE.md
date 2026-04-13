# Bitget Short Bot — Project Context

## Overview
Automated futures trading bot for Bitget exchange. Opens **short positions only** on USDT perpetual futures. Uses composite downtrend scoring to rank pairs and select the best short candidate.

## Trading Strategy

### Coin Selection (runs every cycle)
1. Fetch all USDT perpetual futures pairs from Bitget (~300 pairs)
2. Fetch all tickers in one API call (~700 tickers)
3. No volume filter — all pairs analyzed, volume shown in dashboard
4. **Volatility filter**: remove pairs with ATR(14) > 15% (open positions exempt)
5. Analyze remaining pairs (~480) with composite downtrend score
6. Parallel scanning with ThreadPoolExecutor (7 threads, configurable)

### Composite Downtrend Score
Single score 0-100 ranking how strongly a pair is trending down:

**4 components (normalized 0-100 across all pairs):**
- **ADX directional** (30%): `(DI_minus - DI_plus) * ADX/100` — trend strength + direction
- **Slope** (25%): linear regression slope as %/candle (period=150, 37.5h) — price descent speed
- **ROC weighted** (25%): `ROC(5)*0.4 + ROC(14)*0.35 + ROC(150)*0.25` — multi-period momentum
- **EMA gap** (20%): `(EMA21 - EMA9) / price * 100` — bearish spread

**Quality multipliers:**
- **R²**: coefficient of determination of linear regression (period=150, 37.5h). Penalizes flash crashes (single candle spikes). Zero for uptrends (slope >= 0).
- **Drop Concentration (DC)**: fraction of total drop in top-3 biggest candles (period=150). Only applies when total drop > 5% on 15m. Penalizes step-drops (TAO pattern: flat→dump→flat).
- **DC 1h**: same metric on hourly candles with 3% threshold. Catches flash crashes visible on 1h (COST pattern: sudden 3% drop in 2-3 candles).

**Formula:** `score = raw_score * effective_r2 * dc_penalty * quality_1h * dc_1h_penalty * adx_penalty`

**ADX penalty:** if ADX dir < 0 (bulls winning on 15m) → score killed. Prevents shorting pairs already reversing upward (WET case).

**Trade eligibility (visual indicator):** green border in scan table if ALL:
- `risk_score <= 3`, `slope < -0.01`, `R² >= 0.3`, no open position
- Configurable: `min_slope_threshold` (-0.01), `min_r2_threshold` (0.3)
- Visual only — trading criteria unchanged (for now)

### Entry Criteria (auto-trade)
- Exclude already open positions, then take top N by score (`auto_top_n`, default 10)
- First one with `risk_score <= max_risk_score` (default 3)
- All safety checks passed (BTC trend, position count)
- ROI auto-adjusted: `actual_roi = max(auto_tp_roi_pct, min_roi_for_pair)`

### Min ROI (per pair)
```
min_roi = (2 * taker_rate + 2 * tick / price) * leverage * 100
```
Accounts for round-trip fees + 2 ticks close slippage.
If `auto_tp_roi_pct < min_roi` → ROI auto-increased to min_roi.
Prevents ALGO-type losses where few ticks TP + slippage = net loss.

### Risk Score (0-10)
Based on **days since price was last above liquidation level** (from 90 daily candles):

**Price was above liq:**
- 1-3 days ago → 10 (extreme risk)
- 4-14 days → 5
- 15-30 days → 4
- 31-60 days → 3
- 61-90 days → 2

**Price never above liq (scaled by available history):**
- 60-90 days checked → 1 (solid history, safe)
- 30-59 days checked → 2
- 14-29 days checked → 4
- <14 days checked → 8 (too little data, risky)
- No data → 10

Uses approximate liquidation price: `liq = (free_balance + notional) / (contracts * (1 + keepMarginRate))`
`keepMarginRate` varies per pair (0.4% BTC — 5% PHB), fetched from leverage tiers.

### Timeframe
- 15-minute candles (configurable)
- Bot runs main cycle every 5 minutes (configurable)

### Position Sizing
- Max simultaneous positions: 3 (configurable via `max_positions`)
- Each position: `balance * position_size_pct / max_positions`
- Leverage: 10x (configurable)
- Margin mode: Cross

### Take-Profit (two-API-call flow)
Both auto and manual trades use the same algorithm:
1. `open_short_no_tp()` — market order without TP → get real fill price
2. Calculate TP from **fill price** (not ticker): `fill * (1 - ROI/leverage/100)`
3. `set_take_profit()` via `PlaceTpslOrder` API → 3 retries on failure
4. If all retries fail → save to `state["pending_tp"]` → bot recovers next cycle

- **Auto trades**: `auto_tp_roi_pct` (default 3%)
- **Manual trades**: user selects TP ROI (1/2/3/4/5/10%)
- **Tick safety**: if TP rounds to fill price, forced to `fill - tick_size`

### Trailing Stop
- When position profit reaches trailing_start_pct: move stop to breakeven
- Continue trailing with trailing_distance_pct distance

## Safety Mechanisms

### Pre-trade checklist (ALL must pass):
1. BTC 24h change < +5% (bull market protection)
2. Open positions < max_positions (default 3)
3. risk_score <= max_risk_score (default 3, auto-trade only)

### Tick Size Protection
- Cheap coins with coarse tick size may have TP = fill after rounding
- TP forced to `fill - 1 tick` if this happens
- Dashboard shows ⚠ warning icon for pairs with < 3 ticks of TP distance

### Pending TP Recovery
- If TP fails to set (network error, etc.), saved to `state["pending_tp"]`
- Each bot cycle checks pending_tp: position alive? TP already set? → retry or cleanup

## Fee Structure
- Taker rate: 0.1% of notional (account-wide, not per-pair)
- Open fee: `margin * leverage * 0.001`
- Close fee: `close_notional * 0.001`
- Funding fee: every 8h, from `contract_settle_fee` bills (`totalFee` on position)
- Round-trip at 10x: ~2% ROI breakeven
- Dashboard shows full P&L breakdown before opening manual trades
- Recent Shorts fee popup: opening fee, closing fee, funding fee, closing profit, position PnL
- Bitget reports gross PnL (without fees) — real net = PnL + funding - fees

## Architecture

### Project Structure
```
bitget-short-bot/
├── CLAUDE.md          # This file — project context
├── config.json        # API keys, parameters (gitignored)
├── config.example.json
├── requirements.txt   # Python dependencies
├── Dockerfile
├── docker-compose.yml # 3 services: bot, api, nginx
├── bot.py             # Main bot entry point and cycle loop
├── exchange.py        # Bitget API wrapper (ccxt) with retry
├── strategy.py        # Composite downtrend scoring, indicators
├── risk.py            # Safety checks, position sizing, trailing stops
├── positions.py       # Shared position data builder (report + API)
├── state.py           # State persistence and recovery
├── report.py          # HTML dashboard generator
├── charts.py          # Chart generation (line charts with gradient)
├── api_server.py      # Flask API for manual trading + data
├── cycle_status.py    # Cycle progress tracker (JSON for frontend polling)
├── version.txt        # Auto-generated by pre-commit hook
├── output/            # Generated HTML + chart PNGs + cycle_status.json
└── logs/              # Trade logs with daily rotation
```

### Docker Services
- **bot**: Main trading bot, runs cycles
- **api**: Flask server on port 8432, manual trading + data endpoints
- **nginx**: Serves `output/` on port 8080 (dashboard)

### API Endpoints
- `POST /api/short` — Open manual short (params: symbol, bet_pct, tp_roi_pct)
- `GET /api/positions` — Live position data with days_since_liq
- `GET /api/shorts` — Open positions + recent closed shorts with fee breakdown
- `GET /api/candles` — Historical candles with pagination (params: symbol, tf, days)
- `GET /api/funding-history` — Historical funding rates (params: symbol, days)
- `POST /api/backtest-chart` — Generate backtest chart PNG from candles + trades data

### Cycle Status (output/cycle_status.json)
Bot writes progress to `cycle_status.json` during each cycle:
- **Phases**: Loading market → Loading coins → Rendering → Analyzing risk → Ready
- **Progress**: 0-100% per phase, updated per symbol (thread-safe)
- Frontend polls this file via AJAX (2s during cycle, 10s idle)
- Page auto-reloads when new Ready detected (updated_at changed)

### Dashboard Features
- **Cards**: Balance → Active Trades → Unrealized PnL → Wallet Balance → Est. Balance at TP (with % of wallet) → Start Balance → Total Trades → Total PnL → TP/SL/Auto Bet Size
- **Balance note**: Bitget `total` = wallet + unrealized PnL. `free = total - margin`. To get wallet: `total - unrealized`
- **Est. Balance at TP**: `wallet + sum(gross_at_tp - close_fee)` per position. Open fee/funding already in wallet.
- **Cycle status**: live progress bar + phase name (replaces countdown timer)
- Auto-refresh Open Positions and Recent Shorts on page load
- Manual refresh buttons with spinning icon
- Market Scan: columns Symbol, Score, Risk, Min ROI, Last@Liq, Est.Profit, then ADX/Slope/ROC/EMA/R²/DC/RSI/ATR/Vol/Liq/Components
- Market Scan mobile: only Symbol, Score, Est.Profit visible
- Est.Profit per pair: simulated trade with auto params (margin, max(roi, min_roi))
- Min ROI column: yellow if > 3% (tick-sensitive pairs)
- Component bars visualization (ADX/Slope/ROC/EMA)
- ⚠ tick precision warning icon with rich tooltip for cheap coins
- Chart preview: hover on desktop, long press (500ms) on mobile with vibration
- Touch: tap opens modal, long press shows preview, drag switches rows
- Position modal with charts (1m/15m/1h)
- Trade modal with bet size, TP ROI selectors, full P&L breakdown with formulas
- Toast notifications on successful trade (shows fill price, TP, adjusted warning)
- Open Positions: PnL (after Symbol), Est.TP profit, ROI, progress bar, Fee, Fund, Last@Liq
- Open Positions: chart preview on hover (same as scan table, chart URLs cached on page load for AJAX refresh)
- Charts: yellow entry marker (dot + dashed line) for open positions, only if within visible range
- Trade modal: min ROI warning if selected ROI < breakeven, auto-adds min option to combobox
- **Backtest emulation**: chain short trades on historical candles
  - UI: Emulate button in modal with period (1d/1w/1m/2m/3m/6m/12m), timeframe (1m/15m/1h, auto 15m for >30d), balance, bet %, ROI
  - JS engine: opens short at close, closes at TP (low ≤ tp), checks liquidation (cross margin: loss > balance)
  - Accounts for open/close fees + historical funding rates
  - Shows trade-by-trade results with entry/exit/net/balance/duration
  - Chart with green (TP) / red (loss/liq) markers generated server-side
  - Liquidation time shown from start of emulation
- Recent Shorts with entry/exit prices, fees, net profit, duration, balance delta
- Fee breakdown popup: closing profit, funding fee, opening fee, closing fee, position PnL
- Color rules: positive=blue +, negative=red -, zero=grey
- Last Updated converted to browser local time

## Tech Stack
- Python 3.12
- `ccxt` library for Bitget API (with retry on 429)
- `pandas` + `ta` + `numpy` for technical indicators
- `matplotlib` for chart generation
- `flask` for API server
- Docker + nginx for deployment
- No external databases — JSON file for state

## Configuration (config.json)
- `api_key`, `api_secret`, `passphrase` — Bitget API credentials
- `leverage` — default 10
- `max_positions` — default 3
- `position_size_pct` — default 20
- `timeframe` — default "15m"
- `max_atr_pct` — default 15.0
- `auto_top_n` — default 3 (consider top N pairs for auto-trade)
- `max_risk_score` — default 3 (auto-trade risk filter)
- `auto_tp_roi_pct` — default 3.0 (TP ROI for auto trades)
- `btc_bull_limit_pct` — default 5.0
- `cycle_minutes` — default 5
- `scan_threads` — default 7 (parallel API workers)
- `charts_enabled` — default true
- `demo` — default true (use Bitget demo/testnet)

## Key Commands
- `python bot.py` — start the bot
- `python bot.py --dry-run` — run without placing real orders
- Logs are written to `logs/` directory with daily rotation

## Development Notes
- Always test on Bitget demo account first (set `demo: true` in config)
- The bot is designed to be restarted safely at any time
- All API calls include error handling and retry logic (3 retries on 429)
- `create_order` calls log full request and response for debugging
- Rate limiting: respect Bitget's 20 requests/second limit
- Scan uses ThreadPoolExecutor for parallel OHLCV fetching (~7 threads)
- Charts reuse cached 15m candles from scan phase (150 candles fetched)
- Charts parallelized with ThreadPoolExecutor (5 threads)
- Charts generated for union of top-20 per each metric + open positions
- 90d daily candles fetched for chart symbols to calculate risk score
- Risk score for "never found" scales by checked days (<14d = risk 8, 60-90d = risk 1)
- `days_since_liq` encoding: 0-999 = found X days ago, 1000+ = never (checked N-1000 days)
- API server caches Exchange instance (load_markets once)
- TP/SL fetched once during sync, not duplicated in position builder
- Cycle status: `output/cycle_status.json` written by CycleStatus (thread-safe with Lock)
- Frontend polls cycle_status.json for live progress (2s active, 10s idle)
- Responsive: mobile layout stacks panels vertically at ≤768px
- f-string gotcha: ternary inside format spec must be wrapped in nested f""
- JS in report.py: avoid unicode escapes, use named functions instead of IIFEs
- CSS specificity: `.close-sym.negative` needed to override `.close-sym { color }`
- Every time you finish task commit and push automatically
