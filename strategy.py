"""
Strategy module: technical indicators, filtering, and composite downtrend scoring.
"""

import numpy as np
import pandas as pd
import ta
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def candles_to_dataframe(candles: list) -> Optional[pd.DataFrame]:
    """Convert OHLCV candles to a pandas DataFrame."""
    if not candles or len(candles) < 30:
        return None

    df = pd.DataFrame(
        candles, columns=["timestamp", "open", "high", "low", "close", "volume"]
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    return df


def calculate_atr(df: pd.DataFrame, period: int = 14) -> float:
    """Calculate ATR as percentage of current price."""
    atr_indicator = ta.volatility.AverageTrueRange(
        high=df["high"], low=df["low"], close=df["close"], window=period
    )
    atr_value = atr_indicator.average_true_range().iloc[-1]
    current_price = df["close"].iloc[-1]
    if current_price == 0:
        return 999.0
    return (atr_value / current_price) * 100


def calculate_rsi(df: pd.DataFrame, period: int = 14) -> float:
    """Calculate RSI."""
    rsi = ta.momentum.RSIIndicator(close=df["close"], window=period)
    return float(rsi.rsi().iloc[-1])


def calculate_ema_cross(df: pd.DataFrame, fast: int = 9, slow: int = 21) -> bool:
    """
    Check if fast EMA just crossed below slow EMA (bearish crossover).
    Returns True if crossover happened in the last 2 candles.
    """
    ema_fast = ta.trend.EMAIndicator(close=df["close"], window=fast)
    ema_slow = ta.trend.EMAIndicator(close=df["close"], window=slow)

    fast_values = ema_fast.ema_indicator()
    slow_values = ema_slow.ema_indicator()

    if len(fast_values) < 3:
        return False

    current_fast = fast_values.iloc[-1]
    current_slow = slow_values.iloc[-1]
    prev_fast = fast_values.iloc[-2]
    prev_slow = slow_values.iloc[-2]
    prev2_fast = fast_values.iloc[-3]
    prev2_slow = slow_values.iloc[-3]

    cross_now = current_fast < current_slow and prev_fast >= prev_slow
    cross_prev = prev_fast < prev_slow and prev2_fast >= prev2_slow

    return cross_now or cross_prev


# ── Composite downtrend strategy ──────────────────────────────

def _adx_directional(df: pd.DataFrame, period: int = 14) -> tuple[float, float, float, float]:
    """Returns (directional_score, adx, di_plus, di_minus)."""
    adx_ind = ta.trend.ADXIndicator(
        high=df["high"], low=df["low"], close=df["close"], window=period
    )
    adx = adx_ind.adx().iloc[-1]
    di_plus = adx_ind.adx_pos().iloc[-1]
    di_minus = adx_ind.adx_neg().iloc[-1]
    return (di_minus - di_plus) * (adx / 100), adx, di_plus, di_minus


def _slope_and_r2(df: pd.DataFrame, period: int = 150) -> tuple[float, float]:
    """Linear regression slope (%/candle) and R² (trend quality 0-1)."""
    closes = df["close"].iloc[-period:].values
    x = np.arange(len(closes))
    coeffs = np.polyfit(x, closes, 1)
    avg = closes.mean()
    slope_pct = (coeffs[0] / avg) * 100 if avg != 0 else 0.0
    # R² — how well a straight line fits the price action
    predicted = np.polyval(coeffs, x)
    ss_res = np.sum((closes - predicted) ** 2)
    ss_tot = np.sum((closes - avg) ** 2)
    r2 = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0.0
    return slope_pct, max(0.0, r2)


def _roc_weighted(df: pd.DataFrame) -> float:
    """Weighted ROC: 5-period*0.4 + 14-period*0.35 + 150-period*0.25."""
    close = df["close"]
    def roc(n):
        if len(close) < n + 1:
            return 0.0
        return (close.iloc[-1] - close.iloc[-n - 1]) / close.iloc[-n - 1] * 100
    return roc(5) * 0.4 + roc(14) * 0.35 + roc(150) * 0.25


def _ema_gap(df: pd.DataFrame, fast: int = 9, slow: int = 21) -> float:
    """(EMA_slow - EMA_fast) / price * 100. Positive = bearish spread."""
    ema_f = ta.trend.EMAIndicator(close=df["close"], window=fast).ema_indicator().iloc[-1]
    ema_s = ta.trend.EMAIndicator(close=df["close"], window=slow).ema_indicator().iloc[-1]
    price = df["close"].iloc[-1]
    return (ema_s - ema_f) / price * 100 if price != 0 else 0.0


def _drop_concentration(df: pd.DataFrame, period: int = 150, top_n: int = 3, threshold_pct: float = -5.0) -> float:
    """
    What fraction of total price drop is concentrated in top-N biggest candles.
    Returns 0-1: 0 = evenly distributed or small drop, 1 = large drop in N candles.
    threshold_pct: minimum drop % for DC to activate (default -5% for 15m, -3% for 1h).
    """
    closes = df["close"].iloc[-period:].values
    if len(closes) < 2:
        return 0.0
    total_move = closes[-1] - closes[0]
    total_pct = total_move / closes[0] * 100 if closes[0] != 0 else 0
    if total_pct >= threshold_pct:
        return 0.0  # Drop too small for concentration to matter
    changes = np.diff(closes)
    top_drops = np.sort(changes)[:top_n]
    top_sum = top_drops.sum()
    conc = top_sum / total_move if total_move != 0 else 0.0
    return float(np.clip(conc, 0.0, 1.0))


def calculate_downtrend_components(df: pd.DataFrame) -> dict:
    """Calculate raw downtrend components for a single symbol."""
    adx_dir, adx, di_plus, di_minus = _adx_directional(df)
    slope, r2 = _slope_and_r2(df)
    roc_w = _roc_weighted(df)
    ema_g = _ema_gap(df)
    dc = _drop_concentration(df)
    return {
        "adx_dir": adx_dir, "adx": adx, "di_plus": di_plus, "di_minus": di_minus,
        "slope": slope, "roc_w": roc_w, "ema_gap": ema_g, "r2": r2, "dc": dc,
    }


def normalize_downtrend_scores(scan_results: list[dict]) -> None:
    """
    Normalize raw components across all scan results and compute composite score.
    Mutates scan_results in place, adding 'downtrend_score' field.
    """
    if not scan_results:
        return

    def _norm(values):
        arr = np.array(values, dtype=float)
        mn, mx = arr.min(), arr.max()
        if mx == mn:
            return [50.0] * len(values)
        return ((arr - mn) / (mx - mn) * 100).tolist()

    # Higher = more bearish for all components
    n_adx = _norm([r.get("adx_dir", 0) for r in scan_results])
    n_slope = _norm([-r.get("slope", 0) for r in scan_results])
    n_roc = _norm([-r.get("roc_w", 0) for r in scan_results])
    n_ema = _norm([r.get("ema_gap", 0) for r in scan_results])

    for i, r in enumerate(scan_results):
        r["n_adx"] = round(n_adx[i], 1)
        r["n_slope"] = round(n_slope[i], 1)
        r["n_roc"] = round(n_roc[i], 1)
        r["n_ema"] = round(n_ema[i], 1)
        raw_score = 0.30 * n_adx[i] + 0.25 * n_slope[i] + 0.25 * n_roc[i] + 0.20 * n_ema[i]
        # Quality multiplier: R² (trend smoothness) × DC penalty (drop distribution)
        # R² only counts for downtrends — zero for uptrends (slope >= 0)
        r2 = r.get("r2", 1.0)
        slope = r.get("slope", 0)
        effective_r2 = r2 if slope < 0 else 0.0
        # DC penalty only kicks in above 0.5: dc=0.5→no penalty, dc=1.0→score halved
        dc = r.get("dc", 0.0)
        dc_penalty = 1.0 - max(0.0, dc - 0.5) * 2.0  # 1.0 at dc≤0.5, 0.0 at dc=1.0
        # 1h quality: slope_1h >= 0 → uptrend on higher TF → kill score
        slope_1h = r.get("slope_1h", 0)
        r2_1h = r.get("r2_1h", 0)
        quality_1h = r2_1h if slope_1h < 0 else 0.0
        # ADX dir penalty: negative = bulls winning on 15m → penalize
        adx_dir = r.get("adx_dir", 0)
        adx_penalty = 1.0 if adx_dir >= 0 else 0.0
        # 1h DC penalty: flash crash on hourly (threshold 3%)
        dc_1h = r.get("dc_1h", 0.0)
        dc_1h_penalty = 1.0 - max(0.0, dc_1h - 0.5) * 2.0
        quality = effective_r2 * max(0.1, dc_penalty) * max(0.1, quality_1h) * max(0.1, dc_1h_penalty) * max(0.1, adx_penalty)
        r["downtrend_score"] = round(raw_score * quality, 1)


def calculate_min_roi(price: float, tick_size: float, leverage: int = 10, taker_rate: float = 0.001, slippage_ticks: int = 2) -> float:
    """Calculate minimum ROI % for a profitable trade, accounting for fees and slippage."""
    if price <= 0 or tick_size <= 0:
        return 99.0
    min_price_change = 2 * taker_rate + slippage_ticks * tick_size / price
    return round(min_price_change * leverage * 100, 2)


def analyze_symbol(df: pd.DataFrame, config: dict) -> dict:
    """Analyze a single symbol: RSI, ATR, and composite downtrend components."""
    rsi = calculate_rsi(df)
    atr_pct = calculate_atr(df)
    components = calculate_downtrend_components(df)
    return {
        "rsi": rsi,
        "atr_pct": atr_pct,
        **components,
        "downtrend_score": 0,  # placeholder, set by normalize_downtrend_scores
    }


def calculate_sl_tp(
    entry_price: float, atr_pct: float, config: dict
) -> tuple[float, float]:
    """
    Calculate stop-loss and take-profit prices for a short position.

    Variant 3 (Hybrid ATR):
    - SL = max(min_stop_pct, 1.5 * ATR)
    - TP = max(min_tp_pct, 2.5 * ATR)

    For short: SL is ABOVE entry, TP is BELOW entry.
    """
    min_stop_pct = config.get("min_stop_pct", 2.0)
    min_tp_pct = config.get("min_tp_pct", 5.0)

    sl_pct = max(min_stop_pct, 1.5 * atr_pct)
    tp_pct = max(min_tp_pct, 0.1 * atr_pct)

    # Short position: SL above, TP below
    stop_loss_price = entry_price * (1 + sl_pct / 100)
    take_profit_price = entry_price * (1 - tp_pct / 100)

    return round(stop_loss_price, 8), round(take_profit_price, 8)
