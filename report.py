"""
HTML report generator: creates output/index.html with current bot snapshot.
"""

import os
import logging
from datetime import datetime, timezone
from positions import build_position_data

logger = logging.getLogger(__name__)

OUTPUT_DIR = "output"
APPLE_TOUCH_ICON_FILENAME = "apple-touch-icon.png"


def _load_version() -> str:
    try:
        with open("version.txt", "r") as f:
            return f.read().strip()
    except FileNotFoundError:
        return "unknown"


def _ensure_apple_touch_icon() -> None:
    """Generate output/apple-touch-icon.png (180x180) once if missing.

    iOS "Add to Home Screen" uses this PNG instead of the SVG favicon.
    Idempotent: skips if file already exists.
    """
    icon_path = os.path.join(OUTPUT_DIR, APPLE_TOUCH_ICON_FILENAME)
    if os.path.exists(icon_path):
        return
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        # 360x360 px (2x for retina sharpness; iOS accepts any size and scales)
        fig = plt.figure(figsize=(1.8, 1.8), dpi=200, facecolor="#0d1117")
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set_facecolor("#0d1117")
        # Thai Baht "฿" (U+0E3F) in DejaVu Sans — visually identical to Bitcoin ₿,
        # which is missing from the bundled font. iOS clips to a rounded square,
        # so leave ~12% safe padding around the glyph.
        ax.text(0.5, 0.5, "\u0e3f", fontsize=110, fontweight="bold",
                color="#f7931a", ha="center", va="center",
                family="DejaVu Sans")
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")
        fig.savefig(icon_path, facecolor="#0d1117", dpi=200)
        plt.close(fig)
        logger.info(f"Generated apple-touch-icon at {icon_path}")
    except Exception as e:
        logger.warning(f"Failed to generate apple-touch-icon: {e}")


def generate_report(state: dict, exchange_positions: list[dict], current_balance: float, exchange=None, cycle_info: dict = None):
    """Generate output/index.html with current stats and open positions."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    _ensure_apple_touch_icon()

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
    auto_tp_roi = cfg.get("auto_tp_roi_pct", 3.0)
    taker_rate = 0.001
    auto_margin_pct = position_size_pct / max_positions  # per-position margin %
    auto_exposure_pct = auto_margin_pct * leverage       # leveraged exposure %
    manual_margin_pct = 98
    manual_exposure_pct = manual_margin_pct * leverage

    # Build position data using shared module
    pos_data = build_position_data(exchange_positions, state, exchange)
    open_symbols = {p["symbol"] for p in pos_data}
    total_unrealized = sum(p["unrealized_pnl"] for p in pos_data)

    # Estimated balance if all positions hit TP
    est_tp_net = 0.0
    for p in pos_data:
        tp = p.get("tp", 0)
        if tp > 0 and p.get("entry_price", 0) > 0:
            contracts = p.get("margin", 0) * p.get("leverage", 10) / p.get("entry_price", 1)
            gross = (p["entry_price"] - tp) * contracts
            close_fee = tp * contracts * 0.001
            est_tp_net += gross - close_fee
    wallet_balance = current_balance - total_unrealized  # total includes unrealized
    est_balance_at_tp = wallet_balance + est_tp_net

    position_rows = ""
    position_modals = ""
    if pos_data:
        for pidx, p in enumerate(pos_data):
            pp = p["price_precision"]

            def _fmt_price(v, _pp=pp):
                return f"{v:.{_pp}f}" if v else "-"

            prog_tooltip = f"{p['prog_label_l']} ← {p['prog_val']:.0f}% → {p['prog_label_r']}"
            prog_bar_inline = f'<div class="prog-track prog-inline" title="{prog_tooltip}"><div class="prog-fill {p["prog_cls"]}" style="width:{p["prog_val"]:.1f}%"></div></div>'

            margin_pct = (p['margin'] / current_balance * 100) if current_balance > 0 else 0

            # Estimated net profit at TP
            _tp = p.get("tp", 0)
            if _tp > 0 and p.get("entry_price", 0) > 0:
                _contracts = p["margin"] * p.get("leverage", 10) / p["entry_price"]
                _gross = (p["entry_price"] - _tp) * _contracts
                _close_fee = _tp * _contracts * 0.001
                _est_tp = _gross - _close_fee
            else:
                _est_tp = 0

            pos_modal_id = f"pos-modal-{pidx}"
            chart_map_ci = cycle_info.get("chart_map", {}) if cycle_info else {}
            pos_ch = chart_map_ci.get(p["symbol"], {})
            cb = int(now_dt.timestamp())
            p_1m = f'{pos_ch["1m"]}?t={cb}' if "1m" in pos_ch else ""
            p_15m = f'{pos_ch["15m"]}?t={cb}' if "15m" in pos_ch else ""
            p_1h = f'{pos_ch["1h"]}?t={cb}' if "1h" in pos_ch else ""
            position_rows += f"""
            <tr class="pos-row scan-row" onclick="document.getElementById('{pos_modal_id}').style.display='flex'"
                data-symbol="{_esc(p['base'])}/{_esc(p['quote'])}" data-1m="{p_1m}" data-15m="{p_15m}" data-1h="{p_1h}">
                <td class="symbol">{_esc(p['base'])}</td>
                <td class="{p['pnl_class']}">{p['unrealized_pnl']:+.4f} <small>({p['pnl_pct']:+.2f}%)</small><br>{prog_bar_inline}</td>
                <td class="{'positive' if _est_tp > 0 else ('negative' if _est_tp < 0 else 'muted')}">{f"+{_est_tp:.4f}" if _est_tp > 0 else (f"{_est_tp:+.4f}" if _est_tp != 0 else "—")}</td>
                <td>{f"{(p['entry_price'] - _tp) / p['entry_price'] * p.get('leverage', 10) * 100:.1f}%" if _tp > 0 and p.get('entry_price', 0) > 0 else "—"}</td>
                <td>{_fmt_price(p['entry_price'])}</td>
                <td>{_fmt_price(p['current_price'])}</td>
                <td>{p['leverage']:.0f}x</td>
                <td>{p['margin']:.2f} <small class="muted">({margin_pct:.0f}%)</small></td>
                <td>{_fmt_price(p['sl'])}</td>
                <td>{_fmt_price(p['tp'])}</td>
                <td>{_fmt_price(p['break_even_price'])}</td>
                <td class="liq-price">{_fmt_price(p['liq_price'])}</td>
                <td class="{'negative' if p['deducted_fee'] > 0 else ('positive' if p['deducted_fee'] < 0 else 'muted')}">{f"{-p['deducted_fee']:+.4f}" if p['deducted_fee'] != 0 else "0.0000"}</td>
                <td class="{'ft-pos' if p['funding_fee'] > 0 else ('negative' if p['funding_fee'] < 0 else 'muted')}" style="text-align:right">{f"{p['funding_fee']:.4f}" if p['funding_fee'] > 0 else (f"{p['funding_fee']:+.4f}" if p['funding_fee'] < 0 else "0.0000")}</td>
                <td>{f"{p.get('days_since_liq') - 1000}d+" if p.get('days_since_liq', -1) >= 1000 else (f"{p.get('days_since_liq')}d" if p.get('days_since_liq', -1) >= 0 else "—")}</td>
                <td>{p['opened_str']}</td>
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
            <div class="modal-stat"><span class="label">Break Even</span><span>{_fmt_price(p['break_even_price'])}</span></div>
            <div class="modal-stat"><span class="label">Liq</span><span class="liq-price">{_fmt_price(p['liq_price'])}</span></div>
            <div class="modal-stat"><span class="label">Fee</span><span class="{'negative' if p['deducted_fee'] > 0 else 'muted'}">{f"{-p['deducted_fee']:+.4f}" if p['deducted_fee'] != 0 else "0.0000"}</span></div>
            <div class="modal-stat"><span class="label">Funding</span><span class="{'ft-pos' if p['funding_fee'] > 0 else ('negative' if p['funding_fee'] < 0 else 'muted')}">{f"{p['funding_fee']:.4f}" if p['funding_fee'] > 0 else (f"{p['funding_fee']:+.4f}" if p['funding_fee'] < 0 else "0.0000")}</span></div>
            <div class="modal-stat"><span class="label">Opened</span><span>{p['opened_str']}</span></div>
        </div>
        <div class="modal-progress"><div class="prog-track" style="height:10px" title="{prog_tooltip}"><div class="prog-fill {p['prog_cls']}" style="width:{p['prog_val']:.1f}%"></div></div></div>
        <div class="modal-charts">
            {pos_chart_imgs if pos_chart_imgs else '<div class="empty">No charts available</div>'}
        </div>
    </div>
</div>"""
    else:
        position_rows = '<tr><td colspan="16" class="empty">No open positions</td></tr>'

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

        cycle_section = f"""
<div class="cycle-panel">
    <div class="cycle-header">
        <h2>Last Cycle</h2>
        <div class="cycle-time">{now}</div>
        <div class="cycle-time">{api_calls} api calls <span class="{api_class}">({api_rps:.2f}/sec, limit {api_limit}/sec)</span> | cycle {cycle_duration}s</div>
    </div>
    <div class="checks">{checks_html}</div>
    <div class="outcome {outcome_class}">{_esc(outcome)}</div>
