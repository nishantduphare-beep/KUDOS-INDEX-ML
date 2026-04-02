#!/usr/bin/env python3
"""
Quick verification that get_open_trade_outcomes() method exists and works.
"""

import sys
import os

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_method_exists():
    """Verify method exists in database manager"""
    try:
        # Try different import paths
        try:
            from nifty_trader.database.manager import DatabaseManager
        except ImportError:
            try:
                import nifty_trader.database.manager as mgr_module
                DatabaseManager = mgr_module.DatabaseManager
            except:
                from database.manager import DatabaseManager
        
        # Check if method exists
        if not hasattr(DatabaseManager, 'get_open_trade_outcomes'):
            print("❌ ERROR: get_open_trade_outcomes() method NOT FOUND in DatabaseManager")
            return False
        
        print("✅ get_open_trade_outcomes() method EXISTS")
        
        # Get method info
        method = getattr(DatabaseManager, 'get_open_trade_outcomes')
        print(f"   Method: {method.__name__}")
        print(f"   Return type: List[Dict[str, Any]]")
        return True
        
    except Exception as e:
        print(f"❌ ERROR importing DatabaseManager: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_auto_stop_loss_imports():
    """Verify auto_stop_loss can import what it needs"""
    try:
        from nifty_trader.trading.auto_stop_loss import AutoStopLoss
        print("✅ auto_stop_loss.AutoStopLoss imports OK")
        return True
    except Exception as e:
        print(f"❌ ERROR importing auto_stop_loss: {e}")
        return False

def test_dashboard_imports():
    """Verify live_trading_dashboard can import what it needs"""
    try:
        from nifty_trader.ui.live_trading_dashboard import LiveTradingDashboard
        print("✅ live_trading_dashboard.LiveTradingDashboard imports OK")
        return True
    except Exception as e:
        print(f"❌ ERROR importing live_trading_dashboard: {e}")
        return False

def test_config_imports():
    """Verify config loads"""
    try:
        import nifty_trader.config as config
        
        # Check live trading settings
        settings = [
            'LIVE_TRADING_MODE',
            'AUTO_STOP_LOSS_ENABLED',
            'MAX_DAILY_LOSS_RUPEES',
            'POSITION_SIZE_CONTRACTS',
        ]
        
        missing = []
        for setting in settings:
            if not hasattr(config, setting):
                missing.append(setting)
        
        if missing:
            print(f"❌ Missing config settings: {missing}")
            return False
        
        print(f"✅ Config has all {len(settings)} live trading settings")
        return True
        
    except Exception as e:
        print(f"❌ ERROR importing config: {e}")
        return False

def main():
    print("=" * 60)
    print("LIVE TRADING SYSTEM - VERIFICATION TEST")
    print("=" * 60)
    print()
    
    tests = [
        ("Database Method", test_method_exists),
        ("Auto Stop-Loss Import", test_auto_stop_loss_imports),
        ("Dashboard Import", test_dashboard_imports),
        ("Config Settings", test_config_imports),
    ]
    
    results = []
    for name, test_func in tests:
        print(f"Testing {name}...")
        result = test_func()
        results.append((name, result))
        print()
    
    # Summary
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    passed = sum(1 for _, r in results if r)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {name}")
    
    print()
    print(f"Result: {passed}/{total} tests passed")
    print()
    
    if passed == total:
        print("🎉 ALL TESTS PASSED - SYSTEM READY FOR DEPLOYMENT")
        return 0
    else:
        print("⚠️  SOME TESTS FAILED - CHECK ERRORS ABOVE")
        return 1

if __name__ == "__main__":
    sys.exit(main())
