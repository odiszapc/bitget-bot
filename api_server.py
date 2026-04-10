"""
API server for manual trading actions.
Runs as a separate service, exposes REST endpoints.
"""

import json
import time
import logging
from flask import Flask, request, jsonify
from exchange import Exchange

from state import load_state, add_position, sync_positions_with_exchange
from positions import build_position_data

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Cached exchange instance — load_markets once, reuse across requests
_cached_exchange = None


def load_config() -> dict:
    with open("config.json", "r") as f:
        return json.load(f)


def _get_exchange():
    """Get or create cached exchange instance."""
    global _cached_exchange
    if _cached_exchange is None:
        config = load_config()
        _cached_exchange = Exchange(config)
        _cached_exchange.load_markets()
        logger.info("Exchange instance created and markets loaded")
    return _cached_exchange


def _get_synced_context():
    """Load config, exchange, sync state — shared setup for all read endpoints."""
    config = load_config()
    exchange = _get_exchange()
    exchange_positions = exchange.get_open_positions()
    state = load_state()
    sync_positions_with_exchange(state, exchange_positions, exchange)
    return config, exchange, exchange_positions, state


@app.route("/api/short", methods=["POST"])
def api_short():
    """Open a manual short position with TP only (no SL)."""
    try:
        data = request.get_json(force=True)
        symbol = data.get("symbol", "").strip()
        if not symbol:
            return jsonify({"ok": False, "error": "Missing symbol"}), 400

        bet_pct = data.get("bet_pct", 20)
        try:
            bet_pct = int(bet_pct)
        except (TypeError, ValueError):
            bet_pct = 20
        if bet_pct not in (5, 10, 20, 30, 50, 100):
            return jsonify({"ok": False, "error": f"Invalid bet_pct: {bet_pct}"}), 400

        tp_roi_pct = data.get("tp_roi_pct", 3)
        try:
            tp_roi_pct = float(tp_roi_pct)
        except (TypeError, ValueError):
            tp_roi_pct = 3.0
        if tp_roi_pct not in (1, 2, 3, 4, 5, 10):
            return jsonify({"ok": False, "error": f"Invalid tp_roi_pct: {tp_roi_pct}"}), 400

        config = load_config()
        exchange = Exchange(config)
        exchange.load_markets()

        # Check if already have position on this symbol
        open_positions = exchange.get_open_positions()
        for pos in open_positions:
            if pos["symbol"] == symbol:
                return jsonify({
                    "ok": False,
                    "error": f"Position already open for {symbol.split(':')[0]}"
                }), 400

        # Get balance — use selected percentage
        balance = exchange.get_balance()
        if balance <= 0:
            return jsonify({"ok": False, "error": "Zero balance"}), 400

        margin = round(balance * bet_pct / 100, 2)
        leverage = config.get("leverage", 10)
        tick_size = exchange.get_tick_size(symbol)

        # Step 1: Open short WITHOUT TP
        position = exchange.open_short_no_tp(symbol, margin)
        if not position:
            return jsonify({"ok": False, "error": "Exchange rejected the order"}), 500

        fill_price = position["entry_price"]

        # Step 2: Calculate TP from REAL fill price
        tp_price_pct = tp_roi_pct / leverage
        tp_price = fill_price * (1 - tp_price_pct / 100)
        tp_price = float(exchange.exchange.price_to_precision(symbol, tp_price))

        # Safety: TP must be at least 1 tick below fill
        tp_adjusted = False
        if tp_price >= fill_price:
            tp_price = float(exchange.exchange.price_to_precision(symbol, fill_price - tick_size))
            tp_adjusted = True
            logger.warning(f"TP adjusted to fill - 1 tick: {tp_price} (fill={fill_price}, tick={tick_size})")

        # Step 3: Set TP with retry
        tp_set = False
        for attempt in range(3):
            if exchange.set_take_profit(symbol, tp_price, position["amount"]):
                tp_set = True
                break
            logger.warning(f"TP retry {attempt + 1}/3 for {symbol}")
            time.sleep(1)

        position["take_profit"] = tp_price

        # Save to state
        state = load_state()
        add_position(state, position)

        warning = None
        if not tp_set:
            # Save pending TP for bot cycle recovery
            state.setdefault("pending_tp", {})[symbol] = {
                "tp_price": tp_price,
                "amount": position["amount"],
                "timestamp": time.time(),
            }
            save_state(state)
            warning = "TP failed to set — will retry next cycle"
            logger.error(f"TP failed after 3 retries for {symbol}")

        tp_change_pct = round((fill_price - tp_price) / fill_price * 100, 2)
        logger.info(f"Manual SHORT opened: {symbol} fill={fill_price} TP={tp_price} ({tp_change_pct}%) margin={margin} ({bet_pct}% of {balance:.2f})")

        return jsonify({
            "ok": True,
            "warning": warning,
            "order": {
                "symbol": symbol.split(":")[0],
                "entry_price": fill_price,
                "amount": position["amount"],
                "margin": margin,
                "take_profit": tp_price,
                "tp_change_pct": tp_change_pct,
                "tp_adjusted": tp_adjusted,
                "order_id": position["order_id"],
            }
        })

    except Exception as e:
        logger.exception(f"Error in /api/short: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/shorts", methods=["GET"])
def api_shorts():
    """Return open positions + recent closed shorts for the Recent Shorts panel."""
    try:
        config, exchange, exchange_positions, state = _get_synced_context()
        pos_data = build_position_data(exchange_positions, state, exchange)
        balance = exchange.get_balance()

        # Recent closed trades with full details
        recent_closes = []
        try:
            closes_limit = config.get('recent_closes_count', 12)
            recent_closes = exchange.get_closed_short_trades(limit=closes_limit)
        except Exception as e:
            logger.error(f"Error fetching closed trades: {e}")

        return jsonify({
            "ok": True,
            "positions": pos_data,
            "recent_closes": recent_closes,
            "balance": balance,
        })
    except Exception as e:
        logger.exception(f"Error in /api/shorts: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/positions", methods=["GET"])
def api_positions():
    """Return open positions as JSON for real-time table refresh."""
    try:
        config, exchange, exchange_positions, state = _get_synced_context()
        pos_data = build_position_data(exchange_positions, state, exchange)
        balance = exchange.get_balance()

        # Calculate days_since_liq for each position
        for p in pos_data:
            liq = p.get("liq_price", 0)
            if liq > 0:
                try:
                    candles_1d = exchange.get_ohlcv(p["symbol"], '1d', limit=90)
                    if candles_1d and len(candles_1d) > 1:
                        found = False
                        for i in range(len(candles_1d) - 1, -1, -1):
                            if candles_1d[i][2] >= liq:
                                p["days_since_liq"] = len(candles_1d) - 1 - i
                                found = True
                                break
                        if not found:
                            p["days_since_liq"] = 1000 + len(candles_1d)
                except Exception:
                    pass

        return jsonify({
            "ok": True,
            "positions": pos_data,
            "balance": balance,
        })
    except Exception as e:
        logger.exception(f"Error in /api/positions: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response


if __name__ == "__main__":
    logger.info("Starting API server on port 8432")
    app.run(host="0.0.0.0", port=8432)
