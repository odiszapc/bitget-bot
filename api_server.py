"""
API server for manual trading actions.
Runs as a separate service, exposes REST endpoints.
"""

import json
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

        # Get entry price
        ticker = exchange.get_ticker(symbol)
        if not ticker:
            return jsonify({"ok": False, "error": f"Could not fetch ticker for {symbol}"}), 400

        entry_price = ticker["last"]
        leverage = config.get("leverage", 10)

        # Calculate TP from selected ROI %
        # ROI = price_change% * leverage → price_change% = ROI / leverage
        tp_price_pct = tp_roi_pct / leverage
        tp_price = entry_price * (1 - tp_price_pct / 100)  # SHORT: TP below entry
        tp_price = float(exchange.exchange.price_to_precision(symbol, tp_price))

        # Safety: TP must be at least 1 tick below entry
        tick_size = exchange.get_tick_size(symbol)
        if tp_price >= entry_price:
            tp_price = entry_price - tick_size
            tp_price = float(exchange.exchange.price_to_precision(symbol, tp_price))
            logger.warning(f"TP adjusted to entry - 1 tick: {tp_price} (tick={tick_size})")

        # Open short with TP only
        position = exchange.open_short_tp_only(symbol, margin, tp_price)
        if not position:
            return jsonify({"ok": False, "error": "Exchange rejected the order"}), 500

        # Save to state
        state = load_state()
        add_position(state, position)

        logger.info(f"Manual SHORT opened: {symbol} margin={margin} ({bet_pct}% of {balance:.2f}) TP={tp_price} (ROI {tp_roi_pct}%)")

        return jsonify({
            "ok": True,
            "order": {
                "symbol": symbol.split(":")[0],
                "entry_price": position["entry_price"],
                "amount": position["amount"],
                "margin": margin,
                "take_profit": tp_price,
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
