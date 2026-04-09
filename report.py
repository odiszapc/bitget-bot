"""
HTML report generator: creates output/index.html with current bot snapshot.
"""

import os
import logging
from datetime import datetime, timezone
from positions import build_position_data

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
    start_balance = state.get("start_balance", 0.0)

    # Days since start_date
    start_date_str = state.get("start_date", "")
    start_date_display = ""
    days_since_start = 0
    if start_date_str:
        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            days_since_start = (now_dt - start_date).days
            start_date_display = start_date.strftime("%-d %b %Y")
        except ValueError:
            pass
    total_pnl = current_balance - start_balance if start_balance > 0 else 0.0
    total_pnl_pct = (total_pnl / start_balance * 100) if start_balance > 0 else 0.0
    positions = state.get("positions", {})

    # Config values for display
    cfg = cycle_info.get("config", {}) if cycle_info else {}
    leverage = cfg.get("leverage", 10)
    tp_roi = cfg.get("min_tp_pct", 0.2) * leverage
    sl_roi = cfg.get("min_stop_pct", 2.0) * leverage

    # Position sizing for display
    position_size_pct = cfg.get("position_size_pct", 50)
    max_positions = cfg.get("max_positions", 5)
    auto_margin_pct = position_size_pct / max_positions  # per-position margin %
    auto_exposure_pct = auto_margin_pct * leverage       # leveraged exposure %
    manual_margin_pct = 98
    manual_exposure_pct = manual_margin_pct * leverage

    # Build position data using shared module
    pos_data = build_position_data(exchange_positions, state, exchange)
    open_symbols = {p["symbol"] for p in pos_data}
    total_unrealized = sum(p["unrealized_pnl"] for p in pos_data)

    position_rows = ""
    position_modals = ""
    if pos_data:
        for pidx, p in enumerate(pos_data):
            pp = p["price_precision"]

            def _fmt_price(v, _pp=pp):
                return f"{v:.{_pp}f}" if v else "-"

            prog_bar_html = f"""<div class="prog-wrap"><div class="prog-labels"><span>{p['prog_label_l']}</span><span>{p['prog_label_r']}</span></div><div class="prog-track"><div class="prog-fill {p['prog_cls']}" style="width:{p['prog_val']:.1f}%"></div><div class="prog-thumb {p['prog_cls']}" style="left:{p['prog_val']:.1f}%"></div></div><div class="prog-pct {p['prog_cls']}">{p['prog_val']:.0f}%</div></div>"""

            pos_modal_id = f"pos-modal-{pidx}"
            position_rows += f"""
            <tr class="pos-row" onclick="document.getElementById('{pos_modal_id}').style.display='flex'">
                <td class="symbol">{_esc(p['base'])}<span class="quote">/{_esc(p['quote'])}</span></td>
                <td>{_fmt_price(p['entry_price'])}</td>
                <td>{_fmt_price(p['current_price'])}</td>
                <td>{p['leverage']:.0f}x</td>
                <td>{p['margin']:.2f}</td>
                <td>{_fmt_price(p['sl'])}</td>
                <td>{_fmt_price(p['tp'])}</td>
                <td class="liq-price">{_fmt_price(p['liq_price'])}</td>
                <td class="{p['pnl_class']}">{p['unrealized_pnl']:+.4f}</td>
                <td class="{p['pnl_class']}">{p['pnl_pct']:+.2f}%</td>
                <td>{p['opened_str']}</td>
                <td>{prog_bar_html}</td>
            </tr>"""

            # Build position modal with charts
            chart_map_ci = cycle_info.get("chart_map", {}) if cycle_info else {}
            pos_charts = chart_map_ci.get(p["symbol"], {})
            cache_bust_pos = int(now_dt.timestamp())
            pos_chart_imgs = ""
            for tf_label, tf_key in [("1 min", "1m"), ("15 min", "15m"), ("1 hour", "1h")]:
                src = pos_charts.get(tf_key, "")
                if src:
                    pos_chart_imgs += f'<div class="modal-chart"><div class="modal-chart-label">{tf_label}</div><img src="{_esc(src)}?t={cache_bust_pos}" alt="{_esc(p["base"])} {tf_label}"></div>\n'

            position_modals += f"""
<div class="modal-overlay" id="{pos_modal_id}" onclick="if(event.target===this)this.style.display='none'">
    <div class="modal-content">
        <div class="modal-header">
            <span class="modal-symbol">{_esc(p['base'])}<span class="quote">/{_esc(p['quote'])}</span></span>
            <span class="modal-close" onclick="this.closest('.modal-overlay').style.display='none'">&times;</span>
        </div>
        <div class="modal-stats">
            <div class="modal-stat"><span class="label">Entry</span><span>{_fmt_price(p['entry_price'])}</span></div>
            <div class="modal-stat"><span class="label">Current</span><span>{_fmt_price(p['current_price'])}</span></div>
            <div class="modal-stat"><span class="label">Leverage</span><span>{p['leverage']:.0f}x</span></div>
            <div class="modal-stat"><span class="label">Margin</span><span>{p['margin']:.2f}</span></div>
            <div class="modal-stat"><span class="label">PnL</span><span class="{p['pnl_class']}">{p['unrealized_pnl']:+.4f} ({p['pnl_pct']:+.2f}%)</span></div>
        </div>
        <div class="modal-stats">
            <div class="modal-stat"><span class="label">SL</span><span>{_fmt_price(p['sl'])}</span></div>
            <div class="modal-stat"><span class="label">TP</span><span>{_fmt_price(p['tp'])}</span></div>
            <div class="modal-stat"><span class="label">Liq</span><span class="liq-price">{_fmt_price(p['liq_price'])}</span></div>
            <div class="modal-stat"><span class="label">Opened</span><span>{p['opened_str']}</span></div>
        </div>
        <div class="modal-progress">{prog_bar_html}</div>
        <div class="modal-charts">
            {pos_chart_imgs if pos_chart_imgs else '<div class="empty">No charts available</div>'}
        </div>
    </div>
</div>"""
    else:
        position_rows = '<tr><td colspan="12" class="empty">No open positions</td></tr>'

    unrealized_class = "positive" if total_unrealized >= 0 else "negative"
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
        cycle_duration = cycle_info.get("cycle_duration", 0)

        # Build market indicators (OI + Volume)
        oi_changes = cycle_info.get("oi_changes", [])
        market_vol_ratio = cycle_info.get("market_volume_ratio", 1.0)
        oi_spike_threshold = cycle_info.get("config", {}).get("oi_spike_pct", 10.0)
        vol_spike_threshold = cycle_info.get("config", {}).get("market_volume_spike_multiplier", 3.0)

        indicators_html = ""
        if oi_changes or market_vol_ratio != 1.0:
            # Volume indicator
            vol_class = "negative" if market_vol_ratio >= vol_spike_threshold else "positive"
            indicators_html += f'<div class="indicator"><span class="indicator-label">Market Volume:</span> <span class="{vol_class}">{market_vol_ratio:.1f}x avg</span> <span class="muted">(limit: {vol_spike_threshold}x)</span></div>\n'

            # OI indicator
            if oi_changes:
                top_oi = sorted(oi_changes, key=lambda c: abs(c["oi_change_pct"]), reverse=True)[:5]
                oi_items = ""
                for c in top_oi:
                    sym = c["symbol"].split("/")[0]
                    pct = c["oi_change_pct"]
                    oi_cls = "negative" if abs(pct) >= oi_spike_threshold else ("warning" if abs(pct) >= oi_spike_threshold * 0.5 else "positive")
                    oi_items += f'<span class="oi-tag {oi_cls}">{_esc(sym)} {pct:+.1f}%</span> '
                avg_oi = sum(c["oi_change_pct"] for c in oi_changes) / len(oi_changes)
                avg_oi_cls = "negative" if abs(avg_oi) >= oi_spike_threshold else "positive"
                indicators_html += f'<div class="indicator"><span class="indicator-label">OI Changes:</span> {oi_items}</div>\n'
                indicators_html += f'<div class="indicator"><span class="indicator-label">OI Avg:</span> <span class="{avg_oi_cls}">{avg_oi:+.1f}%</span> <span class="muted">({len(oi_changes)} pairs, limit: {oi_spike_threshold}%)</span></div>\n'
            else:
                indicators_html += '<div class="indicator"><span class="indicator-label">OI:</span> <span class="muted">no data (first cycle)</span></div>\n'

        indicators_section = f'<div class="indicators">{indicators_html}</div>' if indicators_html else ""

        cycle_section = f"""
<div class="cycle-panel">
    <div class="cycle-header">
        <h2>Last Cycle</h2>
        <div class="cycle-time">{now}</div>
        <div class="cycle-time">{api_calls} api calls <span class="{api_class}">({api_rps:.2f}/sec, limit {api_limit}/sec)</span> | cycle {cycle_duration}s</div>
    </div>
    <div class="checks">{checks_html}</div>
    {indicators_section}
    <div class="outcome {outcome_class}">{_esc(outcome)}</div>
    <div class="countdown-row">
        <span class="countdown-label">Next cycle in</span>
        <span class="countdown" id="countdown">--:--</span>
    </div>
</div>
"""

    # Build recent shorts section (open positions + closed shorts)
    closes_section = ""
    if cycle_info:
        recent_closes = cycle_info.get("recent_closes", [])
        now_utc = datetime.now(timezone.utc)
        shorts_rows = ""

        # Open positions first (sorted newest → oldest)
        open_sorted = sorted(pos_data, key=lambda p: p.get("opened_ts", 0), reverse=True)
        # Calculate running balance: accumulate from oldest to newest, then display newest first
        open_by_oldest = sorted(pos_data, key=lambda p: p.get("opened_ts", 0))
        running = current_balance
        bal_map = {}
        for op in open_by_oldest:
            running += op["unrealized_pnl"]
            bal_map[op["symbol"]] = running
        for op in open_sorted:
            sym = _esc(op["base"])
            pnl = op["unrealized_pnl"]
            bal_str = f"{bal_map.get(op['symbol'], current_balance):.2f}"
            delta_str = f"{pnl:+.2f}"
            delta_cls = "positive" if pnl >= 0 else "negative"
            shorts_rows += f'<div class="close-row close-open"><span class="close-sym">{sym}</span><span class="close-bal close-bal-open">{bal_str}</span><span class="close-delta {delta_cls}">{delta_str}</span><span class="close-time">{op["opened_short_str"]}</span></div>\n'

        # Closed shorts
        for i, rc in enumerate(recent_closes):
            sym = _esc(rc["symbol"])
            bal = f"{rc['balance']:.2f}"
            dt = datetime.fromtimestamp(rc["timestamp"], tz=timezone.utc)
            time_str = dt.strftime("%b-%d %H:%M")
            if i == 0 and not pos_data:
                diff = now_utc - dt
                mins = int(diff.total_seconds() / 60)
                if mins < 60:
                    rel = f"{mins} min ago"
                elif mins < 1440:
                    rel = f"{mins // 60} h ago"
                else:
                    rel = f"{mins // 1440} d ago"
                time_str += f" ({rel})"

            if rc["delta"] is not None:
                delta_str = f"{rc['delta']:+.2f}"
                delta_cls = "positive" if rc["delta"] >= 0 else "negative"
            else:
                delta_str = "—"
                delta_cls = "muted"

            shorts_rows += f'<div class="close-row"><span class="close-sym">{sym}</span><span class="close-bal">{bal}</span><span class="close-delta {delta_cls}">{delta_str}</span><span class="close-time">{time_str}</span></div>\n'

        if shorts_rows:
            closes_section = f"""
<div class="closes-panel">
    <div class="section-header"><h2>Recent Shorts</h2><button class="refresh-btn" onclick="refreshShorts()" title="Refresh shorts"><svg class="refresh-icon" id="refresh-shorts-icon" viewBox="0 0 16 16" width="16" height="16"><path fill="currentColor" d="M8 3a5 5 0 1 0 4.546 2.914.5.5 0 0 1 .908-.418A6 6 0 1 1 8 2v1z"/><path fill="currentColor" d="M8 4.466V.534a.25.25 0 0 1 .41-.192l2.36 1.966c.12.1.12.284 0 .384L8.41 4.658A.25.25 0 0 1 8 4.466z"/></svg></button></div>
    <div class="close-rows" id="shorts-body">{shorts_rows}</div>
</div>
"""
        else:
            closes_section = """
<div class="closes-panel">
    <div class="section-header"><h2>Recent Shorts</h2><button class="refresh-btn" onclick="refreshShorts()" title="Refresh shorts"><svg class="refresh-icon" id="refresh-shorts-icon" viewBox="0 0 16 16" width="16" height="16"><path fill="currentColor" d="M8 3a5 5 0 1 0 4.546 2.914.5.5 0 0 1 .908-.418A6 6 0 1 1 8 2v1z"/><path fill="currentColor" d="M8 4.466V.534a.25.25 0 0 1 .41-.192l2.36 1.966c.12.1.12.284 0 .384L8.41 4.658A.25.25 0 0 1 8 4.466z"/></svg></button></div>
    <div class="close-rows" id="shorts-body"><div class="muted" style="padding:10px 0">No shorts yet</div></div>
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
            pos_dot = ' <span class="pos-dot"></span>' if sr["symbol"] in open_symbols else ""
            scan_rows += f"""
            <tr class="{row_class} scan-row" onclick="document.getElementById('{modal_id}').style.display='flex'"
                data-symbol="{_esc(base)}/{_esc(quote)}" data-1m="{d_1m}" data-15m="{d_15m}" data-1h="{d_1h}">
                <td class="symbol">{_esc(base)}<span class="quote">/{_esc(quote)}</span>{pos_dot}</td>
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
        <div class="modal-trade-row">
            <button class="short-btn" onclick="doShort('{_esc(sr['symbol'])}', this)">OPEN SHORT</button>
            <div class="trade-select">
                <span class="label">Bet</span>
                <select class="bet-pct-select" onchange="updateExposure(this, {leverage})">
                    <option value="5">5%</option>
                    <option value="10">10%</option>
                    <option value="20" selected>20%</option>
                    <option value="30">30%</option>
                    <option value="50">50%</option>
                    <option value="100">100%</option>
                </select>
            </div>
            <div class="trade-select">
                <span class="label">TP ROI</span>
                <select class="tp-roi-select">
                    <option value="1">1%</option>
                    <option value="2">2%</option>
                    <option value="3" selected>3%</option>
                    <option value="4">4%</option>
                    <option value="5">5%</option>
                    <option value="10">10%</option>
                </select>
            </div>
            <div class="trade-exposure">
                <span class="label">Exp</span>
                <span class="exposure-value">20%&times;{leverage}x={20 * leverage}%</span>
            </div>
        </div>
        <div class="modal-actions">
            <div class="short-result"></div>
        </div>
        <div class="modal-charts">
            {chart_imgs if chart_imgs else '<div class="empty">No charts available</div>'}
        </div>
    </div>
