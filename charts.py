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


ENTRY_COLOR = "#f0b429"


def generate_chart(closes: list[float], symbol: str, timeframe: str,
                   overlap_candles: int = 0, entry_idx: int = None,
                   entry_price: float = None) -> str | None:
    """
    Generate a single chart PNG.
    overlap_candles: if > 0, draw a vertical marker line showing where the
    finer-resolution chart starts (counted from the right edge).
    entry_idx/entry_price: if provided and within visible range, draw entry marker.
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

        # Lock geometry before optional markers
        ax.set_xlim(0, len(closes) - 1)
        ax.margins(y=0.05)
        y_min, y_max = ax.get_ylim()

        # Entry marker — only if within visible range (don't change geometry)
        if (entry_idx is not None and entry_price is not None
                and 0 <= entry_idx < len(closes)
                and y_min <= entry_price <= y_max):
            ax.scatter([entry_idx], [entry_price], color=ENTRY_COLOR, s=80, zorder=8, edgecolors='none')
            ax.scatter([entry_idx], [entry_price], color=ENTRY_COLOR, s=250, alpha=0.2, zorder=7, edgecolors='none')
            ax.axhline(y=entry_price, color=ENTRY_COLOR, linewidth=0.7, linestyle='--', alpha=0.4, zorder=5)
            ax.set_ylim(y_min, y_max)  # re-enforce

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


WIN_COLOR = "#3fb950"
LOSS_COLOR = "#f85149"


def generate_backtest_chart(closes: list[float], trades: list[dict], liq_idx: int = None) -> bytes:
    """
    Generate backtest chart as PNG bytes.
    trades: [{closeIdx, closePrice, net, result}, ...]
    liq_idx: candle index of liquidation (or None)
    Returns PNG bytes.
    """
    import io

    fig, ax = plt.subplots(figsize=(6, 2.5), dpi=100)
    fig.patch.set_facecolor(BG_COLOR)
    ax.set_facecolor(BG_COLOR)

    x = np.arange(len(closes))
    y = np.array(closes, dtype=float)

    ax.plot(x, y, color=LINE_COLOR, linewidth=1.2, zorder=3)

    # Gradient fill
    n_layers = 20
    for i in range(n_layers):
        frac = i / n_layers
        alpha = 0.35 * (1 - frac)
        level = y.min() + (y - y.min()) * (1 - frac)
        ax.fill_between(x, level, y.min(), color=LINE_COLOR, alpha=alpha / n_layers, zorder=2)

    # Glow on last point
    ax.scatter([x[-1]], [y[-1]], color=GLOW_COLOR, s=30, zorder=5, edgecolors='none')
    ax.scatter([x[-1]], [y[-1]], color=GLOW_COLOR, s=120, alpha=0.15, zorder=4, edgecolors='none')

    # Grid
    for gx in np.linspace(0, len(closes) - 1, 5)[1:-1]:
        ax.axvline(x=gx, color=GRID_COLOR, linewidth=0.5, zorder=1)

    # Lock geometry
    ax.set_xlim(0, len(closes) - 1)
    ax.margins(y=0.05)
    y_min, y_max = ax.get_ylim()

    # Trade markers
    for t in trades:
        ci = t.get("closeIdx", 0)
        cp = t.get("closePrice", 0)
        if ci < 0 or ci >= len(closes):
            continue
        if not (y_min <= cp <= y_max):
            continue
        color = WIN_COLOR if t.get("net", 0) >= 0 else LOSS_COLOR
        ax.scatter([ci], [cp], color=color, s=80, zorder=8, edgecolors='none')
        ax.scatter([ci], [cp], color=color, s=250, alpha=0.2, zorder=7, edgecolors='none')

    # Liquidation marker
    if liq_idx is not None and 0 <= liq_idx < len(closes):
        lp = closes[liq_idx]
        if y_min <= lp <= y_max:
            ax.scatter([liq_idx], [lp], color=LOSS_COLOR, s=150, zorder=9, edgecolors='none', marker='X')
            ax.axvline(x=liq_idx, color=LOSS_COLOR, linewidth=1, linestyle='--', alpha=0.5, zorder=6)

    ax.set_ylim(y_min, y_max)
    ax.axis("off")
    plt.subplots_adjust(left=0, right=1, top=1, bottom=0)

    buf = io.BytesIO()
    fig.savefig(buf, format='png', facecolor=BG_COLOR, bbox_inches="tight", pad_inches=0.02)
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def _get_chart_symbols(scan_results: list[dict], open_position_symbols: set = None) -> list[str]:
    """Get symbols for charts/risk: top 20 per each metric + open positions."""
    chart_symbols = set()
    sort_keys = [
        ("downtrend_score", True),
        ("r2", True),
        ("adx_dir", True),
        ("slope", False),
        ("roc_w", False),
        ("ema_gap", True),
        ("rsi", True),
        ("atr_pct", True),
        ("volume_24h", True),
    ]
    for field, reverse in sort_keys:
        sorted_by = sorted(scan_results, key=lambda s: s.get(field, 0), reverse=reverse)
        for sr in sorted_by[:20]:
            chart_symbols.add(sr["symbol"])
    sorted_comp = sorted(scan_results, key=lambda s: s.get("n_adx", 0) + s.get("n_slope", 0) + s.get("n_roc", 0) + s.get("n_ema", 0), reverse=True)
    for sr in sorted_comp[:20]:
        chart_symbols.add(sr["symbol"])
    if open_position_symbols:
        chart_symbols.update(open_position_symbols)
    return list(chart_symbols)


def generate_charts_for_symbols(exchange, scan_results: list[dict], open_position_symbols: set = None, status=None, position_entries: dict = None) -> dict:
    """
    Generate charts for top scan results + open positions.
    Reuses cached 15m candles from scan phase.
    position_entries: {symbol: {"price": float, "timestamp_ms": int}} for entry markers.
    Returns {symbol: {"1m": "candles/BTC_USDT_1m.png", ...}}
    """
    from concurrent.futures import ThreadPoolExecutor

    clear_candles_dir()

    symbols = _get_chart_symbols(scan_results, open_position_symbols)
    logger.info(f"Chart symbols: {len(symbols)} unique (from top-20 per metric + open positions)")

    if status:
        status.start_phase("Rendering", len(symbols))

    # Build cache of 15m candles from scan results
    candles_cache = {}
    for sr in scan_results:
        cached = sr.get("_candles_15m")
        if cached:
            candles_cache[sr["symbol"]] = cached

    # Build entry lookup
    entries = position_entries or {}

    def _generate_one(symbol):
        """Fetch missing candles and generate all charts for one symbol."""
        short_name = symbol.split("/")[0].split(":")[0]
        entry_info = entries.get(symbol)
        result = {}
        for tf in TIMEFRAMES:
            if tf == "15m" and symbol in candles_cache:
                candles = candles_cache[symbol]
            else:
                candles = exchange.get_ohlcv(symbol, tf, limit=CANDLE_LIMIT)
            if not candles or len(candles) < 2:
                continue
            closes = [c[4] for c in candles]
            timestamps = [c[0] for c in candles]
            overlap = OVERLAP_CANDLES.get(tf, 0)

            # Find entry candle index for this timeframe
            e_idx = None
            e_price = None
            if entry_info:
                e_price = entry_info["price"]
                e_ts = entry_info["timestamp_ms"]
                for ci, ts in enumerate(timestamps):
                    if ts >= e_ts:
                        e_idx = ci
                        break

            filename = generate_chart(closes, symbol, tf, overlap_candles=overlap,
                                      entry_idx=e_idx, entry_price=e_price)
            if filename:
                result[tf] = filename
        logger.info(f"  {short_name} — {len(result)} charts")
        return symbol, result

    chart_map = {}
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = [pool.submit(_generate_one, sym) for sym in symbols]
        for future in futures:
            symbol, result = future.result()
            chart_map[symbol] = result
            if status:
                status.tick()

    generated = sum(len(v) for v in chart_map.values())
    logger.info(f"Charts done: {generated} charts for {len(symbols)} symbols")

    return chart_map
