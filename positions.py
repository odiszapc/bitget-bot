"""
Shared position data builder.
Used by report.py (HTML generation) and api_server.py (JSON API).
"""

from datetime import datetime, timezone


def build_position_data(
    exchange_positions: list[dict],
    state: dict,
    exchange=None,
) -> list[dict]:
    """
    Build enriched position data from exchange positions + state.
    Returns a list of dicts with all fields needed for display.
    """
    positions_state = state.get("positions", {})
    now_dt = datetime.now(timezone.utc)
    result = []

    for ep in exchange_positions:
        if ep["side"] != "short":
            continue

        symbol = ep["symbol"]
        tracked = positions_state.get(symbol, {})

        entry_price = ep.get("entry_price", 0)
        margin = ep.get("margin", 0)
        leverage = ep.get("leverage", 0)
        current_price = ep.get("mark_price", 0) or entry_price
        unrealized_pnl = ep.get("unrealized_pnl", 0)
        pnl_pct = ep.get("percentage", 0)
        liq_price = ep.get("liquidation_price", 0)
        deducted_fee = ep.get("deducted_fee", 0)
        break_even = ep.get("break_even_price", 0)
        pp = ep.get("price_precision", 2)

        # TP/SL: exchange position fields, then state, then plan orders
        tp = ep.get("take_profit", 0) or tracked.get("take_profit", 0)
        sl = ep.get("stop_loss", 0) or tracked.get("current_sl") or tracked.get("stop_loss", 0)
        if exchange and (not tp or not sl):
            try:
                tp_sl = exchange.get_tp_sl_for_symbol(symbol)
                if not tp and tp_sl["tp"]:
                    tp = float(tp_sl["tp"])
                if not sl and tp_sl["sl"]:
                    sl = float(tp_sl["sl"])
            except Exception:
                pass

        # Opened time: state first, then exchange timestamp as fallback
        opened_ts = tracked.get("opened_at", 0)
        if not opened_ts:
            ex_ts = ep.get("timestamp", 0)
            opened_ts = ex_ts / 1000 if ex_ts > 1e12 else ex_ts  # ms → sec
        opened_str = "-"
        opened_short_str = "-"
        if opened_ts:
            opened_dt = datetime.fromtimestamp(opened_ts, tz=timezone.utc)
            ago_sec = (now_dt - opened_dt).total_seconds()
            if ago_sec < 3600:
                ago_str = f"{int(ago_sec // 60)} min ago"
            elif ago_sec < 86400:
                ago_str = f"{int(ago_sec // 3600)} h ago"
            else:
                ago_str = f"{int(ago_sec // 86400)} d ago"
            opened_str = f"{opened_dt.strftime('%Y-%m-%d %H:%M')} ({ago_str})"
            opened_short_str = f"{opened_dt.strftime('%b-%d %H:%M')} ({ago_str})"

        # Progress bar data for SHORT positions
        if current_price <= entry_price and tp and entry_price > 0:
            tp_range = entry_price - tp
            prog_val = ((entry_price - current_price) / tp_range * 100) if tp_range > 0 else 0
            prog_val = min(100.0, max(0.0, prog_val))
            prog_cls = "prog-positive"
            prog_label_l = "TP"
            prog_label_r = "Entry"
        elif liq_price and entry_price > 0:
            liq_range = liq_price - entry_price
            prog_val = ((current_price - entry_price) / liq_range * 100) if liq_range > 0 else 0
            prog_val = min(100.0, max(0.0, prog_val))
            prog_cls = "prog-negative"
            prog_label_l = "Entry"
            prog_label_r = "Liq"
        else:
            prog_val = 0.0
            prog_cls = "prog-positive"
            prog_label_l = ""
            prog_label_r = ""

        # Split symbol
        clean = symbol.split(":")[0]
        parts = clean.split("/")
        base = parts[0] if len(parts) == 2 else clean
        quote = parts[1] if len(parts) == 2 else ""

        result.append({
            "symbol": symbol,
            "base": base,
            "quote": quote,
            "entry_price": entry_price,
            "current_price": current_price,
            "leverage": leverage,
            "margin": margin,
            "sl": sl,
            "tp": tp,
            "liq_price": liq_price,
            "unrealized_pnl": unrealized_pnl,
            "pnl_pct": pnl_pct,
            "opened_str": opened_str,
            "opened_short_str": opened_short_str,
            "opened_ts": opened_ts,
            "price_precision": pp,
            "pnl_class": "positive" if unrealized_pnl >= 0 else "negative",
            "prog_val": round(prog_val, 1),
            "prog_cls": prog_cls,
            "prog_label_l": prog_label_l,
            "prog_label_r": prog_label_r,
            "deducted_fee": deducted_fee,
            "break_even_price": break_even,
        })

    return result