</div>
"""

    # Build recent shorts section (open positions + closed shorts)
    closes_section = ""
    if cycle_info:
        recent_closes = cycle_info.get("recent_closes", [])
        now_utc = datetime.now(timezone.utc)
        shorts_rows = ""

        # Open positions first (sorted newest → oldest), aligned with closed shorts
        open_sorted = sorted(pos_data, key=lambda p: p.get("opened_ts", 0), reverse=True)
        for op in open_sorted:
            sym = _esc(op["base"])
            entry_p = op["entry_price"]
            fee = op.get("deducted_fee", 0)
            pnl = op["unrealized_pnl"]
            # Potential net = unrealized PnL - open fee - estimated close fee
            close_fee_est = abs(op.get("margin", 0) * op.get("leverage", 10) * 0.001)
            potential_net = pnl - fee - close_fee_est
            net_cls = "positive" if potential_net >= 0 else "negative"
            pp = op.get("price_precision", 4)
            # Duration for open position
            open_ts = op.get("opened_ts", 0)
            if open_ts > 0:
                _dur_sec = (now_dt.timestamp() - open_ts)
                _dur_str = f"{int(_dur_sec // 86400)}d" if _dur_sec >= 86400 else (f"{int(_dur_sec // 3600)}h" if _dur_sec >= 3600 else f"{int(_dur_sec // 60)}m")
            else:
                _dur_str = "—"
            shorts_rows += f'<div class="close-row close-open"><span class="close-sym">{sym} <span class="pos-dot"></span></span><span class="close-price">{entry_p:.{pp}f}</span><span class="close-price muted">—</span><span class="close-fee">{fee:.3f}</span><span class="close-delta {net_cls}">{potential_net:+.3f}</span><span class="close-bal close-bal-open">{current_balance:.2f}</span><span class="close-bal-delta muted">—</span><span class="close-time"><span class="time-full">{op["opened_short_str"]}</span><span class="time-short">{_dur_str}</span></span></div>\n'

        # Closed shorts with entry/exit/fees/net
        prev_bal = None
        for rc in recent_closes:
            sym = _esc(rc["symbol"])
            entry_p = rc.get("entry_price", 0)
            exit_p = rc.get("exit_price", 0)
            fees = rc.get("fees", 0)
            net = rc.get("net", 0)
            bal = rc.get("balance", 0)
            dur_sec = rc.get("duration_sec", 0)

            # Format duration (integer, floor)
            if dur_sec < 60:
                dur_str = f"{int(dur_sec)}s"
            elif dur_sec < 3600:
                dur_str = f"{int(dur_sec // 60)}m"
            elif dur_sec < 86400:
                dur_str = f"{int(dur_sec // 3600)}h"
            else:
                dur_str = f"{int(dur_sec // 86400)}d"

            dt = datetime.fromtimestamp(rc["timestamp"], tz=timezone.utc)
            time_str = f"{dt.strftime('%b-%d %H:%M')} ({dur_str})"

            # Balance delta
            if prev_bal is not None and bal > 0:
                delta = round(bal - prev_bal, 2)
                delta_str = f"{delta:+.2f}"
                delta_cls = "positive" if delta >= 0 else "negative"
            else:
                delta_str = "—"
                delta_cls = "muted"
            prev_bal = bal

            net_cls = "positive" if net >= 0 else "negative"
            sym_cls = "negative" if net < 0 else ""
            exit_cls = "negative" if exit_p > entry_p else ""  # price went up = bad for short
            pp = len(str(entry_p).rstrip('0').split('.')[-1]) if '.' in str(entry_p) else 0

            of = rc.get("open_fee", 0)
            cf = rc.get("close_fee", 0)
            ff = rc.get("funding_fee", 0)
            cp = rc.get("close_profit", 0)
            pos_pnl = cp + ff - of - cf  # net after all fees
            def _fv(v):
                """Format value with sign and color."""
                if v == 0:
                    return f'<span class="ft-zero">{v:>13.8f}</span>'
                elif v > 0:
                    return f'<span class="ft-pos">+{v:>12.8f}</span>'
                else:
                    return f'<span class="ft-neg">{v:>13.8f}</span>'

            fee_popup = (
                f'<b>Fee breakdown</b>'
                f'<div class="ft-row"><span class="ft-label">Closing profit</span>{_fv(cp)}</div>'
                f'<div class="ft-row"><span class="ft-label">Funding fee</span>{_fv(ff)}</div>'
                f'<div class="ft-row"><span class="ft-label">Opening fee</span>{_fv(-of)}</div>'
                f'<div class="ft-row"><span class="ft-label">Closing fee</span>{_fv(-cf)}</div>'
                f'<div class="ft-row ft-sep"><span class="ft-label">Position PnL</span>{_fv(pos_pnl)}</div>'
            )
            shorts_rows += f'<div class="close-row"><span class="close-sym {sym_cls}">{sym}</span><span class="close-price">{entry_p:.{pp}f}</span><span class="close-price {exit_cls}">{exit_p:.{pp}f}</span><span class="close-fee fee-tip-wrap"><span class="fee-tip-trigger">{fees:.3f}</span><span class="fee-tip">{fee_popup}</span></span><span class="close-delta {net_cls}">{net:+.3f}</span><span class="close-bal">{bal:.2f}</span><span class="close-bal-delta {delta_cls}">{delta_str}</span><span class="close-time"><span class="time-full">{time_str}</span><span class="time-short">{dur_str}</span></span></div>\n'

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
        chart_map = cycle_info.get("chart_map", {})

        scan_rows = ""
        modals = ""
        for idx, sr in enumerate(sr_list):
            dt_val = sr.get("downtrend_score", 0)
            is_eligible = sr.get("trade_eligible", False)
            if is_eligible:
                row_class = "scan-eligible"
            elif dt_val >= 40:
                row_class = ""
            else:
                row_class = "scan-dim"

            base, quote = _format_symbol(sr["symbol"])
            rsi_class = "positive" if sr["rsi"] > 70 else ("warning" if sr["rsi"] > 60 else "")

            # Composite downtrend score
            dt_score = sr.get("downtrend_score", 0)
            if dt_score >= 70:
                score_cls = "positive"
            elif dt_score >= 40:
                score_cls = "warning"
            else:
                score_cls = "muted"

            # Volume 24h
            vol_24h = sr.get("volume_24h", 0)
            if vol_24h >= 1_000_000_000:
                vol_str = f"{vol_24h / 1_000_000_000:.1f}B"
            elif vol_24h >= 1_000_000:
                vol_str = f"{vol_24h / 1_000_000:.1f}M"
            elif vol_24h >= 1_000:
                vol_str = f"{vol_24h / 1_000:.0f}K"
            else:
                vol_str = f"{vol_24h:.0f}"
            vol_cls = "" if vol_24h >= 5_000_000 else ("warning" if vol_24h >= 1_000_000 else "muted")

            # Component bars (normalized 0-100)
            n_adx = sr.get("n_adx", 0)
            n_slope = sr.get("n_slope", 0)
            n_roc = sr.get("n_roc", 0)
            n_ema = sr.get("n_ema", 0)
            comp_bars = (
                f'<span class="cbar cbar-blue" style="width:{n_adx:.0f}px" title="ADX {n_adx:.0f}"></span>'
                f'<span class="cbar cbar-green" style="width:{n_slope:.0f}px" title="Slope {n_slope:.0f}"></span>'
                f'<span class="cbar cbar-red" style="width:{n_roc:.0f}px" title="ROC {n_roc:.0f}"></span>'
                f'<span class="cbar cbar-cyan" style="width:{n_ema:.0f}px" title="EMA {n_ema:.0f}"></span>'
            )

            modal_id = f"modal-{idx}"
            # Chart URLs for preview panel (data attributes)
            preview_charts = chart_map.get(sr["symbol"], {})
            cache_bust = int(now_dt.timestamp())
            d_1m = f'{preview_charts["1m"]}?t={cache_bust}' if "1m" in preview_charts else ""
            d_15m = f'{preview_charts["15m"]}?t={cache_bust}' if "15m" in preview_charts else ""
            d_1h = f'{preview_charts["1h"]}?t={cache_bust}' if "1h" in preview_charts else ""
            pos_dot = ' <span class="pos-dot"></span>' if sr["symbol"] in open_symbols else ""

            # Est. profit calculation
            _min_roi = sr.get("min_roi", 2.0)
            _act_roi = max(auto_tp_roi, _min_roi)
            _margin = current_balance * position_size_pct / 100 / max_positions
            _notional = _margin * leverage
            _tp_pct = _act_roi / leverage / 100
            _gross = _notional * _tp_pct
            _of = _notional * taker_rate
            _cf = (_notional - _gross) * taker_rate
            _est_prof = _gross - _of - _cf

            # Component detail classes
            slope_v = sr.get("slope", 0)
            slope_cls = "positive" if slope_v < -0.05 else ("neg" if slope_v > 0.05 else "muted")
            roc_v = sr.get("roc_w", 0)
            roc_cls = "positive" if roc_v < -0.5 else ("neg" if roc_v > 0.5 else "muted")
            adx_dir_v = sr.get("adx_dir", 0)
            adx_dir_cls = "positive" if adx_dir_v > 0 else ("neg" if adx_dir_v < -1 else "muted")
            r2_v = sr.get("r2", 0)
            dc_v = sr.get("dc", 1)

            comp_sum = n_adx + n_slope + n_roc + n_ema

            scan_rows += f"""
            <tr class="{row_class} scan-row" onclick="openModal('{modal_id}')"
                data-symbol="{_esc(base)}/{_esc(quote)}" data-1m="{d_1m}" data-15m="{d_15m}" data-1h="{d_1h}">
                <td class="symbol">{_esc(base)}{pos_dot}</td>
                <td data-v="{dt_score}" class="{score_cls}"><b>{dt_score:.0f}</b></td>
                <td data-v="{sr.get('risk_score', 0)}" class="scan-extra {'negative' if sr.get('risk_score', 0) >= 7 else ('warning' if sr.get('risk_score', 0) >= 4 else 'positive')}">{sr.get('risk_score', 0):.0f}</td>
                <td data-v="{_min_roi}" class="scan-extra {'warning' if _min_roi > 3 else 'muted'}">{_min_roi:.1f}%</td>
                <td data-v="{sr.get('days_since_liq', -1) - 1000 if sr.get('days_since_liq', -1) >= 1000 else sr.get('days_since_liq', -1)}" class="scan-extra">{f"{sr.get('days_since_liq') - 1000}d+" if sr.get('days_since_liq', -1) >= 1000 else (f"{sr.get('days_since_liq')}d ago" if sr.get('days_since_liq', -1) >= 0 else "—")}</td>
                <td data-v="{_est_prof}" class="{'positive' if _est_prof > 0 else ('negative' if _est_prof < 0 else 'muted')}">{f"+{_est_prof:.3f}" if _est_prof > 0 else (f"{_est_prof:+.3f}" if _est_prof != 0 else "0")}</td>
                <td data-v="{adx_dir_v}" class="scan-extra {adx_dir_cls}">{adx_dir_v:+.1f}</td>
                <td data-v="{slope_v}" class="scan-extra {slope_cls}">{slope_v:+.3f}</td>
                <td data-v="{roc_v}" class="scan-extra {roc_cls}">{roc_v:+.2f}</td>
                <td data-v="{sr.get('ema_gap', 0)}" class="scan-extra">{sr.get('ema_gap', 0):+.3f}</td>
                <td data-v="{r2_v}" class="scan-extra {'positive' if r2_v >= 0.7 else ('warning' if r2_v >= 0.4 else 'muted')}">{r2_v:.2f}</td>
                <td data-v="{dc_v}" class="scan-extra {'positive' if dc_v <= 0.4 else ('warning' if dc_v <= 0.7 else 'neg')}">{dc_v:.2f}</td>
                <td data-v="{sr['rsi']}" class="scan-extra {rsi_class}">{sr['rsi']:.1f}</td>
                <td data-v="{sr['atr_pct']}" class="scan-extra">{sr['atr_pct']:.1f}%</td>
                <td data-v="{vol_24h}" class="scan-extra {vol_cls}">{vol_str}</td>
                <td data-v="{sr.get('approx_liq', 0)}" class="scan-extra">{sr.get('approx_liq', 0):.4g}</td>
                <td data-v="{comp_sum}" class="scan-extra comp-bars">{comp_bars}</td>
            </tr>"""

            # Build modal for this symbol
            charts = chart_map.get(sr["symbol"], {})
            chart_imgs = ""
            cache_bust = int(now_dt.timestamp())
            for tf_label, tf_key in [("1 min", "1m"), ("15 min", "15m"), ("1 hour", "1h")]:
                src = charts.get(tf_key, "")
                if src:
                    chart_imgs += f'<div class="modal-chart"><div class="modal-chart-label">{tf_label}</div><img src="{_esc(src)}?t={cache_bust}" alt="{_esc(base)} {tf_label}"></div>\n'

            modals += f"""
