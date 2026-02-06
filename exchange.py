"""
Bitget exchange API wrapper using ccxt.
Handles all communication with the exchange.
"""

import ccxt
import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class Exchange:
    def __init__(self, config: dict):
        self.config = config
        self.leverage = config.get("leverage", 10)

        exchange_params = {
            "apiKey": config["api_key"],
            "secret": config["api_secret"],
            "password": config.get("passphrase", ""),
            "options": {
                "defaultType": "swap",
                "defaultSubType": "linear",
            },
        }

        if config.get("demo", True):
            exchange_params["options"]["sandboxMode"] = True
            logger.info("Running in DEMO mode")
        else:
            logger.warning("Running in LIVE mode — real money at risk!")

        self.exchange = ccxt.bitget(exchange_params)

        if config.get("demo", True):
            self.exchange.set_sandbox_mode(True)

    def load_markets(self):
        """Load all available markets."""
        self.exchange.load_markets()
        logger.info(f"Loaded {len(self.exchange.markets)} markets")

    def get_usdt_futures_symbols(self) -> list[str]:
        """Get all USDT perpetual futures symbols."""
        symbols = []
        for symbol, market in self.exchange.markets.items():
            if (
                market.get("swap")
                and market.get("linear")
                and market.get("active")
                and market.get("quote") == "USDT"
            ):
                symbols.append(symbol)
        logger.info(f"Found {len(symbols)} USDT perpetual futures pairs")
        return symbols

    def get_ohlcv(
        self, symbol: str, timeframe: str = "15m", limit: int = 100
    ) -> list:
        """Fetch OHLCV candles for a symbol."""
        try:
            candles = self.exchange.fetch_ohlcv(
                symbol, timeframe=timeframe, limit=limit
            )
            return candles
        except Exception as e:
            logger.error(f"Error fetching OHLCV for {symbol}: {e}")
            return []

    def get_ticker(self, symbol: str) -> Optional[dict]:
        """Fetch current ticker for a symbol."""
        try:
            return self.exchange.fetch_ticker(symbol)
        except Exception as e:
            logger.error(f"Error fetching ticker for {symbol}: {e}")
            return None

    def get_balance(self) -> float:
        """Get total USDT balance (free + used)."""
        try:
            balance = self.exchange.fetch_balance()
            total = balance.get("total", {}).get("USDT", 0)
            return float(total) if total else 0.0
        except Exception as e:
            logger.error(f"Error fetching balance: {e}")
            return 0.0

    def get_open_positions(self) -> list[dict]:
        """Get all open positions."""
        try:
            positions = self.exchange.fetch_positions()
            open_positions = []
            for pos in positions:
                contracts = float(pos.get("contracts", 0))
                if contracts > 0:
                    open_positions.append(
                        {
                            "symbol": pos["symbol"],
                            "side": pos["side"],
                            "contracts": contracts,
                            "entry_price": float(pos.get("entryPrice", 0)),
                            "unrealized_pnl": float(
                                pos.get("unrealizedPnl", 0)
                            ),
                            "leverage": float(pos.get("leverage", 0)),
                            "margin": float(
                                pos.get("initialMargin", 0)
                                or pos.get("collateral", 0)
                            ),
                            "notional": float(pos.get("notional", 0)),
                            "percentage": float(pos.get("percentage", 0)),
                        }
                    )
            return open_positions
        except Exception as e:
            logger.error(f"Error fetching positions: {e}")
            return []

    def set_leverage(self, symbol: str, leverage: int):
        """Set leverage for a symbol."""
        try:
            self.exchange.set_leverage(leverage, symbol)
            logger.info(f"Set leverage {leverage}x for {symbol}")
        except Exception as e:
            logger.warning(f"Could not set leverage for {symbol}: {e}")

    def set_margin_mode(self, symbol: str, mode: str = "cross"):
        """Set margin mode (cross or isolated)."""
        try:
            self.exchange.set_margin_mode(mode, symbol)
        except Exception as e:
            # Often fails if already set — that's fine
            logger.debug(f"Margin mode note for {symbol}: {e}")

    def open_short(
        self,
        symbol: str,
        amount_usdt: float,
        stop_loss_price: float,
        take_profit_price: float,
    ) -> Optional[dict]:
        """
        Open a short position with SL and TP.
        amount_usdt: margin amount in USDT (will be multiplied by leverage on exchange)
        """
        try:
            self.set_margin_mode(symbol, "cross")
            self.set_leverage(symbol, self.leverage)

            ticker = self.get_ticker(symbol)
            if not ticker:
                return None

            current_price = ticker["last"]

            # Calculate position size in contracts
            # amount_usdt is the margin, position value = margin * leverage
            position_value = amount_usdt * self.leverage
            amount = position_value / current_price

            # Get market info for precision
            market = self.exchange.markets.get(symbol)
            if market:
                amount = self.exchange.amount_to_precision(symbol, amount)
                amount = float(amount)

            logger.info(
                f"Opening SHORT {symbol}: amount={amount}, "
                f"price={current_price}, SL={stop_loss_price}, TP={take_profit_price}"
            )

            # Place the short order
            order = self.exchange.create_order(
                symbol=symbol,
                type="market",
                side="sell",
                amount=amount,
                params={
                    "stopLoss": {
                        "triggerPrice": stop_loss_price,
                        "type": "market",
                    },
                    "takeProfit": {
                        "triggerPrice": take_profit_price,
                        "type": "market",
                    },
                },
            )

            logger.info(f"Order placed: {order['id']}")

            return {
                "order_id": order["id"],
                "symbol": symbol,
                "side": "short",
                "entry_price": current_price,
                "amount": amount,
                "margin_usdt": amount_usdt,
                "stop_loss": stop_loss_price,
                "take_profit": take_profit_price,
                "timestamp": time.time(),
            }

        except Exception as e:
            logger.error(f"Error opening short for {symbol}: {e}")
            return None

    def update_stop_loss(self, symbol: str, new_sl_price: float) -> bool:
        """Update stop-loss for an open position."""
        try:
            open_orders = self.exchange.fetch_open_orders(symbol)
            for order in open_orders:
                if order.get("stopPrice") and order.get("side") == "buy":
                    self.exchange.cancel_order(order["id"], symbol)
                    logger.info(f"Cancelled old SL order for {symbol}")

            # Place new SL
            positions = self.exchange.fetch_positions([symbol])
            for pos in positions:
                if float(pos.get("contracts", 0)) > 0 and pos["side"] == "short":
                    amount = float(pos["contracts"])
                    self.exchange.create_order(
                        symbol=symbol,
                        type="market",
                        side="buy",
                        amount=amount,
                        params={
                            "stopLoss": {
                                "triggerPrice": new_sl_price,
                                "type": "market",
                            },
                        },
                    )
                    logger.info(
                        f"Updated SL for {symbol} to {new_sl_price}"
                    )
                    return True
            return False
        except Exception as e:
            logger.error(f"Error updating SL for {symbol}: {e}")
            return False

    def get_funding_rate(self, symbol: str) -> Optional[float]:
        """Get current funding rate for a symbol."""
        try:
            funding = self.exchange.fetch_funding_rate(symbol)
            rate = funding.get("fundingRate", 0)
            return float(rate) if rate else 0.0
        except Exception as e:
            logger.debug(f"Could not get funding rate for {symbol}: {e}")
            return None

    def get_btc_24h_change(self) -> float:
        """Get BTC/USDT 24h price change percentage."""
        ticker = self.get_ticker("BTC/USDT:USDT")
        if ticker and ticker.get("percentage") is not None:
            return float(ticker["percentage"])
        return 0.0
