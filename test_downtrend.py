"""
Test run: calculate Composite Downtrend Score for all liquid pairs
and output an HTML table for visual analysis.
"""

import json
import numpy as np
import pandas as pd
import ta
from exchange import Exchange
from strategy import candles_to_dataframe, calculate_atr, calculate_rsi, calculate_ema_cross


def calculate_adx_directional(df, period=14):
    """(DI_minus - DI_plus) * ADX/100. Positive = downtrend."""
    adx_ind = ta.trend.ADXIndicator(
        high=df["high"], low=df["low"], close=df["close"], window=period
    )
    adx = adx_ind.adx().iloc[-1]
    di_plus = adx_ind.adx_pos().iloc[-1]
    di_minus = adx_ind.adx_neg().iloc[-1]
    directional = (di_minus - di_plus) * (adx / 100)
    return directional, adx, di_plus, di_minus


def calculate_slope_pct(df, period=14):
    """Linear regression slope of close prices, as %/candle."""
    closes = df["close"].iloc[-period:].values
    x = np.arange(len(closes))
    slope = np.polyfit(x, closes, 1)[0]
    avg_price = closes.mean()
    if avg_price == 0:
        return 0.0
    return (slope / avg_price) * 100


def calculate_roc_weighted(df):
    """Weighted Rate of Change: ROC(5)*0.4 + ROC(14)*0.35 + ROC(30)*0.25."""
    close = df["close"]
    def roc(n):
        if len(close) < n + 1:
            return 0.0
        return (close.iloc[-1] - close.iloc[-n - 1]) / close.iloc[-n - 1] * 100
    return roc(5) * 0.4 + roc(14) * 0.35 + roc(30) * 0.25


def calculate_ema_gap(df, fast=9, slow=21):
    """(EMA_slow - EMA_fast) / price * 100. Positive = bearish spread."""
    ema_fast = ta.trend.EMAIndicator(close=df["close"], window=fast).ema_indicator().iloc[-1]
    ema_slow = ta.trend.EMAIndicator(close=df["close"], window=slow).ema_indicator().iloc[-1]
    price = df["close"].iloc[-1]
    if price == 0:
        return 0.0
    return (ema_slow - ema_fast) / price * 100


def norm_minmax(values):
    """Normalize list of values to 0-100 using min-max."""
    arr = np.array(values, dtype=float)
    mn, mx = arr.min(), arr.max()
    if mx == mn:
        return [50.0] * len(values)
    return ((arr - mn) / (mx - mn) * 100).tolist()


