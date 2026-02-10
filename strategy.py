"""
Strategy module: technical indicators, filtering, and signal generation.
"""

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

    # Current: fast below slow. Previous: fast above or equal to slow
    current_fast = fast_values.iloc[-1]
    current_slow = slow_values.iloc[-1]
    prev_fast = fast_values.iloc[-2]
    prev_slow = slow_values.iloc[-2]
    prev2_fast = fast_values.iloc[-3]
    prev2_slow = slow_values.iloc[-3]

    # Cross happened in last 1-2 candles
    cross_now = current_fast < current_slow and prev_fast >= prev_slow
    cross_prev = prev_fast < prev_slow and prev2_fast >= prev2_slow

    return cross_now or cross_prev


def calculate_macd_cross(df: pd.DataFrame) -> bool:
    """
    Check if MACD line crossed below signal line (bearish).
    Returns True if crossover happened in the last 2 candles.
    """
    macd = ta.trend.MACD(close=df["close"])
    macd_line = macd.macd()
    signal_line = macd.macd_signal()

    if len(macd_line) < 3:
        return False

    # Current: MACD below signal. Previous: MACD above or equal
    cross_now = (
        macd_line.iloc[-1] < signal_line.iloc[-1]
        and macd_line.iloc[-2] >= signal_line.iloc[-2]
    )
    cross_prev = (
        macd_line.iloc[-2] < signal_line.iloc[-2]
        and macd_line.iloc[-3] >= signal_line.iloc[-3]
    )

    return cross_now or cross_prev


def calculate_volume_spike(df: pd.DataFrame, lookback: int = 20, multiplier: float = 1.5) -> bool:
    """Check if current volume is significantly above recent average."""
    if len(df) < lookback + 1:
        return False
    avg_volume = df["volume"].iloc[-(lookback + 1):-1].mean()
    current_volume = df["volume"].iloc[-1]
    if avg_volume <= 0:
        return False
    return current_volume > multiplier * avg_volume


# ── Strategy functions ──────────────────────────────────────

def analyze_classic(
    df: pd.DataFrame, funding_rate: float | None, config: dict
) -> dict:
    """Classic strategy: RSI>70, EMA_CROSS, MACD_CROSS, FUNDING (3 of 4)."""
    result = {"signals": [], "signal_count": 0, "max_signals": 4,
              "rsi": 0.0, "atr_pct": 0.0, "details": []}

    rsi = calculate_rsi(df)
    result["rsi"] = rsi
    if rsi > 70:
        result["signals"].append("RSI")
        result["details"].append(f"RSI={rsi:.1f} (>70)")

    if calculate_ema_cross(df):
        result["signals"].append("EMA_CROSS")
        result["details"].append("EMA(9)<EMA(21)")

    if calculate_macd_cross(df):
        result["signals"].append("MACD_CROSS")
        result["details"].append("MACD bearish cross")

    if funding_rate is not None and funding_rate > 0.0001:
        result["signals"].append("FUNDING")
        result["details"].append(f"FR={funding_rate*100:.4f}%")

    result["atr_pct"] = calculate_atr(df)
    result["signal_count"] = len(result["signals"])
    return result


def analyze_volume(
    df: pd.DataFrame, funding_rate: float | None, config: dict
) -> dict:
    """Volume strategy: EMA_CROSS alone is enough, OR 3 of 4 signals."""
    result = {"signals": [], "signal_count": 0, "max_signals": 4,
              "rsi": 0.0, "atr_pct": 0.0, "details": []}

    rsi = calculate_rsi(df)
    result["rsi"] = rsi
    if rsi > 65:
        result["signals"].append("RSI")
        result["details"].append(f"RSI={rsi:.1f} (>65)")

    has_ema_cross = calculate_ema_cross(df)
    if has_ema_cross:
        result["signals"].append("EMA_CROSS")
        result["details"].append("EMA(9)<EMA(21)")

    if calculate_volume_spike(df):
        result["signals"].append("VOL_SPIKE")
        result["details"].append("Volume >1.5x avg")

    if funding_rate is not None and funding_rate > 0.0001:
        result["signals"].append("FUNDING")
        result["details"].append(f"FR={funding_rate*100:.4f}%")

    result["atr_pct"] = calculate_atr(df)
    actual_count = len(result["signals"])
    # EMA_CROSS alone is a sufficient signal — treat as 3/4
    if has_ema_cross and actual_count < 3:
        result["signal_count"] = 3
    else:
        result["signal_count"] = actual_count
    return result


STRATEGIES = {
    "classic": analyze_classic,
    "volume": analyze_volume,
}


def analyze_all_strategies(
    df: pd.DataFrame, funding_rate: float | None, config: dict
) -> dict[str, dict]:
    """Run all strategies on a symbol. Returns {name: result_dict}."""
    return {name: fn(df, funding_rate, config) for name, fn in STRATEGIES.items()}


def analyze_symbol(
    df: pd.DataFrame, funding_rate: Optional[float], config: dict
) -> dict:
    """
    Analyze a single symbol and return signal details.

    Returns dict with:
      - signals: list of triggered signal names
      - signal_count: number of signals triggered
      - rsi: current RSI value
      - atr_pct: ATR as percentage
      - details: human-readable details
    """
    result = {
        "signals": [],
        "signal_count": 0,
        "rsi": 0.0,
        "atr_pct": 0.0,
        "details": [],
    }

    # RSI
    rsi = calculate_rsi(df)
    result["rsi"] = rsi
    if rsi > 70:
        result["signals"].append("RSI")
        result["details"].append(f"RSI={rsi:.1f} (>70, overbought)")

    # EMA crossover
    if calculate_ema_cross(df):
        result["signals"].append("EMA_CROSS")
        result["details"].append("EMA(9) crossed below EMA(21)")

    # MACD crossover
    if calculate_macd_cross(df):
        result["signals"].append("MACD_CROSS")
        result["details"].append("MACD bearish crossover")

    # Funding rate
    if funding_rate is not None and funding_rate > 0.0001:  # 0.01%
        result["signals"].append("FUNDING")
        result["details"].append(f"Funding rate={funding_rate*100:.4f}% (>0.01%)")

    # ATR
    atr_pct = calculate_atr(df)
    result["atr_pct"] = atr_pct

    result["signal_count"] = len(result["signals"])

    return result


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


def filter_by_volume(tickers: dict, min_volume_usd: float) -> list[str]:
    """Filter symbols by 24h volume."""
    filtered = []
    for symbol, ticker in tickers.items():
        quote_volume = ticker.get("quoteVolume", 0)
        if quote_volume and float(quote_volume) >= min_volume_usd:
            filtered.append(symbol)
    return filtered
