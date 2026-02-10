"""
HTML report generator: creates output/index.html with current bot snapshot.
"""

import os
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

OUTPUT_DIR = "output"


def _load_version() -> str:
    try:
        with open("version.txt", "r") as f:
            return f.read().strip()
    except FileNotFoundError:
        return "unknown"


def generate_report(state: dict, exchange_positions: list[dict], current_balance: float, exchange=None, cycle_info: dict = None):
    """Generate output/index.html with current stats and open positions."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    now_dt = datetime.now(timezone.utc)
    now = now_dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    now_iso = now_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    total_trades = state.get("total_trades", 0)
    total_wins = state.get("total_wins", 0)
    total_losses = state.get("total_losses", 0)
    win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0
    daily_pnl = state.get("daily_pnl", 0.0)
    total_pnl = state.get("total_pnl", 0.0)
    start_balance = state.get("start_balance", 0.0)
    positions = state.get("positions", {})

    # Config values for display
    cfg = cycle_info.get("config", {}) if cycle_info else {}
    leverage = cfg.get("leverage", 10)
    tp_roi = cfg.get("min_tp_pct", 0.2) * leverage
    sl_roi = cfg.get("min_stop_pct", 2.0) * leverage

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

    # Build cycle info section
    cycle_section = ""
    cycle_minutes_js = 15
    if cycle_info:
        cycle_minutes_js = cycle_info.get("cycle_minutes", 15)
        checks = cycle_info.get("checks", [])
        outcome = cycle_info.get("outcome", "")

        checks_html = ""
        for check in checks:
            if check.startswith("✅"):
                checks_html += f'<div class="check pass">{_esc(check)}</div>\n'
            elif check.startswith("❌"):
                checks_html += f'<div class="check fail">{_esc(check)}</div>\n'
            else:
                checks_html += f'<div class="check">{_esc(check)}</div>\n'

        outcome_class = "negative" if "fail" in outcome.lower() or "error" in outcome.lower() else "positive"

        api_calls = cycle_info.get("api_calls", 0)
        api_rps = api_calls / (cycle_minutes_js * 60) if cycle_minutes_js > 0 else 0
        api_limit = 20
        api_class = "negative" if api_rps > api_limit * 0.8 else "positive"

        cycle_section = f"""
<div class="cycle-panel">
    <div class="cycle-header">
        <h2>Last Cycle</h2>
        <div class="cycle-time">{now}</div>
        <div class="cycle-time">{api_calls} api calls <span class="{api_class}">({api_rps:.2f}/sec, limit {api_limit}/sec)</span></div>
    </div>
    <div class="checks">{checks_html}</div>
    <div class="outcome {outcome_class}">{_esc(outcome)}</div>
    <div class="countdown-row">
        <span class="countdown-label">Next cycle in</span>
        <span class="countdown" id="countdown">--:--</span>
    </div>
