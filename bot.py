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

from exchange import Exchange
from strategy import (
    candles_to_dataframe,
    calculate_atr,
    analyze_symbol,
    calculate_sl_tp,
    filter_by_volume,
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

    cycle_minutes = risk.config.get("cycle_minutes", 15)

    # ── Step 1: Get current balance ──
    current_balance = exchange.get_balance()
    if current_balance <= 0:
        logger.error("Balance is zero, skipping cycle")
        return

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

    if not all_safe:
        logger.info("Safety check failed, skipping trade search")
        logger.info(get_stats(state))
        save_state(state)
        cycle_info = {"checks": reasons, "outcome": "Safety check failed, skipping trade search", "cycle_minutes": cycle_minutes}
        generate_report(state, exchange_positions, current_balance, exchange, cycle_info)
        return

    # ── Step 5: Scan market ──
    config = risk.config
    timeframe = config.get("timeframe", "15m")
    min_volume = config.get("min_volume_usd", 5_000_000)
    max_atr = config.get("max_atr_pct", 15.0)
    min_signals = config.get("min_signals", 3)

    symbols = exchange.get_usdt_futures_symbols()

    # Filter by volume using tickers
    logger.info("Fetching tickers for volume filter...")
    try:
        tickers = exchange.exchange.fetch_tickers(symbols[:100])  # Batch fetch
        liquid_symbols = filter_by_volume(tickers, min_volume)
        logger.info(
            f"Liquidity filter: {len(liquid_symbols)} pairs with >${min_volume/1e6:.0f}M volume"
        )
    except Exception as e:
        logger.error(f"Error fetching tickers: {e}")
        cycle_info = {"checks": reasons, "outcome": f"Error fetching tickers: {e}", "cycle_minutes": cycle_minutes}
        generate_report(state, exchange_positions, current_balance, exchange, cycle_info)
        return

    # ── Step 6: Analyze each symbol ──
    candidates = []

    for symbol in liquid_symbols:
        # Skip if we already have a position
        if symbol in state["positions"]:
            continue

        candles = exchange.get_ohlcv(symbol, timeframe, limit=100)
        df = candles_to_dataframe(candles)
        if df is None:
            continue

        # ATR volatility filter
        atr_pct = calculate_atr(df)
        if atr_pct > max_atr:
            continue

        # Get funding rate
        funding_rate = exchange.get_funding_rate(symbol)

        # Analyze signals
        analysis = analyze_symbol(df, funding_rate, config)

        if analysis["signal_count"] >= min_signals:
            candidates.append(
                {
                    "symbol": symbol,
                    "analysis": analysis,
                    "atr_pct": atr_pct,
                }
            )
            logger.info(
                f"  🎯 {symbol}: {analysis['signal_count']} signals "
                f"({', '.join(analysis['signals'])})"
            )
            for detail in analysis["details"]:
                logger.info(f"      {detail}")

        # Rate limiting: small delay between API calls
        time.sleep(0.1)

    if not candidates:
        logger.info("No trade signals found this cycle")
        logger.info(get_stats(state))
        save_state(state)
        cycle_info = {"checks": reasons, "outcome": "No trade signals found this cycle", "cycle_minutes": cycle_minutes}
        generate_report(state, exchange_positions, current_balance, exchange, cycle_info)
        return

    # ── Step 7: Select best candidate ──
    # Sort by RSI (highest = most overbought = best short candidate)
    candidates.sort(key=lambda c: c["analysis"]["rsi"], reverse=True)
    best = candidates[0]

    symbol = best["symbol"]
    atr_pct = best["atr_pct"]
    logger.info(f"Best candidate: {symbol} (RSI={best['analysis']['rsi']:.1f})")

    # ── Step 8: Calculate position size ──
    margin = risk.calculate_position_size(current_balance, open_short_count)
    if margin <= 0:
        logger.warning("Position size is zero, skipping")
        save_state(state)
        cycle_info = {"checks": reasons, "outcome": "Position size is zero, skipping", "cycle_minutes": cycle_minutes}
        generate_report(state, exchange_positions, current_balance, exchange, cycle_info)
        return

    # ── Step 9: Calculate SL/TP ──
    ticker = exchange.get_ticker(symbol)
    if not ticker:
        save_state(state)
        cycle_info = {"checks": reasons, "outcome": f"Could not fetch ticker for {symbol}", "cycle_minutes": cycle_minutes}
        generate_report(state, exchange_positions, current_balance, exchange, cycle_info)
        return

    entry_price = ticker["last"]
    sl_price, tp_price = calculate_sl_tp(entry_price, atr_pct, config)

    sl_pct = abs(sl_price - entry_price) / entry_price * 100
    tp_pct = abs(entry_price - tp_price) / entry_price * 100

    logger.info(
        f"Trade plan: SHORT {symbol} @ {entry_price} | "
        f"SL={sl_price} ({sl_pct:.1f}%) | TP={tp_price} ({tp_pct:.1f}%) | "
        f"Margin={margin:.2f} USDT"
    )

    # ── Step 10: Execute trade ──
    if dry_run:
        logger.info("DRY RUN — order not placed")
        position = {
            "order_id": "dry-run",
            "symbol": symbol,
            "entry_price": entry_price,
            "amount": 0,
            "margin_usdt": margin,
            "stop_loss": sl_price,
            "take_profit": tp_price,
            "timestamp": time.time(),
        }
    else:
        position = exchange.open_short(symbol, margin, sl_price, tp_price)

    if position:
        add_position(state, position)
        outcome = f"Opened SHORT {symbol}"
        logger.info(f"✅ Short opened: {symbol}")
    else:
        outcome = f"Failed to open short for {symbol}"
        logger.error(outcome)

    logger.info(get_stats(state))
    save_state(state)
    cycle_info = {"checks": reasons, "outcome": outcome, "cycle_minutes": cycle_minutes}
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
def main():
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
