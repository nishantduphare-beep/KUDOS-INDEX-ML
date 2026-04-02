"""
Account Verification — Pre-flight checks for live trading.

Verifies:
  • Account is authenticated
  • Sufficient buying power
  • Can place test orders
  • Broker connectivity
"""

import logging

try:
    import config
except ImportError:
    import nifty_trader.config as config
from typing import Tuple, Dict

logger = logging.getLogger(__name__)


class AccountVerifier:
    """Verify Fyers account is ready for live trading"""
    
    @staticmethod
    def verify_fyers_account(broker) -> Tuple[bool, Dict]:
        """
        Comprehensive Fyers account verification.
        
        Args:
            broker: Broker adapter instance
        
        Returns:
            (success: bool, results: dict)
        """
        results = {
            'authenticated': False,
            'buying_power': 0,
            'can_place_orders': False,
            'errors': [],
        }
        
        try:
            # Check 1: Authentication
            logger.info("Check 1: Fyers authentication...")
            if broker.needs_auth():
                logger.error("✗ Fyers NOT authenticated - OAuth required")
                results['errors'].append("Not authenticated - need OAuth")
                return False, results
            
            logger.info("✓ Fyers authenticated")
            results['authenticated'] = True
            
            # Check 2: Account info
            logger.info("Check 2: Fetching account info...")
            try:
                account_info = broker._fyers.get_profile()
                equity = account_info.get('equity', {})
                buying_power = float(equity.get('brkEqBal', 0))
                
                results['buying_power'] = buying_power
                
                if buying_power < 50000:  # ₹50k minimum
                    msg = f"Insufficient buying power: ₹{buying_power:,.0f}"
                    logger.error(f"✗ {msg}")
                    results['errors'].append(msg)
                    return False, results
                
                logger.info(f"✓ Buying power: ₹{buying_power:,.0f}")
            
            except Exception as e:
                msg = f"Could not fetch account info: {e}"
                logger.error(f"✗ {msg}")
                results['errors'].append(msg)
                return False, results
            
            # Check 3: Test order placement
            logger.info("Check 3: Testing order placement...")
            test_passed = AccountVerifier._test_order_placement(broker)
            
            if not test_passed:
                results['errors'].append("Test order placement failed")
                return False, results
            
            logger.info("✓ Test order placement successful")
            results['can_place_orders'] = True
            
            # All checks passed
            logger.info("✅ All account checks PASSED")
            return True, results
        
        except Exception as e:
            logger.error(f"Account verification error: {e}", exc_info=True)
            results['errors'].append(str(e))
            return False, results
    
    @staticmethod
    def _test_order_placement(broker) -> bool:
        """Test placing a small limit order that won't fill"""
        try:
            # Place tiny limit order that won't fill (1 paisa above market)
            test_response = broker.place_order({
                'symbol': 'NSE:NIFTY50-INDEX',
                'quantity': 0.1,
                'direction': 'BULLISH',
                'order_type': 'LIMIT',
                'limit_price': 0.01,  # Will never fill
                'tag': 'TEST_ORDER_VERIFICATION',
            })
            
            if test_response.get('status') != 'success':
                logger.error(f"Test order failed: {test_response}")
                return False
            
            order_id = test_response.get('id')
            logger.debug(f"Test order created: {order_id}")
            
            # Cancel immediately
            try:
                broker.cancel_order({'id': order_id})
                logger.debug("Test order cancelled successfully")
            except Exception as e:
                logger.warning(f"Could not cancel test order: {e}")
            
            return True
        
        except Exception as e:
            logger.error(f"Test order placement failed: {e}")
            return False


class CircuitBreaker:
    """Automatic market circuit breaker - stops trading on extreme volatility"""
    
    def __init__(self):
        self.triggered = False
        self.trigger_reason = ""
    
    def check_circuit_break(self, data_manager) -> Tuple[bool, str]:
        """
        Check if circuit breaker should trigger.
        
        Returns:
            (should_break: bool, reason: str)
        """
        
        # Check 1: Extreme ATR spike
        try:
            latest_nifty = data_manager.get_latest_candle('NIFTY')
            
            if latest_nifty:
                atr_current = latest_nifty.get('atr', 0)
                atr_avg_20 = latest_nifty.get('atr_20_sma', atr_current)
                
                if atr_avg_20 > 0 and atr_current > atr_avg_20 * 3:
                    reason = f"ATR spike: {atr_current:.1f} > {atr_avg_20 * 3:.1f}"
                    logger.critical(f"🚨 CIRCUIT BREAKER: {reason}")
                    self.triggered = True
                    self.trigger_reason = reason
                    return True, reason
        
        except Exception as e:
            logger.debug(f"Could not check ATR: {e}")
        
        # Check 2: Large spot move in short time
        try:
            latest_spot = data_manager.get_spot_price('NIFTY')
            
            # Get spot from 5 minutes ago (roughly)
            candles = data_manager.get_candles('NIFTY', interval=1, limit=5)
            if candles and len(candles) >= 2:
                old_close = candles[0]['close']
                move = abs(latest_spot - old_close)
                
                if move > 500:  # 500 pt move in 5 min
                    reason = f"Large spot move +{move:.0f}pt in 5min"
                    logger.critical(f"🚨 CIRCUIT BREAKER: {reason}")
                    self.triggered = True
                    self.trigger_reason = reason
                    return True, reason
        
        except Exception as e:
            logger.debug(f"Could not check spot move: {e}")
        
        return False, ""
    
    def reset(self):
        """Reset circuit breaker"""
        self.triggered = False
        self.trigger_reason = ""
        logger.info("Circuit breaker reset")


# Global instance
_circuit_breaker: CircuitBreaker = None


def get_circuit_breaker() -> CircuitBreaker:
    """Get global circuit breaker instance"""
    global _circuit_breaker
    if _circuit_breaker is None:
        _circuit_breaker = CircuitBreaker()
    return _circuit_breaker
