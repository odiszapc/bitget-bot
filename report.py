"""
HTML report generator: creates output/index.html with current bot snapshot.
"""

import os
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

OUTPUT_DIR = "output"


def generate_report(state: dict, exchange_positions: list[dict], current_balance: float, exchange=None):
    """Generate output/index.html with current stats and open positions."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    total_trades = state.get("total_trades", 0)
    total_wins = state.get("total_wins", 0)
    total_losses = state.get("total_losses", 0)
    win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0
    daily_pnl = state.get("daily_pnl", 0.0)
    total_pnl = state.get("total_pnl", 0.0)
    start_balance = state.get("start_balance", 0.0)
    positions = state.get("positions", {})

    # Build exchange position lookup: symbol -> unrealized_pnl, percentage
    exch_lookup = {}
    for ep in exchange_positions:
        exch_lookup[ep["symbol"]] = ep

    # Build position rows
    position_rows = ""
    total_unrealized = 0.0

    if positions:
        for symbol, pos in positions.items():
            entry_price = pos.get("entry_price", 0)
            margin = pos.get("margin_usdt", 0)
            sl = pos.get("current_sl") or pos.get("stop_loss", 0)
            tp = pos.get("take_profit", 0)

            # Override with live TP/SL: position fields first, then plan orders
            ep = exch_lookup.get(symbol, {})
            if ep.get("take_profit"):
                tp = ep["take_profit"]
            if ep.get("stop_loss"):
                sl = ep["stop_loss"]
            if exchange and (not tp or not sl):
                try:
                    tp_sl = exchange.get_tp_sl_for_symbol(symbol)
                    if not tp and tp_sl["tp"]:
                        tp = float(tp_sl["tp"])
                    if not sl and tp_sl["sl"]:
                        sl = float(tp_sl["sl"])
                except Exception:
                    pass

            opened_ts = pos.get("opened_at", 0)
            opened_str = datetime.fromtimestamp(opened_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M") if opened_ts else "-"

            unrealized_pnl = ep.get("unrealized_pnl", 0)
            pnl_pct = ep.get("percentage", 0)
            current_price = ep.get("mark_price", 0) or entry_price
            leverage = ep.get("leverage", 0)
            total_unrealized += unrealized_pnl

            pnl_class = "positive" if unrealized_pnl >= 0 else "negative"

            base, quote = _format_symbol(symbol)

            position_rows += f"""
            <tr>
                <td class="symbol">{_esc(base)}<span class="quote">/{_esc(quote)}</span></td>
                <td>{entry_price}</td>
                <td>{current_price}</td>
                <td>{leverage}x</td>
                <td>{margin:.2f}</td>
                <td>{sl if sl else '-'}</td>
                <td>{tp if tp else '-'}</td>
                <td class="{pnl_class}">{unrealized_pnl:+.4f}</td>
                <td class="{pnl_class}">{pnl_pct:+.2f}%</td>
                <td>{opened_str}</td>
            </tr>"""
    else:
        position_rows = '<tr><td colspan="10" class="empty">No open positions</td></tr>'

    unrealized_class = "positive" if total_unrealized >= 0 else "negative"
    daily_class = "positive" if daily_pnl >= 0 else "negative"
    total_class = "positive" if total_pnl >= 0 else "negative"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="refresh" content="60">
<title>Bitget Short Bot</title>
<style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
        font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
        background: #0d1117;
        color: #c9d1d9;
        padding: 24px;
        min-height: 100vh;
    }}
    h1 {{
        font-size: 20px;
        color: #58a6ff;
        margin-bottom: 4px;
    }}
    .updated {{
        font-size: 12px;
        color: #484f58;
        margin-bottom: 24px;
    }}
    .cards {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
        gap: 12px;
        margin-bottom: 28px;
    }}
    .card {{
        background: #161b22;
        border: 1px solid #21262d;
        border-radius: 8px;
        padding: 16px;
    }}
    .card .label {{
        font-size: 11px;
        color: #484f58;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        margin-bottom: 6px;
    }}
    .card .value {{
        font-size: 22px;
        font-weight: 700;
    }}
    .positive {{ color: #3fb950; }}
    .negative {{ color: #f85149; }}
    .neutral {{ color: #c9d1d9; }}
    h2 {{
        font-size: 15px;
        color: #8b949e;
        margin-bottom: 12px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }}
    table {{
        width: 100%;
        border-collapse: collapse;
        background: #161b22;
        border: 1px solid #21262d;
        border-radius: 8px;
        overflow: hidden;
    }}
    th {{
        background: #1c2128;
        color: #484f58;
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        padding: 10px 12px;
        text-align: left;
        font-weight: 600;
    }}
    td {{
        padding: 10px 12px;
        font-size: 13px;
        border-top: 1px solid #21262d;
    }}
    td.symbol {{
        color: #58a6ff;
        font-weight: 600;
    }}
    td.symbol .quote {{
        color: #484f58;
        font-weight: 400;
    }}
    td.empty {{
        text-align: center;
        color: #484f58;
        padding: 32px;
    }}
    tr:hover {{
        background: #1c2128;
    }}
    .footer {{
        margin-top: 32px;
        font-size: 11px;
        color: #30363d;
        text-align: center;
    }}
</style>
</head>
<body>

<h1>Bitget Short Bot</h1>
<div class="updated">Last updated: {now}</div>

<div class="cards">
    <div class="card">
        <div class="label">Balance</div>
        <div class="value neutral">{current_balance:.2f} <small style="font-size:12px;color:#484f58">USDT</small></div>
    </div>
    <div class="card">
        <div class="label">Start Balance</div>
        <div class="value neutral">{start_balance:.2f} <small style="font-size:12px;color:#484f58">USDT</small></div>
    </div>
    <div class="card">
        <div class="label">Unrealized PnL</div>
        <div class="value {unrealized_class}">{total_unrealized:+.4f} <small style="font-size:12px">USDT</small></div>
    </div>
    <div class="card">
        <div class="label">Daily PnL</div>
        <div class="value {daily_class}">{daily_pnl:+.4f} <small style="font-size:12px">USDT</small></div>
    </div>
    <div class="card">
        <div class="label">Total PnL</div>
        <div class="value {total_class}">{total_pnl:+.4f} <small style="font-size:12px">USDT</small></div>
    </div>
    <div class="card">
        <div class="label">Trades</div>
        <div class="value neutral">{total_trades}</div>
    </div>
    <div class="card">
        <div class="label">Win / Loss</div>
        <div class="value neutral">{total_wins} <small style="font-size:14px;color:#3fb950">W</small> / {total_losses} <small style="font-size:14px;color:#f85149">L</small></div>
    </div>
    <div class="card">
        <div class="label">Win Rate</div>
        <div class="value neutral">{win_rate:.1f}%</div>
    </div>
</div>

<h2>Open Positions ({len(positions)})</h2>
<table>
    <thead>
        <tr>
            <th>Symbol</th>
            <th>Entry</th>
            <th>Current</th>
            <th>Leverage</th>
            <th>Margin</th>
            <th>Stop Loss</th>
            <th>Take Profit</th>
            <th>PnL (USDT)</th>
            <th>PnL %</th>
            <th>Opened</th>
        </tr>
    </thead>
    <tbody>
        {position_rows}
    </tbody>
</table>

<div class="footer">Auto-refreshes every 60s</div>

</body>
</html>"""

    path = os.path.join(OUTPUT_DIR, "index.html")
    try:
        with open(path, "w") as f:
            f.write(html)
        logger.info(f"Report written to {path}")
    except IOError as e:
        logger.error(f"Error writing report: {e}")


def _format_symbol(symbol: str) -> tuple[str, str]:
    """
    Split 'GRT/USDT:USDT' into ('GRT', 'USDT').
    Strips the ':USDT' settlement suffix and splits on '/'.
    """
    clean = symbol.split(":")[0]  # 'GRT/USDT'
    parts = clean.split("/")
    if len(parts) == 2:
        return parts[0], parts[1]
    return clean, ""


def _esc(s: str) -> str:
    """Escape HTML special characters."""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
