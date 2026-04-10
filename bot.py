"""
Bitget Short Bot — Main entry point.

Automated futures trading bot that opens short positions
with strict risk management.

Usage:
    python bot.py              # Normal mode
    python bot.py --dry-run    # Logging only, no real orders
"""

import json
import sys
import time
import logging
import os
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

from exchange import Exchange
from strategy import (
    candles_to_dataframe,
    calculate_atr,
    analyze_symbol,
    normalize_downtrend_scores,
    calculate_sl_tp,
)
from risk import RiskManager
from state import (
    load_state,
    save_state,
    add_position,
    remove_position,
    sync_positions_with_exchange,
    get_stats,
)
from report import generate_report
from charts import generate_charts_for_symbols

# ── Logging setup ───────────────────────────────────────────
os.makedirs("logs", exist_ok=True)

log_filename = f"logs/bot_{datetime.now().strftime('%Y%m%d')}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(log_filename),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("bot")


# ── Load config ─────────────────────────────────────────────
def load_config() -> dict:
    try:
        with open("config.json", "r") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error("config.json not found! Copy config.json and fill in your API keys.")
        sys.exit(1)


# ── Main cycle ──────────────────────────────────────────────
def run_cycle(exchange: Exchange, risk: RiskManager, state: dict, dry_run: bool):
    """Run one complete trading cycle."""
    logger.info("=" * 60)
    logger.info("Starting new cycle")

    # Reload state from disk to pick up changes made by api_server
    fresh = load_state()
    state.clear()
    state.update(fresh)

    cycle_start = time.time()
    exchange.reset_api_counter()
    cycle_minutes = risk.config.get("cycle_minutes", 15)

    # ── Step 1: Get current balance ──
    current_balance = exchange.get_balance()
    if current_balance <= 0:
        # Retry once — connection may have gone stale
        logger.warning("Balance fetch failed or zero, reloading markets and retrying...")
        exchange.load_markets()
        current_balance = exchange.get_balance()

    balance_ok = current_balance > 0

    if not balance_ok:
        logger.warning("Balance is zero — will scan market but skip trading")
    else:
        if state["start_balance"] <= 0:
            state["start_balance"] = current_balance
            logger.info(f"Set start balance: {current_balance:.2f} USDT")

    logger.info(f"Current balance: {current_balance:.2f} USDT")

    # ── Step 2: Sync positions with exchange ──
    exchange_positions = exchange.get_open_positions()
    sync_positions_with_exchange(state, exchange_positions, exchange)

    open_short_count = len(
        [p for p in exchange_positions if p["side"] == "short"]
    )

    # ── Step 2b: Recover pending TP ──
    pending_tp = state.get("pending_tp", {})
    exchange_symbols = {p["symbol"] for p in exchange_positions if p["side"] == "short"}
    for sym, info in list(pending_tp.items()):
        if sym not in exchange_symbols:
            logger.info(f"Pending TP: {sym} position closed, removing")
            del pending_tp[sym]
            continue
        tp_sl = exchange.get_tp_sl_for_symbol(sym)
        if tp_sl.get("tp"):
            logger.info(f"Pending TP: {sym} TP already set, removing")
            del pending_tp[sym]
            continue
        logger.info(f"Pending TP: setting TP for {sym} at {info['tp_price']}")
        if exchange.set_take_profit(sym, info["tp_price"], info["amount"]):
            del pending_tp[sym]
            logger.info(f"Pending TP: {sym} TP set successfully")
        else:
            logger.error(f"Pending TP: {sym} TP still failed, will retry next cycle")
    if pending_tp != state.get("pending_tp", {}):
        save_state(state)

    # ── Step 3: Manage trailing stops ──
    manage_trailing_stops(exchange, state, exchange_positions)

    # ── Step 4: Safety checks ──
    btc_change = exchange.get_btc_24h_change()

    all_safe, reasons = risk.run_all_checks(
        start_balance=state["start_balance"],
        current_balance=current_balance,
        btc_24h_change=btc_change,
        open_positions=open_short_count,
    )

    for reason in reasons:
        logger.info(f"  {reason}")

    if not balance_ok:
        all_safe = False
        reasons.append("❌ Balance is zero — trading disabled")

    if not all_safe:
        logger.info("Safety check failed, skipping trade execution")

    # ── Step 5: Scan market (always runs for analysis) ──
    config = risk.config
    timeframe = config.get("timeframe", "15m")
    min_volume = config.get("min_volume_usd", 5_000_000)
    max_atr = config.get("max_atr_pct", 15.0)
    leverage = config.get("leverage", 10)
    active_strategy = "composite"

    scan_results = []
    symbols = exchange.get_usdt_futures_symbols()

    # Ensure symbols with open positions are always included
    open_position_symbols = set(state.get("positions", {}).keys())

    # Fetch all tickers for volume data
    logger.info("Fetching tickers...")
    try:
        tickers = exchange.get_tickers(symbols)  # Fetch all at once
        # No volume filter — all pairs go through, volume shown in report
        liquid_symbols = list(tickers.keys())
        # Ensure open position symbols are included
        for ops in open_position_symbols:
            if ops not in liquid_symbols:
                liquid_symbols.append(ops)
        logger.info(f"Total pairs for analysis: {len(liquid_symbols)}")
    except Exception as e:
        logger.error(f"Error fetching tickers: {e}")
        logger.info(get_stats(state))
        api_calls = exchange.api_call_count
        rps = api_calls / (cycle_minutes * 60)
        logger.info(f"API calls this cycle: {api_calls} ({rps:.2f}/sec, limit 20/sec)")
        save_state(state)
        cycle_info = {"checks": reasons, "outcome": f"Error fetching tickers: {e}", "cycle_minutes": cycle_minutes, "scan_results": [], "active_strategy": active_strategy, "api_calls": api_calls, "config": config, "chart_map": {}, "recent_closes": []}
        generate_report(state, exchange_positions, current_balance, exchange, cycle_info)
        return

    # ── Step 6: Analyze each symbol (parallel) ──
    total_symbols = len(liquid_symbols)
    skipped_atr = 0
    skipped_data = 0
    completed = 0

    def _analyze_one(symbol):
        """Fetch candles and analyze one symbol. Returns (result_dict, status)."""
        short_name = symbol.split("/")[0].split(":")[0]
        is_open = symbol in open_position_symbols

        candles = exchange.get_ohlcv(symbol, timeframe, limit=150)  # 150 for chart reuse
        df = candles_to_dataframe(candles)
        if df is None:
            return None, "no_data", short_name

        atr_pct = calculate_atr(df)
        if atr_pct > max_atr and not is_open:
            return None, f"atr_{atr_pct:.1f}", short_name

        analysis = analyze_symbol(df, config)

        ticker_data = tickers.get(symbol, {})
        quote_volume = float(ticker_data.get("quoteVolume", 0) or 0)
        tick_size = exchange.get_tick_size(symbol)
        last_price = float(ticker_data.get("last", 0) or 0) or df["close"].iloc[-1]

        # Calculate TP ticks at default ROI (3%) for warning
        default_roi = 3.0
        tp_distance = last_price * (default_roi / leverage / 100)
        tp_ticks = tp_distance / tick_size if tick_size > 0 else 999

        return {
            "symbol": symbol,
            "volume_24h": quote_volume,
            "funding_rate": 0,
            "tick_size": tick_size,
            "tp_ticks": round(tp_ticks, 1),
            "_candles_15m": candles,  # cached for chart generation
            **analysis,
        }, "ok", short_name

    workers = config.get("scan_threads", 7)
    logger.info(f"Scanning {total_symbols} pairs ({workers} threads)...")

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_analyze_one, sym): sym for sym in liquid_symbols}
        for future in as_completed(futures):
            completed += 1
            result, status, short_name = future.result()
            if status == "no_data":
                skipped_data += 1
            elif status.startswith("atr_"):
                skipped_atr += 1
            else:
                scan_results.append(result)
            if completed % 50 == 0:
                logger.info(f"  {completed}/{total_symbols} done...")


    # ── Step 7: Normalize composite scores and sort ──
    logger.info(f"Analysis done: {len(scan_results)} passed, {skipped_data} no data, {skipped_atr} high ATR")
    normalize_downtrend_scores(scan_results)
    scan_results.sort(key=lambda c: c.get("downtrend_score", 0), reverse=True)

    min_score = config.get("min_downtrend_score", 70)
    logger.info(f"Ranked {len(scan_results)} pairs by downtrend score")
    for sr in scan_results:
        score = sr.get("downtrend_score", 0)
        marker = "🎯" if score >= min_score else "  "
        logger.info(
            f"  {marker} {sr['symbol'].split(':')[0]}: "
            f"score={score:.0f} R²={sr.get('r2',0):.2f} DC={sr.get('dc',0):.2f} RSI={sr['rsi']:.1f} ATR={sr['atr_pct']:.1f}% "
            f"ADXdir={sr.get('adx_dir',0):+.1f} slope={sr.get('slope',0):+.3f} "
            f"ROC={sr.get('roc_w',0):+.2f} EMA={sr.get('ema_gap',0):+.3f}"
        )

    # ── Step 7b: Generate charts for top pairs ──
    chart_map = {}
    if config.get("charts_enabled", False):
        logger.info("Generating charts...")
        try:
            chart_map = generate_charts_for_symbols(exchange, scan_results, open_position_symbols)
        except Exception as e:
            logger.error(f"Error generating charts: {e}")

    # ── Step 8: Execute trade (only if safe) ──
    candidates = [s for s in scan_results if s.get("downtrend_score", 0) >= min_score and s["symbol"] not in open_position_symbols]
    outcome = ""

    if not all_safe:
        outcome = "Safety check failed, trade execution skipped"
    elif not candidates:
        outcome = "No trade signals found this cycle"
    else:
        best = candidates[0]
        symbol = best["symbol"]
        atr_pct = best["atr_pct"]
        logger.info(f"Best candidate: {symbol} (RSI={best['rsi']:.1f})")

        margin = risk.calculate_position_size(current_balance, open_short_count)
        if margin <= 0:
            outcome = "Position size is zero, skipping"
        else:
            ticker = exchange.get_ticker(symbol)
            if not ticker:
                outcome = f"Could not fetch ticker for {symbol}"
            else:
                entry_price = ticker["last"]
                sl_price, tp_price = calculate_sl_tp(entry_price, atr_pct, config)

                tp_pct = abs(entry_price - tp_price) / entry_price * 100

                logger.info(
                    f"Trade plan: SHORT {symbol} @ {entry_price} | "
                    f"TP={tp_price} ({tp_pct:.1f}%) | no SL | "
                    f"Margin={margin:.2f} USDT"
                )

                if dry_run:
                    logger.info("DRY RUN — order not placed")
                    position = {
                        "order_id": "dry-run",
                        "symbol": symbol,
                        "entry_price": entry_price,
                        "amount": 0,
                        "margin_usdt": margin,
                        "stop_loss": 0,
                        "take_profit": tp_price,
                        "timestamp": time.time(),
                    }
                else:
                    position = exchange.open_short_tp_only(symbol, margin, tp_price)

                if position:
                    add_position(state, position)
                    outcome = f"Opened SHORT {symbol}"
                    logger.info(f"✅ Short opened: {symbol}")
                else:
                    outcome = f"Failed to open short for {symbol}"
                    logger.error(outcome)

    # ── Fetch recent close shorts for report ──
    recent_closes = []
    try:
        closes_limit = config.get('recent_closes_count', 12)
        recent_closes = exchange.get_closed_short_trades(limit=closes_limit)
    except Exception as e:
        logger.error(f"Error fetching closed trades: {e}")

    logger.info(get_stats(state))
    api_calls = exchange.api_call_count
    rps = api_calls / (cycle_minutes * 60)
    logger.info(f"API calls this cycle: {api_calls} ({rps:.2f}/sec, limit 20/sec)")
    save_state(state)
    cycle_duration = round(time.time() - cycle_start, 1)
    cycle_info = {
        "checks": reasons, "outcome": outcome, "cycle_minutes": cycle_minutes,
        "scan_results": scan_results, "active_strategy": active_strategy,
        "api_calls": api_calls, "config": config, "chart_map": chart_map,
        "recent_closes": recent_closes, "cycle_duration": cycle_duration,
    }
    generate_report(state, exchange_positions, current_balance, exchange, cycle_info)