<div class="modal-overlay" id="{modal_id}" onclick="if(event.target===this)this.style.display='none'">
    <div class="modal-content">
        <div class="modal-header">
            <span class="modal-symbol">{_esc(base)}<span class="quote">/{_esc(quote)}</span></span>
            <span class="modal-close" onclick="this.closest('.modal-overlay').style.display='none'">&times;</span>
        </div>
        <div class="modal-stats">
            <div class="modal-stat"><span class="label">Score</span><span class="{score_cls}"><b>{dt_score:.0f}</b></span></div>
            <div class="modal-stat"><span class="label">R²</span><span class="{'positive' if r2_v >= 0.7 else ('warning' if r2_v >= 0.4 else 'muted')}">{r2_v:.2f}</span></div>
            <div class="modal-stat"><span class="label">DC</span><span class="{'positive' if dc_v <= 0.4 else ('warning' if dc_v <= 0.7 else 'neg')}">{dc_v:.2f}</span></div>
            <div class="modal-stat"><span class="label">ADX dir</span><span class="{adx_dir_cls}">{adx_dir_v:+.1f}</span></div>
            <div class="modal-stat"><span class="label">Slope</span><span class="{slope_cls}">{slope_v:+.3f}</span></div>
            <div class="modal-stat"><span class="label">ROC</span><span class="{roc_cls}">{roc_v:+.2f}</span></div>
            <div class="modal-stat"><span class="label">EMA gap</span><span>{sr.get('ema_gap', 0):+.3f}</span></div>
            <div class="modal-stat"><span class="label">1h Slope</span><span class="{'positive' if sr.get('slope_1h', 0) < -0.01 else ('negative' if sr.get('slope_1h', 0) > 0.01 else 'muted')}">{sr.get('slope_1h', 0):+.3f}</span></div>
            <div class="modal-stat"><span class="label">1h R²</span><span>{sr.get('r2_1h', 0):.2f}</span></div>
        </div>
        <div class="modal-stats">
            <div class="modal-stat"><span class="label">Risk</span><span class="{'negative' if sr.get('risk_score', 0) >= 7 else ('warning' if sr.get('risk_score', 0) >= 4 else 'positive')}">{sr.get('risk_score', 0):.0f}/10</span></div>
            <div class="modal-stat"><span class="label">Liq (~)</span><span>{sr.get('approx_liq', 0):.4g} (+{sr.get('liq_dist_pct', 0):.0f}%)</span></div>
            <div class="modal-stat"><span class="label">Last@Liq</span><span>{f"{sr.get('days_since_liq') - 1000}d+" if sr.get('days_since_liq', -1) >= 1000 else (f"{sr.get('days_since_liq')}d ago" if sr.get('days_since_liq', -1) >= 0 else "—")}</span></div>
        </div>
        <div class="modal-stats">
            <div class="modal-stat"><span class="label">RSI</span><span class="{rsi_class}">{sr['rsi']:.1f}</span></div>
            <div class="modal-stat"><span class="label">ATR</span><span>{sr['atr_pct']:.1f}%</span></div>
            <div class="modal-stat"><span class="label">ADX</span><span>{sr.get('adx', 0):.0f}</span></div>
            <div class="modal-stat"><span class="label">+DI</span><span>{sr.get('di_plus', 0):.0f}</span></div>
            <div class="modal-stat"><span class="label">-DI</span><span>{sr.get('di_minus', 0):.0f}</span></div>
        </div>
        <div class="modal-trade-row">
            <button class="short-btn" onclick="doShort('{_esc(sr['symbol'])}', this)">OPEN SHORT</button>
            <div class="trade-select">
                <span class="label">Bet</span>
                <select class="bet-pct-select" onchange="updateExposure(this, {leverage})">
                    <option value="5">5%</option>
                    <option value="10" selected>10%</option>
                    <option value="20">20%</option>
                    <option value="30">30%</option>
                    <option value="50">50%</option>
                    <option value="100">100%</option>
                </select>
            </div>
            <div class="trade-select">
                <span class="label">TP ROI</span>
                <select class="tp-roi-select" onchange="updateExposure(this, {leverage})">
                    <option value="1">1%</option>
                    <option value="2">2%</option>
                    <option value="3" selected>3%</option>
                    <option value="4">4%</option>
                    <option value="5">5%</option>
                    <option value="10">10%</option>
                </select>
            </div>
        </div>
        <div class="trade-breakdown" data-bal="{current_balance}" data-lev="{leverage}" data-rate="0.001" data-tick="{sr.get('tick_size', 0.01)}" data-minroi="{sr.get('min_roi', 2)}">
        </div>
        <div class="modal-actions">
            <div class="short-result"></div>
        </div>
        <div class="modal-charts">
            {chart_imgs if chart_imgs else '<div class="empty">No charts available</div>'}
        </div>
        <div class="backtest-section">
            <div class="backtest-header">
                <button class="backtest-btn" onclick="runBacktest('{_esc(sr['symbol'])}', this)">Emulate</button>
                <select class="backtest-select backtest-period" onchange="(function(s){{ var tf=s.closest('.backtest-header').querySelector('.backtest-tf'); var d=parseInt(s.value); if(d>=365) tf.value='1h'; else if(d>30) tf.value='15m'; }})(this)">
                    <option value="1">1d</option>
                    <option value="7" selected>1w</option>
                    <option value="30">1m</option>
                    <option value="60">2m</option>
                    <option value="90">3m</option>
                    <option value="180">6m</option>
                    <option value="365">1y</option>
                    <option value="730">2y</option>
                    <option value="1095">3y</option>
                    <option value="1825">5y</option>
                    <option value="3650">10y</option>
                </select>
                <select class="backtest-select backtest-tf">
                    <option value="1m">1m</option>
                    <option value="15m" selected>15m</option>
                    <option value="1h">1h</option>
                </select>
                <input type="number" class="backtest-input backtest-balance" value="{current_balance:.2f}" step="0.01">
                <select class="backtest-select backtest-bet">
                    <option value="1">1%</option>
                    <option value="2">2%</option>
                    <option value="3">3%</option>
                    <option value="4">4%</option>
                    <option value="5">5%</option>
                    <option value="10">10%</option>
                    <option value="20" selected>20%</option>
                    <option value="30">30%</option>
                    <option value="50">50%</option>
                    <option value="100">100%</option>
                </select>
                <input type="number" class="backtest-input backtest-roi" value="{max(auto_tp_roi, sr.get('min_roi', 2.0)):.1f}" step="0.1">
                <span class="muted" style="font-size:11px">ROI%</span>
            </div>
            <div class="backtest-results" style="display:none"></div>
        </div>
    </div>
