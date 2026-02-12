"""
Risk management module: safety checks, position sizing, trailing stops.
"""

import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)


class RiskManager:
    def __init__(self, config: dict):
        self.config = config
        self.daily_loss_limit = config.get("daily_loss_limit_pct", 5.0)
        self.btc_bull_limit = config.get("btc_bull_limit_pct", 5.0)
        self.max_positions = config.get("max_positions", 5)
        self.news_blackout_minutes = config.get("news_blackout_minutes", 30)
        self.trailing_start_pct = config.get("trailing_start_pct", 3.0)
        self.trailing_distance_pct = config.get("trailing_distance_pct", 2.0)

    def check_daily_loss(
        self, start_balance: float, current_balance: float
    ) -> tuple[bool, str]:
        """
        Check if daily loss limit has been exceeded.
        Returns (is_safe, reason).
        """
        if start_balance <= 0:
            return False, "Start balance is zero or negative"

        loss_pct = ((start_balance - current_balance) / start_balance) * 100

        if loss_pct >= self.daily_loss_limit:
            msg = (
                f"Daily loss limit reached: -{loss_pct:.2f}% "
                f"(limit: -{self.daily_loss_limit}%)"
            )
            logger.warning(msg)
            return False, msg

        return True, f"Daily P&L: {-loss_pct:.2f}%"

    def check_btc_trend(self, btc_24h_change: float) -> tuple[bool, str]:
        """
        Check if BTC is in a strong bull run.
        Returns (is_safe, reason).
        """
        if btc_24h_change >= self.btc_bull_limit:
            msg = (
                f"BTC bull market detected: +{btc_24h_change:.2f}% "
                f"(limit: +{self.btc_bull_limit}%)"
            )
            logger.warning(msg)
            return False, msg

        return True, f"BTC 24h: {btc_24h_change:+.2f}%"

    def check_news_blackout(self) -> tuple[bool, str]:
        """
        Check if we're in a news blackout window.
        Returns (is_safe, reason).
        """
        now = datetime.now(timezone.utc)
        events = self.config.get("news_events", [])

        for event in events:
            try:
                event_dt = datetime.strptime(
                    f"{event['date']} {event['time']}", "%Y-%m-%d %H:%M"
                ).replace(tzinfo=timezone.utc)

                blackout_start = event_dt - timedelta(
                    minutes=self.news_blackout_minutes
                )
                blackout_end = event_dt + timedelta(
                    minutes=self.news_blackout_minutes
                )

                if blackout_start <= now <= blackout_end:
                    msg = (
                        f"News blackout: {event['event']} at "
                        f"{event['date']} {event['time']} UTC"
                    )
                    logger.warning(msg)
                    return False, msg
            except (KeyError, ValueError) as e:
                logger.debug(f"Invalid news event entry: {e}")
                continue

        return True, "No news blackout"

    def check_position_count(
        self, open_positions: int
    ) -> tuple[bool, str]:
        """
        Check if max positions limit is reached.
        Returns (is_safe, reason).
        """
        if open_positions >= self.max_positions:
            msg = (
                f"Max positions reached: {open_positions}/{self.max_positions}"
            )
            logger.info(msg)
            return False, msg

        return True, f"Positions: {open_positions}/{self.max_positions}"

    def run_all_checks(
        self,
        start_balance: float,
        current_balance: float,
        btc_24h_change: float,
        open_positions: int,
    ) -> tuple[bool, list[str]]:
        """
        Run all safety checks.
        Returns (all_passed, list_of_reasons).
        """
        reasons = []
        all_passed = True

        checks = [
            self.check_btc_trend(btc_24h_change),
            self.check_news_blackout(),
            self.check_position_count(open_positions),
        ]

        for passed, reason in checks:
            reasons.append(f"{'✅' if passed else '❌'} {reason}")
            if not passed:
                all_passed = False

        return all_passed, reasons

    def check_oi_spike(
        self, oi_changes: list[dict]
    ) -> tuple[bool, str]:
        """
        Check if any symbol has an extreme OI change.
        oi_changes: list of {symbol, oi_change_pct}
        Returns (is_safe, reason).
        """
        threshold = self.config.get("oi_spike_pct", 10.0)
        spiked = [
            c for c in oi_changes
            if abs(c["oi_change_pct"]) >= threshold
        ]
        if spiked:
            top = sorted(spiked, key=lambda c: abs(c["oi_change_pct"]), reverse=True)[:3]
            names = ", ".join(
                f"{c['symbol'].split('/')[0]} {c['oi_change_pct']:+.1f}%"
                for c in top
            )
            msg = f"OI spike detected: {names} (limit: {threshold}%)"
            logger.warning(msg)
            return False, msg

        if oi_changes:
            avg = sum(c["oi_change_pct"] for c in oi_changes) / len(oi_changes)
            return True, f"OI avg change: {avg:+.1f}% ({len(oi_changes)} pairs)"
        return True, "OI: no data"

    def check_market_volume(
        self, market_volume_ratio: float
    ) -> tuple[bool, str]:
        """
        Check if market-wide volume is abnormally high.
        market_volume_ratio: average (current_volume / avg_volume) across symbols.
        Returns (is_safe, reason).
        """
        threshold = self.config.get("market_volume_spike_multiplier", 3.0)
        if market_volume_ratio >= threshold:
            msg = (
                f"Market volume spike: {market_volume_ratio:.1f}x avg "
                f"(limit: {threshold}x)"
            )
            logger.warning(msg)
            return False, msg

        return True, f"Market volume: {market_volume_ratio:.1f}x avg"

    def calculate_position_size(
        self, balance: float, open_positions: int
    ) -> float:
        """
        Calculate margin amount for a new position.
        Divides available balance equally among max positions.
        """
        slots = self.max_positions - open_positions
        if slots <= 0:
            return 0.0

        position_pct = self.config.get("position_size_pct", 50) / 100
        margin = balance * position_pct / self.max_positions
        return round(margin, 2)

    def calculate_trailing_stop(
        self, entry_price: float, current_price: float, current_sl: float
    ) -> float | None:
        """
        Calculate new trailing stop-loss for a short position.
        Returns new SL price if it should be updated, None otherwise.

        For SHORT: profit when price goes DOWN.
        - profit_pct = (entry - current) / entry * 100
        - SL is above entry (we buy to close if price rises)
        """
        profit_pct = (entry_price - current_price) / entry_price * 100

        if profit_pct < self.trailing_start_pct:
            return None  # Not enough profit yet

        # Calculate ideal SL: lock in (profit - trailing_distance)
        locked_profit_pct = profit_pct - self.trailing_distance_pct

        if locked_profit_pct <= 0:
            # Move to breakeven
            new_sl = entry_price
        else:
            # SL at entry_price * (1 - locked_profit / 100)
            # For short, SL above current price
            new_sl = entry_price * (1 - locked_profit_pct / 100)

        # Only update if new SL is tighter (lower for short = more protection)
        if new_sl < current_sl:
            return round(new_sl, 8)

        return None