def manage_trailing_stops(
    exchange: Exchange, state: dict, exchange_positions: list[dict]
):
    """Check and update trailing stops for all open positions."""
    for pos in exchange_positions:
        if pos["side"] != "short":
            continue

        symbol = pos["symbol"]
        if symbol not in state["positions"]:
            continue

        tracked = state["positions"][symbol]
        entry_price = tracked.get("entry_price", 0)
        current_sl = tracked.get("current_sl", 0)

        if entry_price <= 0 or current_sl <= 0:
            continue

        current_price = pos["entry_price"]  # Use exchange's latest
        ticker = exchange.get_ticker(symbol)
        if ticker:
            current_price = ticker["last"]

        from risk import RiskManager

        rm = RiskManager(exchange.config if hasattr(exchange, 'config') else {})
        new_sl = rm.calculate_trailing_stop(entry_price, current_price, current_sl)

        if new_sl is not None:
            logger.info(
                f"Trailing stop: {symbol} SL {current_sl} → {new_sl} "
                f"(price={current_price}, entry={entry_price})"
            )
            success = exchange.update_stop_loss(symbol, new_sl)
            if success:
                tracked["current_sl"] = new_sl
                save_state(state)


# ── Entry point ─────────────────────────────────────────────
def load_version() -> str:
    try:
        with open("version.txt", "r") as f:
            return f.read().strip()
    except FileNotFoundError:
        return "unknown"