def main():
    config = json.load(open("config.json"))
    exchange = Exchange(config)
    exchange.load_markets()

    symbols = exchange.get_usdt_futures_symbols()
    min_volume = config.get("min_volume_usd", 5_000_000)
    timeframe = config.get("timeframe", "15m")

    print("Fetching tickers...", flush=True)
    tickers = exchange.get_tickers(symbols[:100])
    liquid = []
    for sym, t in tickers.items():
        qv = t.get("quoteVolume", 0)
        if qv and float(qv) >= min_volume:
            liquid.append(sym)
    print(f"Liquid pairs: {len(liquid)}", flush=True)

    rows = []
    for i, symbol in enumerate(liquid):
        try:
            candles = exchange.get_ohlcv(symbol, timeframe, limit=100)
            df = candles_to_dataframe(candles)
            if df is None or len(df) < 30:
                continue

            rsi = calculate_rsi(df)
            atr_pct = calculate_atr(df)
            adx_dir, adx, di_plus, di_minus = calculate_adx_directional(df)
            slope = calculate_slope_pct(df, 14)
            roc_w = calculate_roc_weighted(df)
            ema_gap = calculate_ema_gap(df)
            ema_cross = calculate_ema_cross(df)

            base = symbol.split("/")[0]
            rows.append({
                "symbol": base,
                "rsi": rsi,
                "atr_pct": atr_pct,
                "adx": adx,
                "di_plus": di_plus,
                "di_minus": di_minus,
                "adx_dir": adx_dir,
                "slope": slope,
                "roc_w": roc_w,
                "ema_gap": ema_gap,
                "ema_cross": ema_cross,
            })
        except Exception as e:
            pass

        if (i + 1) % 10 == 0:
            print(f"  {i+1}/{len(liquid)}...", flush=True)
        import time; time.sleep(0.05)

    print(f"\nAnalyzed: {len(rows)} pairs", flush=True)

    # Normalize components
    adx_dirs = [r["adx_dir"] for r in rows]
    slopes = [-r["slope"] for r in rows]       # negate: more negative slope = higher score
    rocs = [-r["roc_w"] for r in rows]         # negate: more negative ROC = higher score
    ema_gaps = [r["ema_gap"] for r in rows]    # positive = bearish

    n_adx = norm_minmax(adx_dirs)
    n_slope = norm_minmax(slopes)
    n_roc = norm_minmax(rocs)
    n_ema = norm_minmax(ema_gaps)

    for i, r in enumerate(rows):
        r["n_adx"] = n_adx[i]
        r["n_slope"] = n_slope[i]
        r["n_roc"] = n_roc[i]
        r["n_ema"] = n_ema[i]
        r["score"] = 0.30 * n_adx[i] + 0.25 * n_slope[i] + 0.25 * n_roc[i] + 0.20 * n_ema[i]

    rows.sort(key=lambda r: r["score"], reverse=True)

    # Generate HTML
    html = """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Downtrend Score Test</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'SF Mono','Consolas',monospace; background:#0d1117; color:#c9d1d9; padding:20px; }
h1 { color:#58a6ff; font-size:18px; margin-bottom:16px; }
table { width:100%; border-collapse:collapse; background:#161b22; border:1px solid #21262d; border-radius:8px; overflow:hidden; }
th { background:#1c2128; color:#6e7681; font-size:10px; text-transform:uppercase; padding:8px 10px; text-align:right; }
th:first-child, th:nth-child(2) { text-align:left; }
td { padding:7px 10px; font-size:12px; border-top:1px solid #21262d; text-align:right; white-space:nowrap; }
td:first-child { text-align:left; color:#58a6ff; font-weight:600; }
td:nth-child(2) { text-align:left; }
tr:hover { background:#1c2128; }
.pos { color:#3fb950; }
.neg { color:#f85149; }
.warn { color:#d29922; }
.muted { color:#6e7681; }
.bar { display:inline-block; height:10px; border-radius:3px; vertical-align:middle; }
.bar-green { background:linear-gradient(90deg,#238636,#3fb950); }
.bar-red { background:linear-gradient(90deg,#da3633,#f85149); }
.bar-blue { background:linear-gradient(90deg,#1f6feb,#58a6ff); }
small { color:#6e7681; font-size:10px; }
</style></head><body>
<h1>Composite Downtrend Score — """ + f"{len(rows)} pairs, {timeframe}" + """</h1>
<table><thead><tr>
<th>#</th><th>Symbol</th><th>Score</th>
<th>ADX<br><small>dir</small></th>
<th>Slope<br><small>%/candle</small></th>
<th>ROC<br><small>weighted</small></th>
<th>EMA<br><small>gap%</small></th>
<th>RSI</th><th>ATR%</th>
<th>ADX</th><th>+DI</th><th>-DI</th>
<th>EMA×</th>
<th style="min-width:160px">Components</th>
</tr></thead><tbody>
"""
    for idx, r in enumerate(rows):
        # Score color
        sc = r["score"]
        if sc >= 70:
            sc_cls = "pos"
        elif sc >= 40:
            sc_cls = "warn"
        else:
            sc_cls = "muted"

        # RSI color
        if r["rsi"] > 70:
            rsi_cls = "pos"
        elif r["rsi"] > 60:
            rsi_cls = "warn"
        else:
            rsi_cls = ""

        # Slope color
        sl_cls = "pos" if r["slope"] < -0.05 else ("neg" if r["slope"] > 0.05 else "muted")

        # ROC color
        roc_cls = "pos" if r["roc_w"] < -0.5 else ("neg" if r["roc_w"] > 0.5 else "muted")

        # EMA cross
        ema_x = "✓" if r["ema_cross"] else ""
        ema_cls = "pos" if r["ema_cross"] else "muted"

        # Component bars
        bars = (
            f'<span class="bar bar-blue" style="width:{r["n_adx"]:.0f}px" title="ADX {r["n_adx"]:.0f}"></span> '
            f'<span class="bar bar-green" style="width:{r["n_slope"]:.0f}px" title="Slope {r["n_slope"]:.0f}"></span> '
            f'<span class="bar bar-red" style="width:{r["n_roc"]:.0f}px" title="ROC {r["n_roc"]:.0f}"></span> '
            f'<span class="bar bar-blue" style="width:{r["n_ema"]:.0f}px" title="EMA {r["n_ema"]:.0f}"></span>'
        )

        html += f"""<tr>
<td>{idx+1}</td>
<td>{r['symbol']}</td>
<td class="{sc_cls}"><b>{sc:.0f}</b></td>
<td class="{'pos' if r['adx_dir']>0 else 'neg'}">{r['adx_dir']:+.1f}</td>
<td class="{sl_cls}">{r['slope']:+.3f}</td>
<td class="{roc_cls}">{r['roc_w']:+.2f}</td>
<td>{r['ema_gap']:+.3f}</td>
<td class="{rsi_cls}">{r['rsi']:.0f}</td>
<td>{r['atr_pct']:.1f}</td>
<td>{r['adx']:.0f}</td>
<td>{r['di_plus']:.0f}</td>
<td>{r['di_minus']:.0f}</td>
<td class="{ema_cls}">{ema_x}</td>
<td>{bars}</td>
</tr>
"""

    html += "</tbody></table></body></html>"

    out_path = "output/downtrend_test.html"
    with open(out_path, "w") as f:
        f.write(html)
    print(f"\n✅ Written to {out_path}")


if __name__ == "__main__":
    main()
