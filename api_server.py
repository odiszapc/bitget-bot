"""
API server for manual trading actions.
Runs as a separate service, exposes REST endpoints.
"""

import json
import logging
from flask import Flask, request, jsonify
from exchange import Exchange
from strategy import candles_to_dataframe, calculate_atr, calculate_sl_tp
from state import load_state, add_position

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

        config = load_config()
        exchange = Exchange(config)
        exchange.load_markets()

        # Check position limit
        max_positions = config.get("max_positions", 5)
        open_positions = exchange.get_open_positions()
        open_count = len(open_positions)

        if open_count >= max_positions:
            return jsonify({
                "ok": False,
                "error": f"Max positions reached ({open_count}/{max_positions})"
            }), 400

        # Check if already have position on this symbol
        for pos in open_positions:
            if pos["symbol"] == symbol:
                return jsonify({
                    "ok": False,
                    "error": f"Position already open for {symbol.split(':')[0]}"
                }), 400

        # Get balance — use full available balance
        balance = exchange.get_balance()
        if balance <= 0:
            return jsonify({"ok": False, "error": "Zero balance"}), 400

        margin = round(balance * 0.98, 2)

        # Calculate TP from ATR
        timeframe = config.get("timeframe", "15m")
        candles = exchange.get_ohlcv(symbol, timeframe, limit=50)
        df = candles_to_dataframe(candles)
        if df is None:
            return jsonify({"ok": False, "error": "Not enough candle data"}), 400

        atr_pct = calculate_atr(df)

        ticker = exchange.get_ticker(symbol)
        if not ticker:
            return jsonify({"ok": False, "error": f"Could not fetch ticker for {symbol}"}), 400

        entry_price = ticker["last"]
        _sl_price, tp_price = calculate_sl_tp(entry_price, atr_pct, config)

        # Open short with TP only
        position = exchange.open_short_tp_only(symbol, margin, tp_price)
        if not position:
            return jsonify({"ok": False, "error": "Exchange rejected the order"}), 500

        # Save to state
        state = load_state()
        add_position(state, position)

        logger.info(f"Manual SHORT opened: {symbol} margin={margin} TP={tp_price}")

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


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    return response


if __name__ == "__main__":
    logger.info("Starting API server on port 8432")
    app.run(host="0.0.0.0", port=8432)
