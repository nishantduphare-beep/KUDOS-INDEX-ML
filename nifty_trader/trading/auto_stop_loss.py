"""
Automatic Stop-Loss Execution — Background thread monitors open positions.

Checks every 5 seconds if current price has hit stop-loss level.
If trigger detected, immediately executes market sell order.
CRITICAL FOR LIVE TRADING - user should not need to manually close.
"""

import threading
import time
import logging
from datetime import datetime
from typing import Optional, Callable

logger = logging.getLogger(__name__)


class AutoStopLoss:
    """Automatic stop-loss execution - runs in background thread"""
    
    def __init__(self, db, broker):
        """
        Args:
            db: Database manager instance
            broker: Broker adapter instance (Fyers/Dhan/etc)
        """
        self.db = db
        self.broker = broker
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.check_interval_sec = 5  # Check every 5 seconds
        self.on_sl_triggered: Optional[Callable] = None  # Callback for UI alerts
    
    def start(self):
        """Start background monitoring thread"""
        if self.running:
            logger.warning("AutoStopLoss already running")
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._monitor_loop, daemon=True, name="AutoStopLoss")
        self.thread.start()
        logger.info("✓ AutoStopLoss monitoring started")
    
    def stop(self):
        """Stop monitoring thread"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
            logger.info("✓ AutoStopLoss monitoring stopped")
    
    def _monitor_loop(self):
        """Run in background: check every 5 seconds for SL triggers"""
        while self.running:
            try:
                self._check_all_open_trades()
            except Exception as e:
                logger.error(f"AutoStopLoss error: {e}", exc_info=True)
            
            time.sleep(self.check_interval_sec)
    
    def _check_all_open_trades(self):
        """Check if any open trade has hit stop-loss level"""
        try:
            open_trades = self.db.get_open_trade_outcomes()
        except Exception as e:
            logger.debug(f"Could not fetch open trades: {e}")
            return
        
        for trade in open_trades:
            try:
                # Get current spot price
                current_price = self.broker.get_spot_price(trade.get('index_name', 'NIFTY'))
                
                if current_price is None:
                    logger.debug(f"Could not get price for {trade['index_name']}")
                    continue
                
                # Check if SL hit
                stop_loss = trade.get('stop_loss', 0)
                if stop_loss <= 0:
                    continue
                
                sl_hit = False
                if trade.get('direction') == 'BULLISH' and current_price <= stop_loss:
                    sl_hit = True
                elif trade.get('direction') == 'BEARISH' and current_price >= stop_loss:
                    sl_hit = True
                
                if sl_hit:
                    logger.critical(
                        f"🚨 STOP-LOSS TRIGGERED: {trade['symbol']} "
                        f"at {current_price} (SL: {stop_loss})"
                    )
                    self._execute_stop_loss(trade)
            
            except Exception as e:
                logger.error(f"Error checking trade {trade.get('id')}: {e}")
    
    def _execute_stop_loss(self, trade: dict):
        """Automatically close position at stop-loss"""
        try:
            broker_order_id = trade.get('broker_order_id')
            symbol = trade.get('symbol')
            quantity = trade.get('quantity', 1)
            direction = trade.get('direction')
            
            # Place opposite order to close (if was BULLISH/CALL, sell it)
            sell_direction = 'SELL' if direction == 'BULLISH' else 'BUY'
            
            logger.critical(
                f"Executing auto stop-loss close: {symbol} {quantity} {sell_direction}"
            )
            
            # Send close order via broker
            close_response = self.broker.place_order({
                'symbol': symbol,
                'quantity': quantity,
                'direction': sell_direction,
                'order_type': 'MARKET',
                'tag': f'AUTO_SL_CLOSE_{broker_order_id}',
            })
            
            if close_response and close_response.get('status') == 'success':
                close_order_id = close_response.get('id')
                logger.critical(f"✓ Stop-loss order placed successfully: {close_order_id}")
                
                # Update database
                self.db.update_trade_outcome(broker_order_id, {
                    'sl_hit': True,
                    'sl_hit_time': datetime.now(),
                    'status': 'CLOSED',
                    'close_order_id': close_order_id,
                })
                
                # Trigger callback for UI alert
                if self.on_sl_triggered:
                    self.on_sl_triggered(trade, close_order_id)
            else:
                logger.error(f"Stop-loss close order failed: {close_response}")
                # Alert user for manual intervention
                logger.critical(
                    f"MANUAL ACTION REQUIRED: Auto SL failed for {symbol}, "
                    f"close manually immediately"
                )
        
        except Exception as e:
            logger.error(f"Stop-loss execution FAILED: {e}", exc_info=True)
            logger.critical(f"ALERT USER: Manual SL close required for {trade.get('symbol')}")
    
    def set_on_sl_triggered_callback(self, callback: Callable):
        """Set callback to fire when SL is triggered (for UI updates)"""
        self.on_sl_triggered = callback


# Global instance
_auto_sl: Optional[AutoStopLoss] = None


def init_auto_stop_loss(db, broker) -> AutoStopLoss:
    """Initialize and return global AutoStopLoss instance"""
    global _auto_sl
    _auto_sl = AutoStopLoss(db, broker)
    return _auto_sl


def get_auto_stop_loss() -> Optional[AutoStopLoss]:
    """Get global AutoStopLoss instance"""
    return _auto_sl