</div>
"""

    # Build market scan section
    scan_section = ""
    modal_html = ""
    if cycle_info and cycle_info.get("scan_results"):
        sr_list = cycle_info["scan_results"]
        min_signals = 3
        act_strat = cycle_info.get("active_strategy", "volume")
        chart_map = cycle_info.get("chart_map", {})

        scan_rows = ""
        modals = ""
        for idx, sr in enumerate(sr_list):
            sc = sr["signal_count"]
            if sc >= 3:
                count_class = "positive"
                row_class = "best-candidate" if idx == 0 else "scan-hot"
            elif sc == 2:
                count_class = "warning"
                row_class = ""
            elif sc == 1:
                count_class = "neutral"
                row_class = ""
            else:
                count_class = "muted"
                row_class = "scan-dim"

            base, quote = _format_symbol(sr["symbol"])
            fr = sr.get("funding_rate", 0)

            rsi_class = "positive" if sr["rsi"] > 70 else ("warning" if sr["rsi"] > 60 else "")

            # Build strategy columns
            def _strat_cell(name):
                s = sr.get(name, {})
                cnt = s.get("signal_count", 0)
                mx = s.get("max_signals", 4)
                sigs = ", ".join(s.get("signals", []))
                if cnt >= 3:
                    cls = "positive"
                elif cnt == 2:
                    cls = "warning"
                elif cnt == 1:
                    cls = "neutral"
                else:
                    cls = "muted"
                return f'<td class="{cls}">{cnt}/{mx} <small>{_esc(sigs)}</small></td>'

            classic_cell = _strat_cell("classic")
            volume_cell = _strat_cell("volume")

            modal_id = f"modal-{idx}"
            # Chart URLs for preview panel (data attributes)
            preview_charts = chart_map.get(sr["symbol"], {})
            cache_bust = int(now_dt.timestamp())
            d_1m = f'{preview_charts["1m"]}?t={cache_bust}' if "1m" in preview_charts else ""
            d_15m = f'{preview_charts["15m"]}?t={cache_bust}' if "15m" in preview_charts else ""
            d_1h = f'{preview_charts["1h"]}?t={cache_bust}' if "1h" in preview_charts else ""
            scan_rows += f"""
            <tr class="{row_class} scan-row" onclick="document.getElementById('{modal_id}').style.display='flex'"
                data-symbol="{_esc(base)}/{_esc(quote)}" data-1m="{d_1m}" data-15m="{d_15m}" data-1h="{d_1h}">
                <td class="symbol">{_esc(base)}<span class="quote">/{_esc(quote)}</span></td>
                <td class="{rsi_class}">{sr['rsi']:.1f}</td>
                <td>{sr['atr_pct']:.1f}%</td>
                <td>{fr*100:.4f}%</td>
                {classic_cell}
                {volume_cell}
            </tr>"""

            # Build modal for this symbol
            charts = chart_map.get(sr["symbol"], {})
            chart_imgs = ""
            cache_bust = int(now_dt.timestamp())
            for tf_label, tf_key in [("1 min", "1m"), ("15 min", "15m"), ("1 hour", "1h")]:
                src = charts.get(tf_key, "")
                if src:
                    chart_imgs += f'<div class="modal-chart"><div class="modal-chart-label">{tf_label}</div><img src="{_esc(src)}?t={cache_bust}" alt="{_esc(base)} {tf_label}"></div>\n'

            # Strategy details for modal
            classic_data = sr.get("classic", {})
            volume_data = sr.get("volume", {})
            c_sigs = ", ".join(classic_data.get("signals", [])) or "-"
            v_sigs = ", ".join(volume_data.get("signals", [])) or "-"

            modals += f"""
<div class="modal-overlay" id="{modal_id}" onclick="if(event.target===this)this.style.display='none'">
    <div class="modal-content">
        <div class="modal-header">
            <span class="modal-symbol">{_esc(base)}<span class="quote">/{_esc(quote)}</span></span>
            <span class="modal-close" onclick="this.closest('.modal-overlay').style.display='none'">&times;</span>
        </div>
        <div class="modal-stats">
            <div class="modal-stat"><span class="label">RSI</span><span class="{rsi_class}">{sr['rsi']:.1f}</span></div>
            <div class="modal-stat"><span class="label">ATR</span><span>{sr['atr_pct']:.1f}%</span></div>
            <div class="modal-stat"><span class="label">Funding</span><span>{fr*100:.4f}%</span></div>
            <div class="modal-stat"><span class="label">Classic</span><span>{classic_data.get('signal_count',0)}/{classic_data.get('max_signals',4)}</span></div>
            <div class="modal-stat"><span class="label">Volume</span><span>{volume_data.get('signal_count',0)}/{volume_data.get('max_signals',4)}</span></div>
        </div>
        <div class="modal-signals">
            <div><small>Classic:</small> {_esc(c_sigs)}</div>
            <div><small>Volume:</small> {_esc(v_sigs)}</div>
        </div>
        <div class="modal-charts">
            {chart_imgs if chart_imgs else '<div class="empty">No charts available</div>'}
        </div>
    </div>
</div>"""

        modal_html = modals

        scan_section = f"""
<h2>Market Scan ({len(sr_list)} pairs) &mdash; Strategy: {_esc(act_strat)}</h2>
<table>
    <thead>
        <tr>
            <th>Symbol</th>
            <th>RSI</th>
            <th>ATR</th>
            <th>Funding</th>
            <th{"" if act_strat != "classic" else ' class="strategy-active"'}>Classic</th>
            <th{"" if act_strat != "volume" else ' class="strategy-active"'}>Volume</th>
        </tr>
    </thead>
    <tbody>
        {scan_rows}
    </tbody>