</div>"""

        modal_html = modals

        scan_section = f"""
<h2>Market Scan ({len(sr_list)} pairs) &mdash; Strategy: {_esc(act_strat)}</h2>
<div class="table-wrap">
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
</div>
<div style="height:28px"></div>
"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Bitget Short Bot</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><circle cx='16' cy='16' r='16' fill='%23f7931a'/><text x='16' y='22' text-anchor='middle' font-family='Arial,sans-serif' font-size='20' font-weight='bold' fill='white'>&#x20bf;</text></svg>">
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
        color: #6e7681;
        margin-bottom: 2px;
    }}
    .version {{
        font-size: 12px;
        color: #c9d1d9;
        font-weight: 600;
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
        color: #6e7681;
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
    .liq-price {{ color: #e8a735; }}
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
        color: #6e7681;
    }}
    th.strategy-active {{
        color: #58a6ff;
    }}
    .scan-dim td.symbol {{
        color: #6e7681;
    }}
    h2 {{
        font-size: 15px;
        color: #8b949e;
        margin-bottom: 12px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }}
    /* Progress bar */
    .prog-wrap {{
        min-width: 110px;
    }}
    .prog-labels {{
        display: flex;
        justify-content: space-between;
        font-size: 9px;
        color: #6e7681;
        margin-bottom: 3px;
        text-transform: uppercase;
        letter-spacing: 0.3px;
    }}
    .prog-track {{
        position: relative;
        height: 8px;
        background: #21262d;
        border-radius: 4px;
        overflow: visible;
    }}
    .prog-fill {{
        height: 100%;
        border-radius: 4px;
        transition: width 0.3s ease;
    }}
    .prog-fill.prog-positive {{
        background: linear-gradient(90deg, #238636, #3fb950);
    }}
    .prog-fill.prog-negative {{
        background: linear-gradient(90deg, #da3633, #f85149);
    }}
    .prog-thumb {{
        position: absolute;
        top: -3px;
        width: 3px;
        height: 14px;
        border-radius: 2px;
        transform: translateX(-1px);
    }}
    .prog-thumb.prog-positive {{
        background: #3fb950;
        box-shadow: 0 0 6px rgba(63, 185, 80, 0.5);
    }}
    .prog-thumb.prog-negative {{
        background: #f85149;
        box-shadow: 0 0 6px rgba(248, 81, 73, 0.5);
    }}
    .prog-pct {{
        font-size: 11px;
        font-weight: 700;
        margin-top: 3px;
        text-align: center;
    }}
    .prog-pct.prog-positive {{ color: #3fb950; }}
    .prog-pct.prog-negative {{ color: #f85149; }}
    .modal-progress {{
        margin-bottom: 16px;
        padding: 12px 14px;
        background: #13171e;
        border: 1px solid #30363d;
        border-radius: 8px;
    }}
    .modal-progress .prog-wrap {{
        min-width: unset;
    }}
    .modal-progress .prog-track {{
        height: 12px;
    }}
    .modal-progress .prog-thumb {{
        height: 18px;
        top: -3px;
    }}
    .modal-progress .prog-pct {{
        font-size: 14px;
    }}
    .section-header {{
        display: flex;
        align-items: center;
        gap: 10px;
        margin-bottom: 12px;
    }}
    .section-header h2 {{
        margin-bottom: 0;
    }}
    .refresh-btn {{
        background: none;
        border: 1px solid #30363d;
        border-radius: 6px;
        padding: 5px 7px;
        cursor: pointer;
        color: #6e7681;
        display: flex;
        align-items: center;
        transition: color 0.15s, border-color 0.15s;
    }}
    .refresh-btn:hover {{
        color: #58a6ff;
        border-color: #58a6ff;
    }}
    .refresh-icon {{
        transition: transform 0.3s;
    }}
    .refresh-icon.spinning {{
        animation: spin 0.8s linear infinite;
    }}
    .table-wrap {{
        overflow-x: auto;
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
        color: #6e7681;
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
        white-space: nowrap;
    }}
    td.symbol {{
        color: #58a6ff;
        font-weight: 600;
    }}
    td.symbol .quote {{
        color: #6e7681;
        font-weight: 400;
    }}
    td.empty {{
        text-align: center;
        color: #6e7681;
        padding: 32px;
    }}
    tr:hover {{
        background: #1c2128;
    }}
    .top-row {{
        display: flex;
        flex-wrap: wrap;
        gap: 16px;
        margin-bottom: 28px;
    }}
    .cycle-panel {{
        background: #161b22;
        border: 1px solid #21262d;
        border-radius: 8px;
        padding: 16px;
        flex: 1;
        min-width: 340px;
    }}
    .closes-panel {{
        background: #161b22;
        border: 1px solid #21262d;
        border-radius: 8px;
        padding: 16px;
        flex: 1;
        min-width: 340px;
    }}
    .closes-panel h2 {{
        margin-bottom: 12px;
    }}
    .close-row {{
        display: flex;
        align-items: baseline;
        gap: 0;
        padding: 4px 0;
        font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
        font-size: 13px;
        border-bottom: 1px solid #21262d;
    }}
    .close-row:last-child {{
        border-bottom: none;
    }}
    .close-open .close-sym {{
        color: #58a6ff;
    }}
    .close-bal-open {{
        color: #d29922 !important;
    }}
    .close-sym {{
        width: 70px;
        color: #c9d1d9;
        font-weight: 600;
    }}
    .close-bal {{
        width: 80px;
        text-align: right;
        color: #8b949e;
    }}
    .close-delta {{
        width: 70px;
        text-align: right;
        font-weight: 600;
    }}
    .close-time {{
        flex: 1;
        text-align: left;
        padding-left: 12px;
        color: #6e7681;
        font-size: 12px;
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
        color: #6e7681;
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
    .indicators {{
        margin: 10px 0;
        padding: 10px 0;
        border-top: 1px solid #21262d;
    }}
    .indicator {{
        font-size: 13px;
        padding: 3px 0;
        color: #8b949e;
    }}
    .indicator-label {{
        color: #8b949e;
        font-weight: 600;
    }}
    .oi-tag {{
        display: inline-block;
        padding: 1px 6px;
        border-radius: 4px;
        font-size: 12px;
        margin: 1px 2px;
        background: #161b22;
        border: 1px solid #30363d;
    }}
    .oi-tag.positive {{ color: #3fb950; border-color: #238636; }}
    .oi-tag.negative {{ color: #f85149; border-color: #da3633; }}
    .oi-tag.warning {{ color: #d29922; border-color: #9e6a03; }}
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
        color: #6e7681;
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
    .pos-row {{
        cursor: pointer;
    }}
    .pos-row:hover {{
        background: #1c2128 !important;
    }}
    .pos-dot {{
        display: inline-block;
        width: 8px;
        height: 8px;
        background: #d29922;
        border-radius: 50%;
        margin-left: 6px;
        vertical-align: middle;
        box-shadow: 0 0 6px rgba(210, 153, 34, 0.5);
        animation: dot-pulse 2s ease-in-out infinite;
    }}
    @keyframes dot-pulse {{
        0%, 100% {{ opacity: 1; box-shadow: 0 0 6px rgba(210, 153, 34, 0.5); }}
        50% {{ opacity: 0.6; box-shadow: 0 0 2px rgba(210, 153, 34, 0.3); }}
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
        color: #6e7681;
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
        color: #6e7681;
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
        color: #6e7681;
    }}
    .modal-trade-row {{
        display: flex;
        align-items: flex-end;
        gap: 12px;
        padding: 12px 14px;
        margin-bottom: 12px;
        background: #13171e;
        border: 1px solid #30363d;
        border-radius: 8px;
        flex-wrap: wrap;
    }}
    .trade-select {{
        display: flex;
        flex-direction: column;
        gap: 4px;
    }}
    .trade-select .label,
    .trade-exposure .label {{
        font-size: 10px;
        color: #6e7681;
        text-transform: uppercase;
        font-weight: 600;
        letter-spacing: 0.5px;
    }}
    .bet-pct-select,
    .tp-roi-select {{
        appearance: none;
        -webkit-appearance: none;
        background: #0d1117;
        color: #58a6ff;
        border: 1px solid #30363d;
        border-radius: 6px;
        padding: 7px 28px 7px 10px;
        font-family: inherit;
        font-size: 14px;
        font-weight: 700;
        cursor: pointer;
        background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M1 1l4 4 4-4' stroke='%236e7681' fill='none' stroke-width='1.5'/%3E%3C/svg%3E");
        background-repeat: no-repeat;
        background-position: right 8px center;
        transition: border-color 0.15s, box-shadow 0.15s;
    }}
    .bet-pct-select:hover,
    .tp-roi-select:hover {{
        border-color: #58a6ff;
    }}
    .bet-pct-select:focus,
    .tp-roi-select:focus {{
        outline: none;
        border-color: #58a6ff;
        box-shadow: 0 0 0 3px rgba(88, 166, 255, 0.15);
    }}
    .bet-pct-select option,
    .tp-roi-select option {{
        background: #161b22;
        color: #c9d1d9;
    }}
    .trade-exposure {{
        display: flex;
        flex-direction: column;
        gap: 4px;
        margin-left: auto;
    }}
    .exposure-value {{
        font-size: 13px;
        font-weight: 600;
        color: #6e7681;
    }}
    .modal-actions {{
        margin-bottom: 16px;
    }}
    .short-btn {{
        background: #da3633;
        color: #fff;
        border: none;
        border-radius: 6px;
        padding: 10px 20px;
        font-family: inherit;
        font-size: 13px;
        font-weight: 700;
        cursor: pointer;
        letter-spacing: 0.5px;
    }}
    .short-btn:hover {{
        background: #f85149;
    }}
    .short-btn:disabled {{
        cursor: default;
        opacity: 0.7;
    }}
    .short-btn.loading {{
        pointer-events: none;
        opacity: 0.7;
    }}
    .short-btn.success {{
        background: #238636;
    }}
    .short-btn .btn-spinner {{
        display: inline-block;
        width: 12px;
        height: 12px;
        border: 2px solid #fff;
        border-top-color: transparent;
        border-radius: 50%;
        animation: spin 0.8s linear infinite;
        vertical-align: middle;
        margin-right: 6px;
    }}
    .short-result {{
        font-size: 12px;
        margin-top: 8px;
        line-height: 1.5;
    }}
    .short-result.error {{
        color: #f85149;
    }}
    .short-result.ok {{
        color: #8b949e;
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
        color: #6e7681;
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
        color: #6e7681;
        text-transform: uppercase;
        margin-bottom: 2px;
    }}
    .preview-chart img {{
        width: 100%;
        border-radius: 4px;
        border: 1px solid #21262d;
    }}
    .spinner {{
        display: inline-block;
        width: 14px;
        height: 14px;
        border: 2px solid #3fb950;
        border-top-color: transparent;
        border-radius: 50%;
        animation: spin 0.8s linear infinite;
        vertical-align: middle;
        margin-left: 8px;
    }}
    @keyframes spin {{
        to {{ transform: rotate(360deg); }}
    }}
    .preview-empty {{
        font-size: 12px;
        color: #6e7681;
        text-align: center;
        padding: 24px 0;
    }}
</style>
</head>
<body>

<h1>Bitget Short Bot</h1>
<div class="updated">Last updated: {now}</div>
<div class="version">Ver: {_esc(_load_version())}</div>

<div class="cards">
    <div class="card">
        <div class="label">Balance</div>
        <div class="value neutral">{current_balance:.2f} <small style="font-size:12px;color:#6e7681">USDT</small></div>
    </div>
    <div class="card">
        <div class="label">Total PnL</div>
        <div class="value {total_class}">{total_pnl:+.2f} <small style="font-size:12px">USDT ({total_pnl_pct:+.1f}%)</small></div>
    </div>
    <div class="card">
        <div class="label">Trades</div>
        <div class="value neutral">{total_trades}{f' <small style="font-size:12px;color:#6e7681">(days: {days_since_start})</small>' if start_date_str else ""}</div>
    </div>
    <div class="card">
        <div class="label">Start Balance</div>
        <div class="value neutral">{start_balance:.2f} <small style="font-size:12px;color:#6e7681">USDT{f" ({start_date_display})" if start_date_display else ""}</small></div>
    </div>
    <div class="card">
        <div class="label">Unrealized PnL</div>
        <div class="value {unrealized_class}">{total_unrealized:+.2f} <small style="font-size:12px">USDT</small></div>
    </div>
    <div class="card card-settings">
        <div class="label">TP (ROI)</div>
        <div class="value positive">+{tp_roi:.1f}%</div>
    </div>
    <div class="card card-settings">
        <div class="label">SL (ROI)</div>
        <div class="value negative">-{sl_roi:.1f}%</div>
    </div>
    <div class="card card-settings">
        <div class="label">Auto Bet Size</div>
        <div class="value neutral">{auto_margin_pct:.0f}% <small style="font-size:12px;color:#6e7681">&times; {leverage}x = {auto_exposure_pct:.0f}%</small></div>
        <div style="font-size:11px;color:#6e7681;margin-top:4px">{position_size_pct:.0f}% / {max_positions} pos</div>
    </div>
</div>

<div class="section-header">
    <h2>Open Positions (<span id="pos-count">{len(pos_data)}</span>)</h2>
    <button class="refresh-btn" id="refresh-positions" onclick="refreshPositions()" title="Refresh positions">
        <svg class="refresh-icon" id="refresh-icon" viewBox="0 0 16 16" width="16" height="16"><path fill="currentColor" d="M8 3a5 5 0 1 0 4.546 2.914.5.5 0 0 1 .908-.418A6 6 0 1 1 8 2v1z"/><path fill="currentColor" d="M8 4.466V.534a.25.25 0 0 1 .41-.192l2.36 1.966c.12.1.12.284 0 .384L8.41 4.658A.25.25 0 0 1 8 4.466z"/></svg>
    </button>
</div>
<div class="table-wrap">
<table id="positions-table">
    <thead>
        <tr>
            <th>Symbol</th>
            <th>Entry</th>
            <th>Current</th>
            <th>Lev</th>
            <th>Margin</th>
            <th>SL</th>
            <th>TP</th>
            <th>Liq</th>
            <th>PnL</th>
            <th>PnL %</th>
            <th>Opened</th>
            <th style="min-width:120px">Progress</th>
        </tr>
    </thead>
    <tbody id="positions-body">
        {position_rows}
    </tbody>
</table>
</div>
<div style="height:28px"></div>

<div class="top-row">
{cycle_section}
{closes_section}
</div>

{scan_section}

<div class="footer">Bitget Short Bot</div>

<div class="preview-panel" id="preview-panel">
    <div class="preview-symbol" id="preview-symbol"></div>
    <div class="preview-charts" id="preview-charts"></div>
</div>

{modal_html}
{position_modals}

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
            el.innerHTML = 'waiting for update...<span class="spinner"></span>';
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

// Update exposure label when bet % changes
function updateExposure(sel, leverage) {{
    var pct = parseInt(sel.value);
    var exposure = pct * leverage;
    var row = sel.closest(".modal-trade-row");
    var label = row.querySelector(".exposure-value");
    label.innerHTML = pct + "%&times;" + leverage + "x=" + exposure + "%";
}}

// Manual SHORT button
function doShort(symbol, btn) {{
    var row = btn.closest(".modal-trade-row");
    var betSelect = row.querySelector(".bet-pct-select");
    var tpSelect = row.querySelector(".tp-roi-select");
    var betPct = betSelect ? parseInt(betSelect.value) : 20;
    var tpRoi = tpSelect ? parseFloat(tpSelect.value) : 3;

    var modal = btn.closest(".modal-content");
    var resultEl = modal.querySelector(".short-result");
    var originalText = btn.textContent;
    btn.disabled = true;
    btn.classList.add("loading");
    btn.innerHTML = '<span class="btn-spinner"></span>Opening...';
    resultEl.textContent = "";
    resultEl.className = "short-result";

    var apiUrl = window.location.protocol + "//" + window.location.hostname + ":8432/api/short";
    fetch(apiUrl, {{
        method: "POST",
        headers: {{"Content-Type": "application/json"}},
        body: JSON.stringify({{symbol: symbol, bet_pct: betPct, tp_roi_pct: tpRoi}})
    }})
    .then(function(r) {{ return r.json(); }})
    .then(function(data) {{
        btn.classList.remove("loading");
        if (data.ok) {{
            // Close the modal, refresh positions and shorts
            var overlay = btn.closest(".modal-overlay");
            if (overlay) overlay.style.display = "none";
            refreshPositions();
            refreshShorts();
        }} else {{
            btn.disabled = false;
            btn.textContent = originalText;
            resultEl.className = "short-result error";
            resultEl.textContent = data.error || "Unknown error";
        }}
    }})
    .catch(function(e) {{
        btn.classList.remove("loading");
        btn.disabled = false;
        btn.textContent = originalText;
        resultEl.className = "short-result error";
        resultEl.textContent = "Network error: " + e.message;
    }});
}}

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

// Refresh positions table
function refreshPositions() {{
    var icon = document.getElementById("refresh-icon");
    icon.classList.add("spinning");

    var apiUrl = window.location.protocol + "//" + window.location.hostname + ":8432/api/positions";
    fetch(apiUrl)
    .then(function(r) {{ return r.json(); }})
    .then(function(data) {{
        icon.classList.remove("spinning");
        if (!data.ok) return;

        var tbody = document.getElementById("positions-body");
        var countEl = document.getElementById("pos-count");
        var positions = data.positions;
        countEl.textContent = positions.length;

        if (positions.length === 0) {{
            tbody.innerHTML = '<tr><td colspan="12" class="empty">No open positions</td></tr>';
            return;
        }}

        var html = "";
        for (var i = 0; i < positions.length; i++) {{
            var p = positions[i];
            var pp = p.price_precision || 2;
            var pnlCls = p.pnl_class || "neutral";

            function fmtP(v) {{
                return v ? v.toFixed(pp) : "-";
            }}

            // Progress bar
            var progHtml = '<div class="prog-wrap">' +
                '<div class="prog-labels"><span>' + (p.prog_label_l || "") + '</span><span>' + (p.prog_label_r || "") + '</span></div>' +
                '<div class="prog-track"><div class="prog-fill ' + p.prog_cls + '" style="width:' + p.prog_val + '%"></div>' +
                '<div class="prog-thumb ' + p.prog_cls + '" style="left:' + p.prog_val + '%"></div></div>' +
                '<div class="prog-pct ' + p.prog_cls + '">' + Math.round(p.prog_val) + '%</div></div>';

            html += '<tr class="pos-row">' +
                '<td class="symbol">' + p.base + '<span class="quote">/' + p.quote + '</span></td>' +
                '<td>' + fmtP(p.entry_price) + '</td>' +
                '<td>' + fmtP(p.current_price) + '</td>' +
                '<td>' + p.leverage.toFixed(0) + 'x</td>' +
                '<td>' + p.margin.toFixed(2) + '</td>' +
                '<td>' + fmtP(p.sl) + '</td>' +
                '<td>' + fmtP(p.tp) + '</td>' +
                '<td class="liq-price">' + fmtP(p.liq_price) + '</td>' +
                '<td class="' + pnlCls + '">' + (p.unrealized_pnl >= 0 ? "+" : "") + p.unrealized_pnl.toFixed(4) + '</td>' +
                '<td class="' + pnlCls + '">' + (p.pnl_pct >= 0 ? "+" : "") + p.pnl_pct.toFixed(2) + '%</td>' +
                '<td>' + p.opened_str + '</td>' +
                '<td>' + progHtml + '</td>' +
                '</tr>';
        }}
        tbody.innerHTML = html;
    }})
    .catch(function(e) {{
        icon.classList.remove("spinning");
        console.error("Refresh error:", e);
    }});
}}

// Refresh Recent Shorts panel
function refreshShorts() {{
    var icon = document.getElementById("refresh-shorts-icon");
    icon.classList.add("spinning");

    var apiUrl = window.location.protocol + "//" + window.location.hostname + ":8432/api/shorts";
    fetch(apiUrl)
    .then(function(r) {{ return r.json(); }})
    .then(function(data) {{
        icon.classList.remove("spinning");
        if (!data.ok) return;

        var container = document.getElementById("shorts-body");
        var positions = data.positions || [];
        var closes = data.recent_closes || [];
        var balance = data.balance || 0;
        var html = "";

        // Open positions: sort newest first, calculate running balance from oldest
        var sorted = positions.slice().sort(function(a,b) {{ return (a.opened_ts||0) - (b.opened_ts||0); }});
        var runBal = balance;
        var balMap = {{}};
        for (var k = 0; k < sorted.length; k++) {{
            runBal += sorted[k].unrealized_pnl;
            balMap[sorted[k].symbol] = runBal;
        }}
        // Display newest first
        var newest = positions.slice().sort(function(a,b) {{ return (b.opened_ts||0) - (a.opened_ts||0); }});
        for (var i = 0; i < newest.length; i++) {{
            var p = newest[i];
            var bVal = (balMap[p.symbol] || balance).toFixed(2);
            var cls = p.unrealized_pnl >= 0 ? "positive" : "negative";
            var delta = (p.unrealized_pnl >= 0 ? "+" : "") + p.unrealized_pnl.toFixed(2);
            html += '<div class="close-row close-open"><span class="close-sym">' + p.base + '</span><span class="close-bal close-bal-open">' + bVal + '</span><span class="close-delta ' + cls + '">' + delta + '</span><span class="close-time">' + (p.opened_short_str || p.opened_str) + '</span></div>';
        }}

        // Closed shorts
        for (var j = 0; j < closes.length; j++) {{
            var c = closes[j];
            var dCls = "muted";
            var dStr = "\u2014";
            if (c.delta !== null) {{
                dCls = c.delta >= 0 ? "positive" : "negative";
                dStr = (c.delta >= 0 ? "+" : "") + c.delta.toFixed(2);
            }}
            var dt = new Date(c.timestamp * 1000);
            var timeStr = dt.toLocaleDateString("en", {{month:"short",day:"2-digit"}}) + " " + dt.toLocaleTimeString("en", {{hour:"2-digit",minute:"2-digit",hour12:false}});
            html += '<div class="close-row"><span class="close-sym">' + c.symbol + '</span><span class="close-bal">' + c.balance.toFixed(2) + '</span><span class="close-delta ' + dCls + '">' + dStr + '</span><span class="close-time">' + timeStr + '</span></div>';
        }}

        container.innerHTML = html || '<div class="muted" style="padding:10px 0">No shorts yet</div>';
    }})
    .catch(function(e) {{
        icon.classList.remove("spinning");
        console.error("Shorts refresh error:", e);
    }});
}}
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
