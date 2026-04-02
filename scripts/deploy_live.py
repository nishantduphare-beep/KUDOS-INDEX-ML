#!/usr/bin/env python3
"""
DEPLOY_LIVE.py — Comprehensive live trading deployment script.

Performs:
  1. Backup database
  2. Run pre-live checklist
  3. Enable live mode
  4. Start AutoStopLoss
  5. Verify all systems
  6. Print deployment summary
"""

import sys
import logging
import argparse
from datetime import datetime
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def print_banner(text: str):
    """Print formatted banner"""
    print("\n" + "="*70)
    print(f"🚀 {text}")
    print("="*70 + "\n")


def backup_database():
    """Create backup of current database"""
    print_banner("Step 1: Backup Database")
    
    db_path = Path("niftytrader.db")
    if not db_path.exists():
        logger.warning("Database file not found - skipping backup")
        return True
    
    backup_path = Path(f"niftytrader.db.backup-{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    
    try:
        import shutil
        shutil.copy2(db_path, backup_path)
        logger.info(f"✓ Backup created: {backup_path}")
        return True
    except Exception as e:
        logger.error(f"✗ Backup failed: {e}")
        return False


def run_pre_live_checklist():
    """Run pre-live checks"""
    print_banner("Step 2: Pre-Live Checklist")
    
    try:
        from trading.pre_live_checklist import run_pre_live_checklist
        from database.manager import get_db
        from ml.model_manager import get_model_manager
        
        # Get context
        context = {
            'db': get_db(),
            'broker': None,  # Will be loaded by checklist
            'model_manager': get_model_manager(),
        }
        
        success = run_pre_live_checklist(context)
        return success
    
    except Exception as e:
        logger.error(f"✗ Checklist failed: {e}", exc_info=True)
        return False


def enable_live_mode():
    """Enable live trading in config"""
    print_banner("Step 3: Enable Live Mode")
    
    try:
        import config
        
        # Verify settings
        if not config.AUTO_STOP_LOSS_ENABLED:
            logger.error("✗ AUTO_STOP_LOSS_ENABLED is False - cannot go live")
            return False
        
        # Note: LIVE_TRADING_MODE should already be set in config
        logger.info(f"LIVE_TRADING_MODE: {config.LIVE_TRADING_MODE}")
        logger.info(f"AUTO_STOP_LOSS_ENABLED: {config.AUTO_STOP_LOSS_ENABLED}")
        logger.info(f"POSITION_SIZE_CONTRACTS: {config.POSITION_SIZE_CONTRACTS}")
        logger.info(f"MAX_DAILY_LOSS_RUPEES: {config.MAX_DAILY_LOSS_RUPEES}")
        
        if config.LIVE_TRADING_MODE:
            logger.info("✓ Live mode ENABLED in config")
            return True
        else:
            logger.warning("⚠ Live mode DISABLED in config - user must set LIVE_TRADING_MODE=True")
            return True  # Not critical, user can enable manually
    
    except Exception as e:
        logger.error(f"✗ Enable live mode failed: {e}")
        return False


def start_monitoring():
    """Start AutoStopLoss monitoring"""
    print_banner("Step 4: Start Monitoring Systems")
    
    try:
        from database.manager import get_db
        from trading.auto_stop_loss import init_auto_stop_loss
        from trading.daily_pnl_tracker import init_daily_pnl_tracker
        from trading.live_gate import get_live_gate
        
        db = get_db()
        
        # Initialize auto stop-loss
        auto_sl = init_auto_stop_loss(db, None)  # Broker will be added later
        auto_sl.start()
        logger.info("✓ AutoStopLoss started")
        
        # Initialize PnL tracker
        pnl_tracker = init_daily_pnl_tracker(db)
        logger.info("✓ Daily P&L Tracker started")
        
        # Get live gate
        gate = get_live_gate()
        logger.info("✓ Live Gate ready")
        
        return True
    
    except Exception as e:
        logger.error(f"✗ System startup failed: {e}", exc_info=True)
        return False


def verify_systems():
    """Final system verification"""
    print_banner("Step 5: System Verification")
    
    checks = []
    
    try:
        import config
        checks.append(("Live Mode", config.LIVE_TRADING_MODE))
        checks.append(("Auto Stop-Loss", config.AUTO_STOP_LOSS_ENABLED))
        checks.append(("Position Size", config.POSITION_SIZE_CONTRACTS > 0))
        checks.append(("Daily Loss Limit", config.MAX_DAILY_LOSS_RUPEES > 0))
    except Exception as e:
        logger.error(f"Config check failed: {e}")
        return False
    
    for check_name, passed in checks:
        status = "✓" if passed else "✗"
        logger.info(f"{status} {check_name}")
    
    all_passed = all(p for _, p in checks)
    return all_passed


def print_deployment_summary():
    """Print deployment summary and next steps"""
    print_banner("Deployment Summary")
    
    print("""
✅ DEPLOYMENT COMPLETE

🔧 CONFIGURATION:
   • LIVE_TRADING_MODE: Check config.py (set to True to enable)
   • Maximum Daily Loss: ₹5,000
   • Maximum Concurrent Trades: 2
   • Position Size: 1 lot
   • Auto Stop-Loss: ENABLED
   • Required ML Confidence: 55%

📊 MONITORING:
   • Dashboard: Open nifty_trader/ui/main_window.py
   • Logs: Check logs/ folder for today's log
   • Real-time: View dashboard every 30 minutes

🚨 SAFETY:
   • Emergency Exit: Click red button on dashboard
   • Daily Limit: Auto-stops at ₹5,000 loss
   • Stop-Loss: Auto-executes at SL price
   • Circuit Breaker: Stops on ATR spike >300%

📋 NEXT STEPS:

   1. READ: LIVE_TRADING_RUNBOOK.md (daily procedures)
   2. VERIFY: All pre-live checks PASS
   3. CONFIRM: You have ₹50,000+ in Fyers
   4. START: Open app and monitor signals
   5. SIGNAL: First signal will show confirmation dialog
   6. CONFIRM: Click CONFIRM to place live order
   7. MONITOR: Watch dashboard for P&L updates

⚡ FIRST LIVE TRADE:
   • Will show confirmation dialog
   • Has 30-second confirmation window
   • Can close all positions with 🚨 button
   • Stop-loss is automatic (no action needed)

Remember:
   ✋ DO NOT disable AUTO_STOP_LOSS_ENABLED
   ✋ DO NOT increase MAX_DAILY_LOSS_RUPEES
   ✋ DO NOT leave unattended for > 1 hour
   ✋ DO NOT skip daily pre-live checklist

🎯 GOOD LUCK! Monitor carefully for first 2 hours.
    """)


def main():
    """Main deployment flow"""
    parser = argparse.ArgumentParser(description="Deploy NiftyTrader for live trading")
    parser.add_argument("--skip-backup", action="store_true", help="Skip database backup")
    parser.add_argument("--skip-checklist", action="store_true", help="Skip pre-live checklist")
    args = parser.parse_args()
    
    print_banner("NIFTYTRADER v3 - LIVE TRADING DEPLOYMENT")
    
    # Step 1: Backup
    if not args.skip_backup:
        if not backup_database():
            logger.error("Backup failed - aborting deployment")
            return 1
    
    # Step 2: Checklist
    if not args.skip_checklist:
        if not run_pre_live_checklist():
            logger.error("Pre-live checklist failed - aborting deployment")
            return 1
    
    # Step 3: Enable live mode
    if not enable_live_mode():
        logger.error("Failed to enable live mode")
        return 1
    
    # Step 4: Start monitoring
    if not start_monitoring():
        logger.error("Failed to start monitoring systems")
        return 1
    
    # Step 5: Verify
    if not verify_systems():
        logger.error("System verification failed")
        return 1
    
    # Summary
    print_deployment_summary()
    
    logger.info("✅ DEPLOYMENT SUCCESSFUL - Ready for live trading")
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        logger.info("Deployment cancelled by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Deployment error: {e}", exc_info=True)
        sys.exit(1)
