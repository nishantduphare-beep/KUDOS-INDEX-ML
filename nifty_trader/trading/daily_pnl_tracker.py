"""
Daily P&L Tracker — Track realized profits/losses for the day.

Monitors:
  • Total realized P&L
  • Win rate
  • Average win/loss
  • Daily loss limit enforcement
"""

import logging
from datetime import datetime, date
from typing import Optional, Dict, List

from sqlalchemy import text

try:
    import config
except ImportError:
    import nifty_trader.config as config

logger = logging.getLogger(__name__)


class DailyPnLTracker:
    """Track daily P&L for live trading risk management"""
    
    def __init__(self, db):
        self.db = db
        self.trades_today: List[dict] = []
        self._refresh()
    
    def _refresh(self):
        """Reload trades from database for today"""
        try:
            today_str = datetime.now().strftime('%Y-%m-%d')
            with self.db.get_session() as session:
                result = session.execute(
                    text("SELECT * FROM trade_outcomes WHERE DATE(entry_time) = DATE(:d)"),
                    {"d": today_str}
                )
                self.trades_today = [dict(r._mapping) for r in result]
        except Exception as e:
            logger.error(f"Error refreshing daily trades: {e}")
            self.trades_today = []
    
    def get_daily_pnl(self) -> float:
        """Get total realized P&L for today"""
        self._refresh()
        
        total_pnl = 0.0
        for trade in self.trades_today:
            if trade.get('status') == 'CLOSED' and trade.get('realized_pnl') is not None:
                total_pnl += trade['realized_pnl']
        
        return total_pnl
    
    def get_daily_metrics(self) -> Dict:
        """Get comprehensive daily trading metrics"""
        self._refresh()
        
        closed_trades = [t for t in self.trades_today if t.get('status') == 'CLOSED']
        
        if not closed_trades:
            return {
                'total_trades': 0,
                'wins': 0,
                'losses': 0,
                'win_rate': 0,
                'total_pnl': 0,
                'avg_win': 0,
                'avg_loss': 0,
                'profit_factor': 0,
                'largest_win': 0,
                'largest_loss': 0,
            }
        
        pnls = [t.get('realized_pnl', 0) for t in closed_trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        
        total_pnl = sum(pnls)
        total_wins = sum(wins) if wins else 0
        total_losses = abs(sum(losses)) if losses else 0
        
        profit_factor = total_wins / total_losses if total_losses > 0 else 0
        
        return {
            'total_trades': len(closed_trades),
            'wins': len(wins),
            'losses': len(losses),
            'win_rate': (len(wins) / len(closed_trades) * 100) if closed_trades else 0,
            'total_pnl': total_pnl,
            'avg_win': sum(wins) / len(wins) if wins else 0,
            'avg_loss': sum(losses) / len(losses) if losses else 0,
            'profit_factor': profit_factor,
            'largest_win': max(wins) if wins else 0,
            'largest_loss': min(losses) if losses else 0,
        }
    
    def check_daily_loss_limit(self) -> tuple:
        """
        Check if daily loss has exceeded limit.
        
        Returns:
            (exceeded: bool, current_loss: float, limit: float)
        """
        
        daily_pnl = self.get_daily_pnl()
        daily_loss = abs(daily_pnl) if daily_pnl < 0 else 0
        
        limit_exceeded = daily_loss >= config.MAX_DAILY_LOSS_RUPEES
        
        return limit_exceeded, daily_loss, config.MAX_DAILY_LOSS_RUPEES
    
    def should_halt_trading(self) -> tuple:
        """
        Determine if trading should be halted based on daily loss.
        
        Returns:
            (should_halt: bool, reason: str)
        """
        
        if not config.LIVE_TRADING_MODE:
            return False, "Live trading disabled"
        
        limit_exceeded, daily_loss, limit = self.check_daily_loss_limit()
        
        if limit_exceeded:
            return True, f"Daily loss limit exceeded: ₹{daily_loss:.0f} / ₹{limit:.0f}"
        
        return False, "Trading allowed"
    
    def get_today_trades(self) -> List[Dict]:
        """Get all trades from today"""
        self._refresh()
        return self.trades_today
    
    def reset_daily_stats(self):
        """Reset tracker (for new day)"""
        self.trades_today = []
        logger.info("Daily P&L tracker reset")


def track_daily_pnl(db) -> float:
    """Simple utility to get daily P&L"""
    tracker = DailyPnLTracker(db)
    return tracker.get_daily_pnl()


def get_daily_metrics(db) -> Dict:
    """Simple utility to get daily metrics"""
    tracker = DailyPnLTracker(db)
    return tracker.get_daily_metrics()


# Global instance
_tracker: Optional[DailyPnLTracker] = None


def init_daily_pnl_tracker(db) -> DailyPnLTracker:
    """Initialize global tracker"""
    global _tracker
    _tracker = DailyPnLTracker(db)
    return _tracker


def get_daily_pnl_tracker() -> Optional[DailyPnLTracker]:
    """Get global tracker"""
    return _tracker
