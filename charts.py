"""
Chart generation module: creates line charts for coin candles.
Style: dark background, cyan line with gradient fill, minimal.
"""

import os
import shutil
import logging
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

logger = logging.getLogger(__name__)

CANDLES_DIR = os.path.join("output", "candles")

TIMEFRAMES = ["1m", "15m", "1h"]
CANDLE_LIMIT = 150

# Style constants
BG_COLOR = "#0d1117"
LINE_COLOR = "#00d4ff"
GRID_COLOR = "#1a1e2e"
GLOW_COLOR = "#00d4ff"


def _symbol_to_filename(symbol: str) -> str:
    """Convert 'BTC/USDT:USDT' to 'BTC_USDT'."""
    clean = symbol.split(":")[0]  # 'BTC/USDT'
    return clean.replace("/", "_")


def clear_candles_dir():
    """Remove all files from candles directory."""
    if os.path.exists(CANDLES_DIR):
        shutil.rmtree(CANDLES_DIR)
    os.makedirs(CANDLES_DIR, exist_ok=True)


OVERLAP_COLOR = "#f0883e"


def generate_chart(closes: list[float], symbol: str, timeframe: str, overlap_candles: int = 0) -> str | None:
    """
    Generate a single chart PNG.
    overlap_candles: if > 0, draw a vertical marker line showing where the
    finer-resolution chart starts (counted from the right edge).
    Returns the filename relative to output/ or None on error.
    """
    if not closes or len(closes) < 2:
        return None

    try:
        fig, ax = plt.subplots(figsize=(6, 2.5), dpi=100)
        fig.patch.set_facecolor(BG_COLOR)
        ax.set_facecolor(BG_COLOR)

        x = np.arange(len(closes))
        y = np.array(closes, dtype=float)

        # Draw line
        ax.plot(x, y, color=LINE_COLOR, linewidth=1.2, zorder=3)

        # Create gradient effect with multiple fills
        n_layers = 20
        for i in range(n_layers):
            frac = i / n_layers
            alpha = 0.35 * (1 - frac)
            level = y.min() + (y - y.min()) * (1 - frac)
            ax.fill_between(x, level, y.min(), color=LINE_COLOR, alpha=alpha / n_layers, zorder=2)

        # Glow on last point
        ax.scatter([x[-1]], [y[-1]], color=GLOW_COLOR, s=30, zorder=5, edgecolors='none')
        ax.scatter([x[-1]], [y[-1]], color=GLOW_COLOR, s=120, alpha=0.15, zorder=4, edgecolors='none')

        # Grid - subtle vertical lines
        for gx in np.linspace(0, len(closes) - 1, 5)[1:-1]:
            ax.axvline(x=gx, color=GRID_COLOR, linewidth=0.5, zorder=1)

        # Overlap marker — where the finer chart begins
        if 0 < overlap_candles < len(closes):
            marker_x = len(closes) - overlap_candles
            ax.axvline(x=marker_x, color=OVERLAP_COLOR, linewidth=1, linestyle="--", zorder=6, alpha=0.7)

        # Remove all axes, labels, borders
        ax.set_xlim(0, len(closes) - 1)
        ax.margins(y=0.05)
        ax.axis("off")
        plt.subplots_adjust(left=0, right=1, top=1, bottom=0)

        name = _symbol_to_filename(symbol)
        filename = f"candles/{name}_{timeframe}.png"
        filepath = os.path.join("output", filename)
        fig.savefig(filepath, facecolor=BG_COLOR, bbox_inches="tight", pad_inches=0.02)
        plt.close(fig)

        return filename

    except Exception as e:
        logger.error(f"Error generating chart for {symbol} {timeframe}: {e}")
        plt.close("all")
        return None


# How many candles from the right the finer chart covers on this chart:
# 15m chart: 150 1m-candles = 150 min → 150/15 = 10 candles
# 1h chart: 150 15m-candles = 2250 min → 2250/60 = 37 candles
OVERLAP_CANDLES = {
    "1m": 0,
    "15m": CANDLE_LIMIT // 15,          # 150 / 15 = 10
    "1h": CANDLE_LIMIT * 15 // 60,      # 150 * 15 / 60 = 37
}


def generate_charts_for_symbols(exchange, scan_results: list[dict]) -> dict:
    """
    Generate charts for top scan results.
    Returns {symbol: {"1m": "candles/BTC_USDT_1m.png", ...}}
    """
    clear_candles_dir()

    chart_map = {}
    symbols = [sr["symbol"] for sr in scan_results[:20]]

    for symbol in symbols:
        chart_map[symbol] = {}
        for tf in TIMEFRAMES:
            candles = exchange.get_ohlcv(symbol, tf, limit=CANDLE_LIMIT)
            if not candles or len(candles) < 2:
                continue
            closes = [c[4] for c in candles]  # close price is index 4
            overlap = OVERLAP_CANDLES.get(tf, 0)
            filename = generate_chart(closes, symbol, tf, overlap_candles=overlap)
            if filename:
                chart_map[symbol][tf] = filename

    generated = sum(len(v) for v in chart_map.values())
    logger.info(f"Generated {generated} charts for {len(symbols)} symbols")

    return chart_map
