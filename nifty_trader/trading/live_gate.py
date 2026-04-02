"""
Live Trading Gate — Gatekeeper for real money order execution.

Blocks orders that don't meet safety criteria:
  • Live mode explicitly enabled
  • ML confidence threshold
  • Trading hours (9:30-14:45 IST)
  • Position limits
  • Daily loss limits
  • Circuit breaker (ATR spike protection)
"""

import logging
from datetime import datetime, time
from typing import Tuple, Optional

try:
    import config
except ImportError:
    import nifty_trader.config as config

logger = logging.getLogger(__name__)


class LiveTradingGate:
    """Gatekeeper for live trading execution - blocks unsafe trades"""
    
    def __init__(self):
        self.daily_loss = 0.0
        self.trade_count_today = 0
        self.live_enabled = False
        self.open_trades_cache = {}
    
    def can_trade(self, signal_dict: dict, db=None) -> Tuple[bool, str]:
        """
        Check if live trading should execute this signal.
        
        Args:
            signal_dict: Dictionary with keys:
                - ml_confidence: float (0-1)
                - atr: float (current ATR)
                - atr_avg: float (20-period average ATR)
                - symbol: str
                - direction: str (BULLISH/BEARISH)
            db: Database manager instance (optional)
        
        Returns:
            (should_trade: bool, reason: str)
        """
        
        # Rule 1: Live mode explicitly enabled
        if not config.LIVE_TRADING_MODE:
            return False, "Live trading disabled in config"
        
        # Rule 2: Model confidence threshold
        ml_score = signal_dict.get('ml_confidence', 0)
        if ml_score < config.REQUIRED_MODEL_CONFIDENCE:
            return False, f"ML confidence {ml_score:.2f} < {config.REQUIRED_MODEL_CONFIDENCE}"
        
        # Rule 3: Time gates (9:30 - 14:45 IST)
        now = datetime.now()
        market_open = datetime.combine(now.date(), time(9, 30))
        market_close = datetime.combine(now.date(), time(14, 45))
        
        if not (market_open <= now <= market_close):
            return False, f"Outside trading hours ({now.strftime('%H:%M')} IST)"
        
        # Rule 4: Position limit
        open_trades = self._count_open_trades(db)
        if open_trades >= config.MAX_CONCURRENT_TRADES:
            return False, f"Already {open_trades} open trades (max {config.MAX_CONCURRENT_TRADES})"
        
        # Rule 5: Daily loss limit
        if self.daily_loss >= config.MAX_DAILY_LOSS_RUPEES:
            return False, f"Daily loss limit (₹{self.daily_loss:.0f}) exceeded"
        
        # Rule 6: Circuit breaker (excessive volatility)
        atr_current = signal_dict.get('atr', 0)
        atr_normal = signal_dict.get('atr_avg', atr_current)
        
        if atr_normal > 0 and atr_current > atr_normal * config.EMERGENCY_EXIT_THRESHOLD:
            return False, f"Circuit breaker: ATR spike {atr_current:.1f} > {atr_normal * config.EMERGENCY_EXIT_THRESHOLD:.1f}"
        
        # All checks passed
        self.trade_count_today += 1
        logger.info(
            f"✓ Live signal cleared - confidence={ml_score:.2f}, "
            f"open_trades={open_trades}, daily_loss=₹{self.daily_loss:.0f}"
        )
        return True, "Signal cleared for live execution"
    
    def _count_open_trades(self, db=None) -> int:
        """Count currently open trades from database"""
        if db is None:
            return 0
        
        try:
            # Query database for open trades today
            open_outcomes = db.query(
                "SELECT COUNT(*) FROM trade_outcomes WHERE status='OPEN' AND DATE(entry_time)=DATE('now')"
            )
            count = open_outcomes[0][0] if open_outcomes else 0
            return count
        except Exception as e:
            logger.warning(f"Could not count open trades: {e}")
            return 0
    
    def record_trade_outcome(self, alert_id: int, pnl_rupees: float):
        """Track P&L for daily loss limit enforcement"""
        if pnl_rupees < 0:
            self.daily_loss += abs(pnl_rupees)
            logger.warning(
                f"Loss recorded: -{pnl_rupees:.0f}₹ | Daily total: ₹{self.daily_loss:.0f}"
            )
        else:
            logger.info(
                f"Profit recorded: +{pnl_rupees:.0f}₹ | Daily total: ₹{self.daily_loss:.0f}"
            )
    
    def get_status(self) -> dict:
        """Return live gate status for dashboard display"""
        
        loss_percent = 0
        if config.MAX_DAILY_LOSS_RUPEES > 0:
            loss_percent = (self.daily_loss / config.MAX_DAILY_LOSS_RUPEES) * 100
        
        return {
            'live_enabled': config.LIVE_TRADING_MODE,
            'trades_today': self.trade_count_today,
            'daily_loss_rupees': self.daily_loss,
            'daily_loss_limit': config.MAX_DAILY_LOSS_RUPEES,
            'daily_loss_percent': loss_percent,
            'can_trade': self.daily_loss < config.MAX_DAILY_LOSS_RUPEES,
        }
    
    def reset_daily_stats(self):
        """Reset daily counters at market open"""
        self.daily_loss = 0.0
        self.trade_count_today = 0
        logger.info("✓ Daily stats reset")
    
    def emergency_stop(self):
        """Trigger emergency stop - disables all further trading"""
        config.LIVE_TRADING_MODE = False
        logger.critical("🚨 EMERGENCY STOP ACTIVATED - Live trading disabled")


# Global gate instance
_gate: Optional[LiveTradingGate] = None


def get_live_gate() -> LiveTradingGate:
    """Get or create global live trading gate instance"""
    global _gate
    if _gate is None:
        _gate = LiveTradingGate()
        logger.info("Live trading gate initialized")
    return _gate


def reset_live_gate():
    """Reset gate (for testing/daily reset)"""
    global _gate
    if _gate:
        _gate.reset_daily_stats()
