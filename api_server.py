"""
API server for manual trading actions.
Runs as a separate service, exposes REST endpoints.
"""

import json
import logging
from flask import Flask, request, jsonify
from exchange import Exchange
from strategy import candles_to_dataframe, calculate_atr  # kept for potential future use
from state import load_state, add_position
from positions import build_position_data

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)


def load_config() -> dict:
    with open("config.json", "r") as f:
        return json.load(f)


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
        config = load_config()
        exchange = Exchange(config)
        exchange.load_markets()

        # Open positions
        exchange_positions = exchange.get_open_positions()
        state = load_state()
        pos_data = build_position_data(exchange_positions, state, exchange)

        balance = exchange.get_balance()

        # Recent closes (same logic as bot.py)
        recent_closes = []
        try:
            bills = exchange.get_recent_close_shorts()
            bills.sort(key=lambda b: (int(b.get('cTime', 0)), float(b.get('balance', 0))))
            close_list = []
            for b in bills:
                if b.get('businessType') == 'close_short':
                    close_list.append({
                        'symbol': b.get('symbol', '').replace('USDT', ''),
                        'balance': round(float(b.get('balance', 0)), 2),
                        'timestamp': int(b.get('cTime', 0)) / 1000,
                    })
            for i, c in enumerate(close_list):
                if i > 0:
                    c['delta'] = round(c['balance'] - close_list[i - 1]['balance'], 2)
                else:
                    c['delta'] = None
            close_list.reverse()
            closes_limit = config.get('recent_closes_count', 12)
            recent_closes = close_list[:closes_limit]
        except Exception as e:
            logger.error(f"Error fetching close shorts: {e}")

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
        config = load_config()
        exchange = Exchange(config)
        exchange.load_markets()

        exchange_positions = exchange.get_open_positions()
        state = load_state()
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
