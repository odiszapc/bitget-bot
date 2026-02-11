"""
State persistence module: saves and loads bot state to/from JSON.
Ensures safe restarts.
"""

import json
import os
import time
import logging
logger = logging.getLogger(__name__)

STATE_FILE = "state.json"


def get_default_state() -> dict:
    """Return a fresh default state."""
    return {
        "start_balance": 0.0,
        "positions": {},  # symbol -> position info
        "total_trades": 0,
        "last_cycle_time": 0,
    }


def load_state() -> dict:
    """Load state from file, or return default state."""
    if not os.path.exists(STATE_FILE):
        logger.info("No state file found, starting fresh")
        return get_default_state()

    try:
        with open(STATE_FILE, "r") as f:
            state = json.load(f)

        # Ensure all required keys exist (e.g. state.json was manually created as {})
        defaults = get_default_state()
        for key, value in defaults.items():
            if key not in state:
                state[key] = value

        logger.info("State loaded from file")
        return state

    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Error loading state file: {e}")
        return get_default_state()


def save_state(state: dict):
    """Save state to file."""
    try:
        state["last_cycle_time"] = time.time()
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
        logger.debug("State saved")
    except IOError as e:
        logger.error(f"Error saving state: {e}")


def add_position(state: dict, position: dict):
    """Add a new position to state tracking."""
    symbol = position["symbol"]
    state["positions"][symbol] = {
        "order_id": position.get("order_id"),
        "entry_price": position["entry_price"],
        "amount": position["amount"],
        "margin_usdt": position["margin_usdt"],
        "stop_loss": position["stop_loss"],
        "take_profit": position["take_profit"],
        "current_sl": position["stop_loss"],  # Track current SL for trailing
        "opened_at": position.get("timestamp", time.time()),
    }
    state["total_trades"] += 1
    save_state(state)
    logger.info(f"Position added to state: {symbol}")


def remove_position(state: dict, symbol: str, pnl: float = 0.0):
    """Remove a closed position from state."""
    if symbol in state["positions"]:
        del state["positions"][symbol]
        save_state(state)
        logger.info(f"Position removed: {symbol}")


def sync_positions_with_exchange(state: dict, exchange_positions: list[dict], exchange=None):
    """
    Sync state with actual exchange positions.
    Removes positions from state that no longer exist on exchange.
    If exchange is provided, fetches live TP/SL for new and existing positions.
    """
    exchange_symbols = {pos["symbol"] for pos in exchange_positions if pos["side"] == "short"}
    state_symbols = set(state["positions"].keys())

    # Positions closed while bot was offline
    closed = state_symbols - exchange_symbols
    for symbol in closed:
        logger.info(f"Position {symbol} was closed while bot was offline")
        remove_position(state, symbol, pnl=0.0)  # PnL unknown

    # Build lookup: symbol -> exchange position data
    exch_lookup = {}
    for pos in exchange_positions:
        if pos["side"] == "short":
            exch_lookup[pos["symbol"]] = pos

    # Positions on exchange not in state (manual trades?)
    new = exchange_symbols - state_symbols
    for symbol in new:
        pos = exch_lookup.get(symbol)
        if pos:
            logger.info(f"Found untracked position: {symbol}, adding to state")
            # Try position fields first, then fall back to plan orders
            tp_price = pos.get("take_profit", 0) or 0
            sl_price = pos.get("stop_loss", 0) or 0
            if exchange and (not tp_price or not sl_price):
                tp_sl = exchange.get_tp_sl_for_symbol(symbol)
                if not tp_price and tp_sl["tp"]:
                    tp_price = float(tp_sl["tp"])
                if not sl_price and tp_sl["sl"]:
                    sl_price = float(tp_sl["sl"])
            state["positions"][symbol] = {
                "order_id": "unknown",
                "entry_price": pos["entry_price"],
                "amount": pos["contracts"],
                "margin_usdt": pos.get("margin", 0),
                "stop_loss": sl_price,
                "take_profit": tp_price,
                "current_sl": sl_price,
                "opened_at": time.time(),
            }

    # Update TP/SL for existing positions that have zeros
    for symbol in exchange_symbols & state_symbols:
        tracked = state["positions"][symbol]
        if not tracked.get("take_profit") or not tracked.get("stop_loss"):
            # Try position fields first
            pos = exch_lookup.get(symbol)
            if pos:
                if not tracked.get("take_profit") and pos.get("take_profit"):
                    tracked["take_profit"] = pos["take_profit"]
                if not tracked.get("stop_loss") and pos.get("stop_loss"):
                    tracked["stop_loss"] = pos["stop_loss"]
                    if not tracked.get("current_sl"):
                        tracked["current_sl"] = pos["stop_loss"]
            # Fall back to plan orders
            if exchange and (not tracked.get("take_profit") or not tracked.get("stop_loss")):
                tp_sl = exchange.get_tp_sl_for_symbol(symbol)
                if tp_sl["tp"] and not tracked.get("take_profit"):
                    tracked["take_profit"] = float(tp_sl["tp"])
                if tp_sl["sl"] and not tracked.get("stop_loss"):
                    tracked["stop_loss"] = float(tp_sl["sl"])
                    if not tracked.get("current_sl"):
                        tracked["current_sl"] = float(tp_sl["sl"])

    save_state(state)


def get_stats(state: dict) -> str:
    """Get a formatted stats string."""
    total = state.get("total_trades", 0)
    return f"📊 Stats: {total} trades"