</div>"""

        modal_html = modals

        scan_section = f"""
<h2>Market Scan ({len(sr_list)} pairs)</h2>
<div class="table-wrap">
<table id="scan-table">
    <thead>
        <tr>
            <th>Symbol</th>
            <th class="sortable strategy-active" data-col="1" data-dir="desc">Score</th>
            <th class="sortable scan-extra" data-col="2" data-sort="asc">Risk</th>
            <th class="sortable scan-extra" data-col="3" data-sort="asc">Min ROI</th>
            <th class="sortable scan-extra" data-col="4" data-sort="desc">Last@Liq</th>
            <th class="sortable" data-col="5">Est.P</th>
            <th class="sortable scan-extra" data-col="6">ADX</th>
            <th class="sortable scan-extra" data-col="7">Slope</th>
            <th class="sortable scan-extra" data-col="8">ROC</th>
            <th class="sortable scan-extra" data-col="9">EMA</th>
            <th class="sortable scan-extra" data-col="10">R²</th>
            <th class="sortable scan-extra" data-col="11">DC</th>
            <th class="sortable scan-extra" data-col="12">RSI</th>
            <th class="sortable scan-extra" data-col="13">ATR</th>
            <th class="sortable scan-extra" data-col="14">Vol</th>
            <th class="sortable scan-extra" data-col="15">Liq</th>
            <th class="sortable scan-extra" data-col="16" style="min-width:120px">Components</th>
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
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><text x='16' y='26' text-anchor='middle' font-family='Arial,sans-serif' font-size='28' font-weight='bold' fill='%23f7931a'>&#x20bf;</text></svg>">
<link rel="apple-touch-icon" sizes="180x180" href="apple-touch-icon.png">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Short Bot">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="theme-color" content="#0d1117">
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
    .scan-eligible {{
        background: #1a2a1a;
        border-left: 3px solid #3fb950;
    }}
    .scan-dim td {{
        color: #6e7681;
    }}
    th.strategy-active {{
        color: #58a6ff;
    }}
    th.sortable {{
        cursor: pointer;
        user-select: none;
        position: relative;
        padding-right: 18px;
    }}
    th.sortable:hover {{
        color: #c9d1d9;
    }}
    th.sortable::after {{
        content: "⇅";
        position: absolute;
        right: 4px;
        font-size: 9px;
        opacity: 0.3;
    }}
    th.sortable[data-dir="desc"]::after {{
        content: "↓";
        opacity: 0.8;
        color: #58a6ff;
    }}
    th.sortable[data-dir="asc"]::after {{
        content: "↑";
        opacity: 0.8;
        color: #58a6ff;
    }}
    .scan-dim td.symbol {{
        color: #6e7681;
    }}
    .comp-bars {{
        white-space: nowrap;
    }}
    .cbar {{
        display: inline-block;
        height: 8px;
        border-radius: 3px;
        vertical-align: middle;
        margin-right: 2px;
        min-width: 1px;
    }}
    .cbar-blue {{ background: linear-gradient(90deg, #1f6feb, #58a6ff); }}
    .cbar-green {{ background: linear-gradient(90deg, #238636, #3fb950); }}
    .cbar-red {{ background: linear-gradient(90deg, #da3633, #f85149); }}
    .cbar-cyan {{ background: linear-gradient(90deg, #1b7c83, #3bc9d1); }}
    .neg {{ color: #f85149; }}
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
    .prog-inline {{
        height: 5px;
        margin-top: 5px;
        overflow: hidden;
        cursor: help;
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
    @media (max-width: 768px) {{
        .top-row {{
            flex-direction: column;
        }}
        .cycle-panel, .closes-panel {{
            min-width: unset;
        }}
        .close-price, .close-fee, .close-bal-delta {{
            display: none;
        }}
        .close-sym {{
            white-space: nowrap;
        }}
        .scan-extra {{
            display: none !important;
        }}
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
    .closes-panel .section-header h2 {{
        margin-bottom: 0;
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
        width: 55px;
        color: #c9d1d9;
        font-weight: 600;
    }}
    .close-sym.negative {{
        color: #f85149;
    }}
    .close-price.negative {{
        color: #f85149;
    }}
    .close-price {{
        width: 70px;
        text-align: right;
        color: #8b949e;
        font-size: 12px;
    }}
    .close-fee {{
        width: 50px;
        text-align: right;
        color: #6e7681;
        font-size: 12px;
    }}
    .fee-tip-wrap {{
        position: relative;
        cursor: help;
    }}
    .fee-tip {{
        display: none;
        position: absolute;
        bottom: calc(100% + 8px);
        left: 50%;
        transform: translateX(-50%);
        background: #1c2128;
        border: 1px solid #30363d;
        border-radius: 8px;
        padding: 10px 14px;
        font-size: 12px;
        color: #c9d1d9;
        line-height: 1.8;
        white-space: nowrap;
        z-index: 60;
        box-shadow: 0 8px 24px rgba(0,0,0,0.5);
        pointer-events: none;
        font-family: inherit;
    }}
    .fee-tip::after {{
        content: "";
        position: absolute;
        top: 100%;
        left: 50%;
        transform: translateX(-50%);
        border: 6px solid transparent;
        border-top-color: #30363d;
    }}
    .fee-tip b {{
        color: #8b949e;
        font-size: 13px;
        display: block;
        margin-bottom: 6px;
    }}
    .ft-row {{
        display: flex;
        justify-content: space-between;
        gap: 16px;
    }}
    .ft-label {{
        color: #6e7681;
    }}
    .ft-neg {{
        color: #f85149;
        font-family: inherit;
        text-align: right;
    }}
    .ft-pos {{
        color: #58a6ff;
        font-family: inherit;
        text-align: right;
    }}
    .ft-zero {{
        color: #484f58;
        font-family: inherit;
        text-align: right;
    }}
    .ft-sep {{
        border-top: 1px solid #21262d;
        padding-top: 4px;
        margin-top: 2px;
    }}
    .fee-tip-wrap:hover .fee-tip {{
        display: block;
    }}
    .close-bal {{
        width: 55px;
        text-align: right;
        color: #8b949e;
    }}
    .close-delta, .close-bal-delta {{
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
    .time-short {{
        display: none;
    }}
    @media (max-width: 768px) {{
        .time-full {{
            display: none;
        }}
        .time-short {{
            display: inline;
        }}
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
    .status-bar {{
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 8px 14px;
        margin-bottom: 16px;
        background: #161b22;
        border: 1px solid #21262d;
        border-radius: 8px;
        font-size: 13px;
    }}
    .status-dot {{
        width: 8px;
        height: 8px;
        border-radius: 50%;
        background: #3fb950;
        flex-shrink: 0;
    }}
    .status-dot.active {{
        background: #58a6ff;
        animation: dot-pulse 1.5s ease-in-out infinite;
    }}
    .status-dot.error {{
        background: #f85149;
    }}
    .status-text {{
        color: #8b949e;
        font-weight: 600;
    }}
    .status-progress {{
        flex: 1;
        height: 4px;
        background: #21262d;
        border-radius: 2px;
        overflow: hidden;
        max-width: 300px;
    }}
    .status-progress-bar {{
        height: 100%;
        background: linear-gradient(90deg, #1f6feb, #58a6ff);
        border-radius: 2px;
        transition: width 0.5s ease;
        width: 0%;
    }}
    .scan-row {{
        cursor: pointer;
        -webkit-user-select: none;
        user-select: none;
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
    .tick-warn {{
        position: relative;
        display: inline-block;
        margin-left: 4px;
        cursor: help;
    }}
    .tick-warn-icon {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 18px;
        height: 18px;
        font-size: 13px;
        background: #d29922;
        color: #0d1117;
        border-radius: 4px;
        font-weight: 700;
        vertical-align: middle;
        line-height: 1;
    }}
    .tick-tooltip {{
        display: none;
        position: absolute;
        bottom: calc(100% + 8px);
        left: 50%;
        transform: translateX(-50%);
        background: #1c2128;
        border: 1px solid #d29922;
        border-radius: 8px;
        padding: 10px 14px;
        font-size: 12px;
        color: #c9d1d9;
        line-height: 1.6;
        white-space: nowrap;
        z-index: 60;
        box-shadow: 0 8px 24px rgba(0,0,0,0.5);
        pointer-events: none;
    }}
    .tick-tooltip::after {{
        content: "";
        position: absolute;
        top: 100%;
        left: 50%;
        transform: translateX(-50%);
        border: 6px solid transparent;
        border-top-color: #d29922;
    }}
    .tick-tooltip b {{
        color: #d29922;
        font-size: 13px;
    }}
    .tick-warn:hover .tick-tooltip {{
        display: block;
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
    .trade-breakdown {{
        font-size: 12px;
        color: #6e7681;
        padding: 8px 14px;
        margin-bottom: 8px;
        line-height: 1.7;
        border-top: 1px solid #21262d;
    }}
    .trade-breakdown .tb-row {{
        display: flex;
        justify-content: space-between;
    }}
    .trade-breakdown .tb-label {{
        color: #6e7681;
    }}
    .trade-breakdown .tb-val {{
        color: #8b949e;
        font-family: inherit;
    }}
    .trade-breakdown .tb-result {{
        border-top: 1px solid #30363d;
        padding-top: 4px;
        margin-top: 2px;
        font-weight: 700;
        font-size: 13px;
    }}
    .trade-breakdown .tb-result .tb-val {{
        color: #c9d1d9;
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
    .backtest-section {{
        margin-top: 16px;
        border-top: 1px solid #21262d;
        padding-top: 12px;
    }}
    .backtest-header {{
        display: flex;
        align-items: center;
        gap: 8px;
        flex-wrap: wrap;
    }}
    .backtest-btn {{
        background: #1f6feb;
        color: #fff;
        border: none;
        border-radius: 6px;
        padding: 7px 16px;
        font-family: inherit;
        font-size: 13px;
        font-weight: 700;
        cursor: pointer;
    }}
    .backtest-btn:hover {{ background: #388bfd; }}
    .backtest-btn:disabled {{ opacity: 0.5; cursor: default; }}
    .backtest-select, .backtest-input {{
        background: #0d1117;
        color: #c9d1d9;
        border: 1px solid #30363d;
        border-radius: 6px;
        padding: 6px 10px;
        font-family: inherit;
        font-size: 13px;
    }}
    .backtest-input {{ width: 70px; }}
    .backtest-results {{
        margin-top: 12px;
        font-size: 12px;
        max-height: 300px;
        overflow-y: auto;
    }}
    .bt-row {{
        display: flex;
        gap: 8px;
        padding: 3px 0;
        border-bottom: 1px solid #21262d;
        font-family: inherit;
    }}
    .bt-row.bt-header {{
        color: #6e7681;
        font-weight: 600;
        font-size: 11px;
        text-transform: uppercase;
    }}
    .bt-chart {{
        margin-top: 12px;
        min-height: 40px;
        display: flex;
        align-items: center;
        justify-content: center;
    }}
    .bt-summary {{
        margin-top: 8px;
        padding: 10px;
        background: #13171e;
        border-radius: 6px;
        font-size: 13px;
        line-height: 1.8;
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
    /* Toast notification */
    .toast-container {{
        position: fixed;
        top: 24px;
        right: 24px;
        z-index: 200;
        display: flex;
        flex-direction: column;
        gap: 8px;
        pointer-events: none;
    }}
    .toast {{
        background: #1c2128;
        border: 1px solid #238636;
        border-left: 4px solid #3fb950;
        border-radius: 8px;
        padding: 14px 20px;
        color: #c9d1d9;
        font-family: inherit;
        font-size: 13px;
        box-shadow: 0 8px 32px rgba(0,0,0,0.5);
        pointer-events: auto;
        transform: translateX(120%);
        animation: toast-in 0.35s cubic-bezier(0.21, 1.02, 0.73, 1) forwards;
    }}
    .toast.toast-out {{
        animation: toast-out 0.3s ease-in forwards;
    }}
    .toast-title {{
        font-weight: 700;
        color: #3fb950;
        margin-bottom: 4px;
        font-size: 14px;
    }}
    .toast-body {{
        color: #8b949e;
        line-height: 1.5;
    }}
    .toast-body b {{
        color: #c9d1d9;
    }}
    @keyframes toast-in {{
        from {{ transform: translateX(120%); opacity: 0; }}
        to {{ transform: translateX(0); opacity: 1; }}
    }}
    @keyframes toast-out {{
        from {{ transform: translateX(0); opacity: 1; }}
        to {{ transform: translateX(120%); opacity: 0; }}
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
<div class="updated">Last updated: <span id="last-updated" data-utc="{now_iso}"></span></div>
<div class="version">Ver: {_esc(_load_version())}</div>

<div class="status-bar" id="status-bar">
    <span class="status-dot" id="status-dot"></span>
    <span class="status-text" id="cycle-phase">Ready</span>
    <div class="status-progress" id="cycle-progress" style="display:none">
        <div class="status-progress-bar" id="cycle-progress-bar"></div>
    </div>
</div>

<div class="cards">
    <div class="card">
        <div class="label">Balance</div>
        <div class="value neutral">{current_balance:.2f} <small style="font-size:12px;color:#6e7681">USDT</small></div>
    </div>
    <div class="card">
        <div class="label">Active Trades</div>
        <div class="value {'positive' if len(pos_data) > 0 else 'muted'}">{len(pos_data)}</div>
    </div>
    <div class="card">
        <div class="label">Unrealized PnL</div>
        <div class="value {unrealized_class}">{total_unrealized:+.2f} <small style="font-size:12px">USDT</small></div>
    </div>
    <div class="card">
        <div class="label">Wallet Balance</div>
        <div class="value neutral">{wallet_balance:.2f} <small style="font-size:12px;color:#6e7681">USDT</small></div>
    </div>
    <div class="card">
        <div class="label">Est. Balance at TP</div>
        <div class="value {'positive' if est_tp_net > 0 else ('negative' if est_tp_net < 0 else 'muted')}">{est_balance_at_tp:.2f} <small style="font-size:12px">({est_tp_net:+.2f} / {f"{est_tp_net / wallet_balance * 100:+.1f}" if wallet_balance > 0 else "0.0"}%)</small></div>
    </div>
    <div class="card">
        <div class="label">Start Balance</div>
        <div class="value neutral">{start_balance:.2f} <small style="font-size:12px;color:#6e7681">USDT{f" ({start_date_display})" if start_date_display else ""}</small></div>
    </div>
    <div class="card">
        <div class="label">Total Trades</div>
        <div class="value neutral">{total_trades}{f' <small style="font-size:12px;color:#6e7681">(days: {days_since_start})</small>' if start_date_str else ""}</div>
    </div>
    <div class="card">
        <div class="label">Total PnL</div>
        <div class="value {total_class}">{total_pnl:+.2f} <small style="font-size:12px">USDT ({total_pnl_pct:+.1f}%)</small></div>
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
            <th>PnL</th>
            <th>Est.TP</th>
            <th>ROI</th>
            <th>Entry</th>
            <th>Current</th>
            <th>Lev</th>
            <th>Margin</th>
            <th>SL</th>
            <th>TP</th>
            <th>BE</th>
            <th>Liq</th>
            <th>Fee</th>
            <th>Fund</th>
            <th>Last@Liq</th>
            <th>Opened</th>
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
// Convert UTC timestamp to local time
(function() {{
    var el = document.getElementById("last-updated");
    if (el) {{
        var utc = el.getAttribute("data-utc");
        var d = new Date(utc);
        el.textContent = d.toLocaleString();
    }}
}})();

// Cycle status polling
(function() {{
    var phaseEl = document.getElementById("cycle-phase");
    var progressWrap = document.getElementById("cycle-progress");
    var progressBar = document.getElementById("cycle-progress-bar");
    var dotEl = document.getElementById("status-dot");
    if (!phaseEl) return;

    var initialReadyAt = null;
    var pollInterval = 10000;
    var pollTimer = null;

    function setStatus(text, state) {{
        phaseEl.textContent = text;
        dotEl.className = "status-dot" + (state === "active" ? " active" : (state === "error" ? " error" : ""));
    }}

    function poll() {{
        fetch("/cycle_status.json?" + Date.now())
        .then(function(r) {{
            if (!r.ok) throw new Error("Status " + r.status);
            return r.json();
        }})
        .then(function(data) {{
            var phase = data.phase || "Unknown";
            var progress = data.progress || 0;
            var updatedAt = data.updated_at || 0;

            if (phase === "Ready") {{
                if (initialReadyAt === null) {{
                    initialReadyAt = updatedAt;
                    setStatus("Ready", "ready");
                    progressWrap.style.display = "none";
                    setPollRate(10000);
                }} else if (updatedAt !== initialReadyAt) {{
                    location.reload();
                }} else {{
                    setStatus("Ready", "ready");
                    progressWrap.style.display = "none";
                    setPollRate(10000);
                }}
            }} else {{
                setStatus(phase + " " + progress + "%", "active");
                progressWrap.style.display = "block";
                progressBar.style.width = progress + "%";
                setPollRate(2000);
            }}
        }})
        .catch(function(e) {{
            setStatus("Status unavailable", "error");
            progressWrap.style.display = "none";
            setPollRate(10000);
        }});
    }}

    function setPollRate(ms) {{
        if (pollInterval !== ms) {{
            pollInterval = ms;
            clearInterval(pollTimer);
            pollTimer = setInterval(poll, ms);
        }}
    }}

    poll();
    pollTimer = setInterval(poll, pollInterval);
}})();
document.addEventListener("keydown", function(e) {{
    if (e.key === "Escape") {{
        var modals = document.querySelectorAll(".modal-overlay");
        modals.forEach(function(m) {{ m.style.display = "none"; }});
    }}
}});

// Open modal and init breakdown
function openModal(id) {{
    var modal = document.getElementById(id);
    modal.style.display = "flex";
    var sel = modal.querySelector(".bet-pct-select");
    if (sel) {{
        var bd = modal.querySelector(".trade-breakdown");
        var lev = bd ? parseFloat(bd.getAttribute("data-lev")) || 10 : 10;
        updateExposure(sel, lev);
    }}
}}

// Update trade breakdown when bet/tp changes
function updateExposure(sel, leverage) {{
    var row = sel.closest(".modal-trade-row");
    var bd = row.parentElement.querySelector(".trade-breakdown") || row.nextElementSibling;
    if (!bd || !bd.classList.contains("trade-breakdown")) return;
    var betPct = parseInt(row.querySelector(".bet-pct-select").value);
    var tpRoi = parseFloat(row.querySelector(".tp-roi-select").value);
    var bal = parseFloat(bd.getAttribute("data-bal")) || 0;
    var lev = parseFloat(bd.getAttribute("data-lev")) || 10;
    var rate = parseFloat(bd.getAttribute("data-rate")) || 0.001;
    var tick = parseFloat(bd.getAttribute("data-tick")) || 0.01;

    var margin = bal * betPct / 100;
    var notional = margin * lev;
    var tpPriceChg = tpRoi / lev / 100;
    var openFee = notional * rate;
    var gross = notional * tpPriceChg;
    var closeNotional = notional - gross;
    var closeFee = closeNotional * rate;
    var totalFee = openFee + closeFee;
    var net = gross - totalFee;
    var netRoi = margin > 0 ? (net / margin * 100) : 0;
    var netCls = net >= 0 ? "#3fb950" : "#f85149";

    function R(label, val, formula) {{
        return '<div class="tb-row"><span class="tb-label">' + label + '</span><span class="tb-val">' + val + (formula ? ' <small style="color:#30363d">' + formula + '</small>' : '') + '</span></div>';
    }}

    bd.innerHTML =
        R("Margin", margin.toFixed(2) + " USDT", bal.toFixed(1) + " * " + betPct + "%") +
        R("Position", notional.toFixed(2) + " USDT", margin.toFixed(2) + " * " + lev + "x") +
        R("Open fee", openFee.toFixed(4) + " USDT", notional.toFixed(2) + " * " + (rate*100).toFixed(1) + "%") +
        R("Gross profit", gross.toFixed(4) + " USDT", notional.toFixed(2) + " * " + (tpPriceChg*100).toFixed(2) + "%") +
        R("Close fee", closeFee.toFixed(4) + " USDT", closeNotional.toFixed(2) + " * " + (rate*100).toFixed(1) + "%") +
        R("Total fees", totalFee.toFixed(4) + " USDT", openFee.toFixed(4) + " + " + closeFee.toFixed(4)) +
        '<div class="tb-row tb-result"><span class="tb-label">Net profit</span><span class="tb-val" style="color:' + netCls + '">' + (net >= 0 ? "+" : "") + net.toFixed(4) + " USDT (" + (netRoi >= 0 ? "+" : "") + netRoi.toFixed(1) + '% ROI)</span></div>' +
        R("Tick size", tick.toString(), "min TP = entry - tick");

    // Min ROI warning
    var minRoi = parseFloat(bd.getAttribute("data-minroi")) || 2;
    var tpRoi = parseFloat(row.querySelector(".tp-roi-select").value);
    if (tpRoi < minRoi) {{
        bd.innerHTML += '<div class="ft-row" style="margin-top:6px;color:#f85149;font-weight:600">Min ROI for this pair: ' + minRoi.toFixed(1) + '% &mdash; selected ' + tpRoi + '% is below breakeven!</div>';
    }}

    // Add min_roi option to combobox if not present
    var tpSelect = row.querySelector(".tp-roi-select");
    var minVal = Math.ceil(minRoi);
    var exists = false;
    for (var oi = 0; oi < tpSelect.options.length; oi++) {{
        if (parseInt(tpSelect.options[oi].value) === minVal) exists = true;
    }}
    if (!exists && minVal > 1 && minVal < 20) {{
        var opt = document.createElement("option");
        opt.value = minVal;
        opt.textContent = minVal + "% (min)";
        tpSelect.appendChild(opt);
    }}
}}

// Manual SHORT button
function doShort(symbol, btn) {{
    var row = btn.closest(".modal-trade-row");
    var betSelect = row.querySelector(".bet-pct-select");
    var tpSelect = row.querySelector(".tp-roi-select");
    var betPct = betSelect ? parseInt(betSelect.value) : 10;
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
            var overlay = btn.closest(".modal-overlay");
            if (overlay) overlay.style.display = "none";
            var o = data.order;
            var sym = o.symbol || symbol.split(":")[0];
            showToast(
                "SHORT opened",
                "<b>" + sym + "</b><br>" +
                "Entry: " + o.entry_price + " (fill)<br>" +
                "TP: " + o.take_profit + " (" + (o.tp_change_pct >= 0 ? "-" : "") + o.tp_change_pct + "%)" +
                (o.tp_adjusted ? ' <span style="color:#d29922">&#9888; adjusted</span>' : "") +
                "<br>Margin: " + o.margin + " USDT"
            );
            if (data.warning) {{
                showToast("&#9888; Warning", data.warning, 8000);
            }}
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

// Preview panel on hover + touch (event delegation)
(function() {{
    var panel = document.getElementById("preview-panel");
    var symEl = document.getElementById("preview-symbol");
    var chartsEl = document.getElementById("preview-charts");
    if (!panel) return;
    var currentRow = null;

    function showPreview(row) {{
        if (row === currentRow) return;
        currentRow = row;
        if (!row) {{
            panel.classList.remove("visible");
            return;
        }}
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
    }}

    function hidePreview() {{
        currentRow = null;
        panel.classList.remove("visible");
    }}

    // Mouse
    document.addEventListener("mouseover", function(e) {{
        showPreview(e.target.closest(".scan-row"));
    }});
    document.addEventListener("mouseout", function(e) {{
        var row = e.target.closest(".scan-row");
        var related = e.relatedTarget ? e.relatedTarget.closest(".scan-row") : null;
        if (row && row !== related) hidePreview();
    }});

    // Touch — long press (500ms) for preview, tap for modal
    var touchTimer = null;
    var touchActive = false;
    var touchStartY = 0;

    document.addEventListener("touchstart", function(e) {{
        var row = e.target.closest(".scan-row");
        if (!row) return;
        touchActive = false;
        touchStartY = e.touches[0].clientY;
        touchTimer = setTimeout(function() {{
            touchActive = true;
            showPreview(row);
            if (navigator.vibrate) navigator.vibrate(30);
        }}, 500);
    }}, {{passive: true}});

    document.addEventListener("touchmove", function(e) {{
        // Cancel long press if scrolling vertically
        if (!touchActive && Math.abs(e.touches[0].clientY - touchStartY) > 10) {{
            clearTimeout(touchTimer);
            return;
        }}
        // If long press activated, follow finger between rows
        if (touchActive) {{
            e.preventDefault();
            var touch = e.touches[0];
            var el = document.elementFromPoint(touch.clientX, touch.clientY);
            var row = el ? el.closest(".scan-row") : null;
            if (row) {{
                showPreview(row);
            }} else {{
                hidePreview();
            }}
        }}
    }}, {{passive: false}});

    document.addEventListener("touchend", function(e) {{
        clearTimeout(touchTimer);
        if (touchActive) {{
            // Long press was active — hide preview, don't trigger click
            hidePreview();
            touchActive = false;
            e.preventDefault();
        }}
        // If not active — normal tap, click fires naturally (opens modal)
    }}, {{passive: false}});
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
            tbody.innerHTML = '<tr><td colspan="16" class="empty">No open positions</td></tr>';
            return;
        }}

        var bal = data.balance || 1;
        var html = "";
        for (var i = 0; i < positions.length; i++) {{
            var p = positions[i];
            var pp = p.price_precision || 2;
            var pnlCls = p.pnl_class || "neutral";

            function fmtP(v) {{
                return v ? v.toFixed(pp) : "-";
            }}

            var progTip = (p.prog_label_l||"") + " \u2190 " + Math.round(p.prog_val) + "% \u2192 " + (p.prog_label_r||"");
            var progBar = '<div class="prog-track prog-inline" title="' + progTip + '"><div class="prog-fill ' + p.prog_cls + '" style="width:' + p.prog_val + '%"></div></div>';
            var marginPct = Math.round(p.margin / bal * 100);

            var symKey = p.base + '/' + p.quote;
            var cc = _chartCache[symKey] || {{}};
            html += '<tr class="pos-row scan-row" data-symbol="' + symKey + '" data-1m="' + (cc["1m"]||"") + '" data-15m="' + (cc["15m"]||"") + '" data-1h="' + (cc["1h"]||"") + '">' +
                '<td class="symbol">' + p.base + '</td>' +
                '<td class="' + pnlCls + '">' + (p.unrealized_pnl >= 0 ? "+" : "") + p.unrealized_pnl.toFixed(4) + ' <small>(' + (p.pnl_pct >= 0 ? "+" : "") + p.pnl_pct.toFixed(2) + '%)</small><br>' + progBar + '</td>' +
                (function() {{ var tp=p.tp||0, ep=p.entry_price||0, lev=p.leverage||10, mg=p.margin||0; if(!tp||!ep) return '<td class="muted">\u2014</td>'; var c=mg*lev/ep, g=(ep-tp)*c, cf=tp*c*0.001, n=g-cf; return '<td class="'+(n>0?"positive":(n<0?"negative":"muted"))+'">+'+ n.toFixed(4)+'</td>'; }})() +
                '<td>' + (function() {{ var tp=p.tp||0, ep=p.entry_price||0, lev=p.leverage||10; if(!tp||!ep) return '\u2014'; return ((ep-tp)/ep*lev*100).toFixed(1)+'%'; }})() + '</td>' +
                '<td>' + fmtP(p.entry_price) + '</td>' +
                '<td>' + fmtP(p.current_price) + '</td>' +
                '<td>' + p.leverage.toFixed(0) + 'x</td>' +
                '<td>' + p.margin.toFixed(2) + ' <small class="muted">(' + marginPct + '%)</small></td>' +
                '<td>' + fmtP(p.sl) + '</td>' +
                '<td>' + fmtP(p.tp) + '</td>' +
                '<td>' + fmtP(p.break_even_price) + '</td>' +
                '<td class="liq-price">' + fmtP(p.liq_price) + '</td>' +
                (function() {{ var df=p.deducted_fee||0; var cls=df>0?"negative":(df<0?"positive":"muted"); return '<td class="'+cls+'">'+(df!==0?(-df>0?"+":"")+(-df).toFixed(4):"0.0000")+'</td>'; }})() +
                (function() {{ var ff=p.funding_fee||0; var cls=ff>0?"ft-pos":(ff<0?"negative":"muted"); return '<td class="'+cls+'" style="text-align:right">'+(ff>0?ff.toFixed(4):(ff<0?ff.toFixed(4):"0.0000"))+'</td>'; }})() +
                '<td>' + (function() {{ var d=p.days_since_liq; if(d===undefined||d===null||d<0) return "\u2014"; if(d>=1000) return (d-1000)+"d+"; return d+"d"; }})() + '</td>' +
                '<td>' + p.opened_str + '</td>' +
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
        // Display newest first
        var newest = positions.slice().sort(function(a,b) {{ return (b.opened_ts||0) - (a.opened_ts||0); }});
        for (var i = 0; i < newest.length; i++) {{
            var p = newest[i];
            var ep = p.entry_price || 0;
            var fee = p.deducted_fee || 0;
            var closeFeeEst = Math.abs((p.margin || 0) * (p.leverage || 10) * 0.001);
            var potNet = (p.unrealized_pnl || 0) - fee - closeFeeEst;
            var netCls = potNet >= 0 ? "positive" : "negative";
            var pp = p.price_precision || 4;
            html += '<div class="close-row close-open">' +
                '<span class="close-sym">' + p.base + ' <span class="pos-dot"></span></span>' +
                '<span class="close-price">' + ep.toFixed(pp) + '</span>' +
                '<span class="close-price muted">\u2014</span>' +
                '<span class="close-fee">' + fee.toFixed(3) + '</span>' +
                '<span class="close-delta ' + netCls + '">' + (potNet >= 0 ? "+" : "") + potNet.toFixed(3) + '</span>' +
                '<span class="close-bal close-bal-open">' + balance.toFixed(2) + '</span>' +
                '<span class="close-bal-delta muted">\u2014</span>' +
                (function() {{ var ts=p.opened_ts||0; if(!ts) return '<span class="close-time"><span class="time-full">\u2014</span><span class="time-short">\u2014</span></span></div>'; var sec=(Date.now()/1000)-ts; var d=sec>=86400?Math.floor(sec/86400)+"d":(sec>=3600?Math.floor(sec/3600)+"h":Math.floor(sec/60)+"m"); return '<span class="close-time"><span class="time-full">'+(p.opened_short_str||p.opened_str)+'</span><span class="time-short">'+d+'</span></span></div>'; }})();
        }}

        // Closed shorts
        var prevBal = null;
        for (var j = 0; j < closes.length; j++) {{
            var c = closes[j];
            var net = c.net || 0;
            var netCls = net >= 0 ? "positive" : "negative";
            var symCls = net < 0 ? "negative" : "";
            var exitCls = (c.exit_price || 0) > (c.entry_price || 0) ? "negative" : "";
            var ep = c.entry_price || 0;
            var xp = c.exit_price || 0;
            var fees = c.fees || 0;
            var bal = c.balance || 0;

            // Duration
            var ds = c.duration_sec || 0;
            var durStr = ds < 60 ? Math.round(ds) + "s" : (ds < 3600 ? Math.round(ds/60) + "m" : (ds/3600).toFixed(1) + "h");

            var dt = new Date(c.timestamp * 1000);
            var timeStr = dt.toLocaleDateString("en", {{month:"short",day:"2-digit"}}) + " " + dt.toLocaleTimeString("en", {{hour:"2-digit",minute:"2-digit",hour12:false}}) + " (" + durStr + ")";

            // Balance delta
            var bdCls = "muted";
            var bdStr = "\u2014";
            if (prevBal !== null && bal > 0) {{
                var bd = Math.round((bal - prevBal) * 100) / 100;
                bdCls = bd >= 0 ? "positive" : "negative";
                bdStr = (bd >= 0 ? "+" : "") + bd.toFixed(2);
            }}
            prevBal = bal;

            // Price precision
            var epS = ep.toString();
            var pp = epS.indexOf(".") >= 0 ? epS.replace(/0+$/, "").split(".")[1].length : 0;

            html += '<div class="close-row">' +
                '<span class="close-sym ' + symCls + '">' + c.symbol + '</span>' +
                '<span class="close-price">' + ep.toFixed(pp) + '</span>' +
                '<span class="close-price ' + exitCls + '">' + xp.toFixed(pp) + '</span>' +
                '<span class="close-fee fee-tip-wrap"><span class="fee-tip-trigger">' + fees.toFixed(3) + '</span><span class="fee-tip">' + buildFeeTip(c.open_fee||0, c.close_fee||0, c.funding_fee||0, c.close_profit||0) + '</span></span>' +
                '<span class="close-delta ' + netCls + '">' + (net >= 0 ? "+" : "") + net.toFixed(3) + '</span>' +
                '<span class="close-bal">' + bal.toFixed(2) + '</span>' +
                '<span class="close-bal-delta ' + bdCls + '">' + bdStr + '</span>' +
                (function() {{ var ds=c.duration_sec||0; var d=ds>=86400?Math.floor(ds/86400)+"d":(ds>=3600?Math.floor(ds/3600)+"h":(ds>=60?Math.floor(ds/60)+"m":Math.floor(ds)+"s")); return '<span class="close-time"><span class="time-full">'+timeStr+'</span><span class="time-short">'+d+'</span></span></div>'; }})();
        }}

        container.innerHTML = html || '<div class="muted" style="padding:10px 0">No shorts yet</div>';
    }})
    .catch(function(e) {{
        icon.classList.remove("spinning");
        console.error("Shorts refresh error:", e);
    }});
}}

// Table sorting — direction from data-sort attribute or default DESC
(function() {{
    var table = document.getElementById("scan-table");
    if (!table) return;
    var headers = table.querySelectorAll("th.sortable");
    headers.forEach(function(th) {{
        th.addEventListener("click", function(e) {{
            e.stopPropagation();
            var col = parseInt(th.getAttribute("data-col"));
            var dir = th.getAttribute("data-sort") || "desc";
            headers.forEach(function(h) {{ h.removeAttribute("data-dir"); }});
            th.setAttribute("data-dir", dir);
            var tbody = table.querySelector("tbody");
            var rows = Array.from(tbody.querySelectorAll("tr"));
            rows.sort(function(a, b) {{
                var aVal = parseFloat((a.children[col] || {{}}).getAttribute("data-v")) || 0;
                var bVal = parseFloat((b.children[col] || {{}}).getAttribute("data-v")) || 0;
                return dir === "asc" ? aVal - bVal : bVal - aVal;
            }});
            rows.forEach(function(r) {{ tbody.appendChild(r); }});
        }});
    }});
}})();

// Backtest engine
function runBacktest(symbol, btn) {{
    var section = btn.closest(".backtest-section");
    var period = parseInt(section.querySelector(".backtest-period").value);
    var tf = section.querySelector(".backtest-tf").value;
    var balance = parseFloat(section.querySelector(".backtest-balance").value);
    var betPct = parseInt(section.querySelector(".backtest-bet").value) / 100;
    var roi = parseFloat(section.querySelector(".backtest-roi").value);
    var resultsEl = section.querySelector(".backtest-results");
    var leverage = 10;
    var takerRate = 0.001;

    btn.disabled = true;
    btn.textContent = "Loading...";
    resultsEl.style.display = "block";
    resultsEl.innerHTML = '<div class="muted">Fetching candles...</div>';

    var apiBase = window.location.protocol + "//" + window.location.hostname + ":8432";

    // Fetch candles and funding rates in parallel
    Promise.all([
        fetch(apiBase + "/api/candles?symbol=" + encodeURIComponent(symbol) + "&tf=" + tf + "&days=" + period).then(function(r) {{ return r.json(); }}),
        fetch(apiBase + "/api/funding-history?symbol=" + encodeURIComponent(symbol) + "&days=" + period).then(function(r) {{ return r.json(); }})
    ]).then(function(results) {{
        var candleData = results[0];
        var fundingData = results[1];

        if (!candleData.ok || !candleData.candles || candleData.candles.length < 2) {{
            resultsEl.innerHTML = '<div class="negative">No candle data</div>';
            btn.disabled = false;
            btn.textContent = "Emulate";
            return;
        }}

        var candles = candleData.candles;
        var fundingRates = (fundingData.ok && fundingData.rates) ? fundingData.rates : [];

        // Build funding rate lookup: timestamp → rate
        var fundingMap = {{}};
        fundingRates.forEach(function(fr) {{ fundingMap[fr.timestamp] = fr.rate; }});

        // Backtest logic
        var trades = [];
        var bal = balance;
        var position = null;
        var tpPricePct = roi / leverage / 100;

        for (var i = 0; i < candles.length; i++) {{
            var c = candles[i]; // [ts, open, high, low, close, vol]
            var ts = c[0], open = c[1], high = c[2], low = c[3], close = c[4];

            if (!position) {{
                // Open short at close price
                var entry = close;
                var margin = bal * betPct;
                if (margin <= 0) break;
                var notional = margin * leverage;
                var contracts = notional / entry;
                var openFee = notional * takerRate;
                var tpPrice = entry * (1 - tpPricePct);
                position = {{
                    entry: entry, tp: tpPrice, contracts: contracts,
                    margin: margin, notional: notional, openFee: openFee,
                    openTs: ts, funding: 0
                }};
                continue;
            }}

            // Check funding (every 8h: 00:00, 08:00, 16:00 UTC)
            var fundTs = Object.keys(fundingMap).map(Number);
            fundTs.forEach(function(ft) {{
                if (ft > position.openTs && ft <= ts && !position["_f" + ft]) {{
                    position.funding += position.notional * fundingMap[ft];
                    position["_f" + ft] = true;
                }}
            }});

            // Check TP hit (low <= tp for SHORT)
            if (low <= position.tp) {{
                var closeFee = position.tp * position.contracts * takerRate;
                var gross = (position.entry - position.tp) * position.contracts;
                var net = gross - position.openFee - closeFee + position.funding;
                bal += net;
                trades.push({{
                    entry: position.entry, exit: position.tp, gross: gross,
                    openFee: position.openFee, closeFee: closeFee,
                    funding: position.funding, net: net, balance: bal,
                    openTs: position.openTs, closeTs: ts, _closeIdx: i, result: "TP"
                }});
                position = null;
                continue;
            }}

            // Check liquidation: cross margin — unrealized loss vs total balance
            var unrealized = (close - position.entry) * position.contracts;
            if (unrealized > bal * 0.9) {{
                var loss = -bal;
                bal += loss;
                trades.push({{
                    entry: position.entry, exit: close, gross: loss,
                    openFee: position.openFee, closeFee: 0,
                    funding: position.funding, net: loss, balance: bal,
                    openTs: position.openTs, closeTs: ts, _closeIdx: i, result: "LIQ"
                }});
                position = null;
                break;
            }}
        }}

        // Render results
        var html = '<div class="bt-row bt-header"><span style="width:40px">#</span><span style="width:70px">Entry</span><span style="width:70px">Exit</span><span style="width:60px">Net</span><span style="width:60px">Balance</span><span style="width:50px">Dur</span><span style="width:30px"></span></div>';
        trades.forEach(function(t, idx) {{
            var dur = Math.round((t.closeTs - t.openTs) / 60000);
            var durStr = dur < 60 ? dur + "m" : (dur < 1440 ? Math.floor(dur/60) + "h" : Math.floor(dur/1440) + "d");
            var cls = t.net >= 0 ? "positive" : "negative";
            var resCls = t.result === "LIQ" ? "negative" : cls;
            html += '<div class="bt-row"><span style="width:40px">' + (idx+1) + '</span><span style="width:70px">' + t.entry.toPrecision(5) + '</span><span style="width:70px">' + t.exit.toPrecision(5) + '</span><span style="width:60px" class="' + cls + '">' + (t.net >= 0 ? "+" : "") + t.net.toFixed(3) + '</span><span style="width:60px">' + t.balance.toFixed(2) + '</span><span style="width:50px">' + durStr + '</span><span style="width:30px" class="' + resCls + '">' + t.result + '</span></div>';
        }});

        // Summary
        var totalNet = trades.reduce(function(s, t) {{ return s + t.net; }}, 0);
        var wins = trades.filter(function(t) {{ return t.net > 0; }}).length;
        var losses = trades.length - wins;
        var liq = trades.some(function(t) {{ return t.result === "LIQ"; }});
        html += '<div class="bt-summary">';
        html += '<b>Trades:</b> ' + trades.length + ' (W:' + wins + ' L:' + losses + ')<br>';
        html += '<b>Net P&L:</b> <span class="' + (totalNet >= 0 ? "positive" : "negative") + '">' + (totalNet >= 0 ? "+" : "") + totalNet.toFixed(4) + ' USDT</span><br>';
        html += '<b>Balance:</b> ' + balance.toFixed(2) + ' &rarr; ' + bal.toFixed(2) + ' (' + ((bal - balance) / balance * 100).toFixed(1) + '%)<br>';
        html += '<b>Candles:</b> ' + candles.length + ' (' + tf + ')<br>';
        if (liq) {{
            var liqTrade = trades[trades.length - 1];
            var liqMs = liqTrade.closeTs - candles[0][0];
            var liqH = Math.floor(liqMs / 3600000);
            var liqStr = liqH < 24 ? liqH + "h" : Math.floor(liqH / 24) + "d " + (liqH % 24) + "h";
            html += '<span class="negative"><b>LIQUIDATED</b> after ' + liqStr + ' from start</span>';
        }}
        html += '</div>';

        // Chart placeholder
        html += '<div class="bt-chart"><span class="spinner"></span></div>';
        resultsEl.innerHTML = html;

        // Generate chart
        var chartTrades = trades.map(function(t) {{
            return {{closeIdx: t._closeIdx, closePrice: t.exit, net: t.net, result: t.result}};
        }});
        var liqIdx = liq ? trades[trades.length-1]._closeIdx : null;

        fetch(apiBase + "/api/backtest-chart", {{
            method: "POST",
            headers: {{"Content-Type": "application/json"}},
            body: JSON.stringify({{candles: candles, trades: chartTrades, liqIdx: liqIdx}})
        }})
        .then(function(r) {{ return r.blob(); }})
        .then(function(blob) {{
            var chartEl = resultsEl.querySelector(".bt-chart");
            if (chartEl) {{
                var url = URL.createObjectURL(blob);
                chartEl.innerHTML = '<img src="' + url + '" style="width:100%;border-radius:6px;border:1px solid #21262d">';
            }}
        }})
        .catch(function() {{
            var chartEl = resultsEl.querySelector(".bt-chart");
            if (chartEl) chartEl.innerHTML = '<div class="muted">Chart unavailable</div>';
        }});

        btn.disabled = false;
        btn.textContent = "Emulate";
    }}).catch(function(e) {{
        resultsEl.innerHTML = '<div class="negative">Error: ' + e.message + '</div>';
        btn.disabled = false;
        btn.textContent = "Emulate";
    }});
}}

// Fee breakdown tooltip builder
function buildFeeTip(of, cf, ff, cp) {{
    var pp = cp + ff - of - cf;
    function fv(v) {{
        if (v === 0) return '<span class="ft-zero">  0.00000000</span>';
        return v > 0
            ? '<span class="ft-pos">+' + v.toFixed(8) + '</span>'
            : '<span class="ft-neg">' + v.toFixed(8) + '</span>';
    }}
    return '<b>Fee breakdown</b>' +
        '<div class="ft-row"><span class="ft-label">Closing profit</span>' + fv(cp) + '</div>' +
        '<div class="ft-row"><span class="ft-label">Funding fee</span>' + fv(ff) + '</div>' +
        '<div class="ft-row"><span class="ft-label">Opening fee</span>' + fv(-of) + '</div>' +
        '<div class="ft-row"><span class="ft-label">Closing fee</span>' + fv(-cf) + '</div>' +
        '<div class="ft-row ft-sep"><span class="ft-label">Position PnL</span>' + fv(pp) + '</div>';
}}

// Cache chart URLs from initial render for position rows
var _chartCache = {{}};
document.querySelectorAll("#positions-body .scan-row").forEach(function(row) {{
    var sym = row.getAttribute("data-symbol");
    if (sym) {{
        _chartCache[sym] = {{
            "1m": row.getAttribute("data-1m") || "",
            "15m": row.getAttribute("data-15m") || "",
            "1h": row.getAttribute("data-1h") || ""
        }};
    }}
}});

// Auto-refresh on page load
refreshPositions();
refreshShorts();

// Toast notifications
var _toastContainer;
function showToast(title, body, duration) {{
    if (!_toastContainer) {{
        _toastContainer = document.createElement("div");
        _toastContainer.className = "toast-container";
        document.body.appendChild(_toastContainer);
    }}
    var toast = document.createElement("div");
    toast.className = "toast";
    toast.innerHTML = '<div class="toast-title">' + title + '</div><div class="toast-body">' + body + '</div>';
    _toastContainer.appendChild(toast);
    setTimeout(function() {{
        toast.classList.add("toast-out");
        setTimeout(function() {{ toast.remove(); }}, 300);
    }}, duration || 4000);
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
