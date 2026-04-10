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
            self.check_position_count(open_positions),
        ]

        for passed, reason in checks:
            reasons.append(f"{'✅' if passed else '❌'} {reason}")
            if not passed:
                all_passed = False

        return all_passed, reasons

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