def main():
    version = load_version()
    logger.info("═" * 56)
    logger.info(f"  Bitget Short Bot {version}")
    logger.info("═" * 56)

    dry_run = "--dry-run" in sys.argv

    if dry_run:
        logger.info("🔶 DRY RUN MODE — no real orders will be placed")
    else:
        logger.info("🔴 LIVE MODE — real orders will be placed!")

    config = load_config()
    exchange = Exchange(config)

    logger.info("Loading markets...")
    exchange.load_markets()

    risk = RiskManager(config)
    state = load_state()

    cycle_minutes = config.get("cycle_minutes", 15)
    logger.info(f"Bot started. Cycle every {cycle_minutes} minutes.")
    logger.info("Press Ctrl+C to stop.\n")

    while True:
        try:
            run_cycle(exchange, risk, state, dry_run)
        except KeyboardInterrupt:
            logger.info("Bot stopped by user")
            save_state(state)
            break
        except Exception as e:
            logger.error(f"Cycle error: {e}", exc_info=True)

        logger.info(f"Sleeping {cycle_minutes} minutes...\n")
        try:
            time.sleep(cycle_minutes * 60)
        except KeyboardInterrupt:
            logger.info("Bot stopped by user")
            save_state(state)
            break


if __name__ == "__main__":
    main()