</table>
<div style="height:28px"></div>
"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
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
        margin-bottom: 2px;
    }}
    .version {{
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
    .card-settings {{
        background: #13171e;
        border-style: dashed;
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
    .warning {{ color: #d29922; }}
    .neutral {{ color: #c9d1d9; }}
    .muted {{ color: #30363d; }}
    .best-candidate {{
        background: #1a2233;
        border-left: 3px solid #58a6ff;
    }}
    .scan-hot {{
        background: #1a2a1a;
    }}
    .scan-dim td {{
        color: #484f58;
    }}
    th.strategy-active {{
        color: #58a6ff;
    }}
    .scan-dim td.symbol {{
        color: #484f58;
    }}
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
    .cycle-panel {{
        background: #161b22;
        border: 1px solid #21262d;
        border-radius: 8px;
        padding: 16px;
        margin-bottom: 28px;
    }}
    .cycle-header {{
        display: flex;
        align-items: baseline;
        gap: 12px;
        margin-bottom: 12px;
    }}
    .cycle-header h2 {{
        margin-bottom: 0;
    }}
    .cycle-time {{
        font-size: 12px;
        color: #484f58;
    }}
    .checks {{
        margin-bottom: 10px;
    }}
    .check {{
        font-size: 13px;
        padding: 3px 0;
        color: #8b949e;
    }}
    .check.pass {{
        color: #3fb950;
    }}
    .check.fail {{
        color: #f85149;
    }}
    .outcome {{
        font-size: 13px;
        font-weight: 600;
        padding: 8px 0;
        border-top: 1px solid #21262d;
    }}
    .countdown-row {{
        display: flex;
        align-items: baseline;
        gap: 8px;
        padding-top: 10px;
        border-top: 1px solid #21262d;
        margin-top: 8px;
    }}
    .countdown-label {{
        font-size: 12px;
        color: #484f58;
    }}
    .countdown {{
        font-size: 20px;
        font-weight: 700;
        color: #58a6ff;
    }}
    .scan-row {{
        cursor: pointer;
    }}
    .scan-row:hover {{
        background: #1c2128 !important;
    }}
    .footer {{
        margin-top: 32px;
        font-size: 11px;
        color: #30363d;
        text-align: center;
    }}
    .modal-overlay {{
        display: none;
        position: fixed;
        top: 0; left: 0; right: 0; bottom: 0;
        background: rgba(0,0,0,0.75);
        z-index: 100;
        align-items: center;
        justify-content: center;
    }}
    .modal-content {{
        background: #161b22;
        border: 1px solid #21262d;
        border-radius: 12px;
        padding: 24px;
        max-width: 720px;
        width: 90%;
        max-height: 90vh;
        overflow-y: auto;
    }}
    .modal-header {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 16px;
    }}
    .modal-symbol {{
        font-size: 20px;
        font-weight: 700;
        color: #58a6ff;
    }}
    .modal-close {{
        font-size: 28px;
        color: #484f58;
        cursor: pointer;
        line-height: 1;
    }}
    .modal-close:hover {{
        color: #c9d1d9;
    }}
    .modal-stats {{
        display: flex;
        gap: 16px;
        flex-wrap: wrap;
        margin-bottom: 12px;
    }}
    .modal-stat {{
        display: flex;
        flex-direction: column;
        gap: 2px;
    }}
    .modal-stat .label {{
        font-size: 10px;
        color: #484f58;
        text-transform: uppercase;
    }}
    .modal-stat span:last-child {{
        font-size: 15px;
        font-weight: 600;
    }}
    .modal-signals {{
        font-size: 12px;
        color: #8b949e;
        margin-bottom: 16px;
        line-height: 1.6;
    }}
    .modal-signals small {{
        color: #484f58;
    }}
    .modal-charts {{
        display: flex;
        flex-direction: column;
        gap: 12px;
    }}
    .modal-chart img {{
        width: 100%;
        border-radius: 6px;
        border: 1px solid #21262d;
    }}
    .modal-chart-label {{
        font-size: 11px;
        color: #484f58;
        text-transform: uppercase;
        margin-bottom: 4px;
    }}
    /* Preview panel (hover) */
    .preview-panel {{
        display: none;
        position: fixed;
        right: 16px;
        top: 50%;
        transform: translateY(-50%);
        width: 340px;
        background: #161b22;
        border: 1px solid #21262d;
        border-radius: 10px;
        padding: 14px;
        z-index: 50;
        box-shadow: 0 8px 32px rgba(0,0,0,0.5);
    }}
    .preview-panel.visible {{
        display: block;
    }}
    .preview-symbol {{
        font-size: 14px;
        font-weight: 700;
        color: #58a6ff;
        margin-bottom: 10px;
    }}
    .preview-charts {{
        display: flex;
        flex-direction: column;
        gap: 8px;
    }}
    .preview-chart-label {{
        font-size: 10px;
        color: #484f58;
        text-transform: uppercase;
        margin-bottom: 2px;
    }}
    .preview-chart img {{
        width: 100%;
        border-radius: 4px;
        border: 1px solid #21262d;
    }}
    .preview-empty {{
        font-size: 12px;
        color: #484f58;
        text-align: center;
        padding: 24px 0;
    }}
</style>
</head>
<body>

<h1>Bitget Short Bot</h1>
<div class="updated">Last updated: {now}</div>
<div class="version">{_esc(_load_version())}</div>

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
    <div class="card card-settings">
        <div class="label">TP (ROI)</div>
        <div class="value positive">+{tp_roi:.1f}%</div>
    </div>
    <div class="card card-settings">
        <div class="label">SL (ROI)</div>
        <div class="value negative">-{sl_roi:.1f}%</div>
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
<div style="height:28px"></div>

{cycle_section}

{scan_section}

<div class="footer">Bitget Short Bot</div>

<div class="preview-panel" id="preview-panel">
    <div class="preview-symbol" id="preview-symbol"></div>
    <div class="preview-charts" id="preview-charts"></div>
</div>

{modal_html}

<script>
(function() {{
    var cycleMinutes = {cycle_minutes_js};
    var generatedAt = new Date("{now_iso}");
    var nextCycle = new Date(generatedAt.getTime() + cycleMinutes * 60 * 1000);
    var el = document.getElementById("countdown");
    if (!el) return;
    var refreshTimer = null;
    function tick() {{
        var diff = Math.floor((nextCycle - Date.now()) / 1000);
        if (diff <= 0) {{
            el.textContent = "waiting for update...";
            el.style.color = "#3fb950";
            if (!refreshTimer) {{
                refreshTimer = setInterval(function() {{
                    location.reload();
                }}, 5000);
            }}
            return;
        }}
        var m = Math.floor(diff / 60);
        var s = diff % 60;
        el.textContent = String(m).padStart(2, "0") + ":" + String(s).padStart(2, "0");
    }}
    tick();
    setInterval(tick, 1000);
}})();
document.addEventListener("keydown", function(e) {{
    if (e.key === "Escape") {{
        var modals = document.querySelectorAll(".modal-overlay");
        modals.forEach(function(m) {{ m.style.display = "none"; }});
    }}
}});

// Preview panel on hover
(function() {{
    var panel = document.getElementById("preview-panel");
    var symEl = document.getElementById("preview-symbol");
    var chartsEl = document.getElementById("preview-charts");
    if (!panel) return;

    var rows = document.querySelectorAll(".scan-row");
    rows.forEach(function(row) {{
        row.addEventListener("mouseenter", function() {{
            var symbol = row.getAttribute("data-symbol") || "";
            var tfs = [
                ["1 min", row.getAttribute("data-1m")],
                ["15 min", row.getAttribute("data-15m")],
                ["1 hour", row.getAttribute("data-1h")]
            ];
            symEl.textContent = symbol;
            chartsEl.innerHTML = "";
            var hasAny = false;
            tfs.forEach(function(tf) {{
                if (tf[1]) {{
                    hasAny = true;
                    var div = document.createElement("div");
                    div.className = "preview-chart";
                    div.innerHTML = '<div class="preview-chart-label">' + tf[0] + '</div><img src="' + tf[1] + '">';
                    chartsEl.appendChild(div);
                }}
            }});
            if (!hasAny) {{
                chartsEl.innerHTML = '<div class="preview-empty">No charts</div>';
            }}
            panel.classList.add("visible");
        }});
        row.addEventListener("mouseleave", function() {{
            panel.classList.remove("visible");
        }});
    }});
}})();
</script>

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
