"""
Pre-Live Checklist Generator — Final safety verification before going live.

Runs these checks:
  • Database health
  • Broker connection
  • Model readiness
  • Live gate configuration
  • Stop-loss automation
  • Backup database exists
  • Logs being written
"""

import logging
import sys
from pathlib import Path
from datetime import datetime

try:
    import config
except ImportError:
    import nifty_trader.config as config

logger = logging.getLogger(__name__)


class PreLiveChecker:
    """Run pre-flight checks before going live"""
    
    def __init__(self):
        self.checks: list = []
        self.passed = 0
        self.failed = 0
    
    def run_all_checks(self, context: dict) -> bool:
        """
        Run all pre-live checks.
        
        Args:
            context: Dict with:
                - db: Database manager
                - broker: Broker adapter
                - model_manager: ML model manager
        
        Returns:
            True if all checks pass
        """
        self.checks = []
        self.passed = 0
        self.failed = 0
        
        print("\n" + "="*70)
        print("🚀 PRE-LIVE TRADING CHECKLIST")
        print("="*70)
        
        # Run all checks
        self._check_database(context.get('db'))
        self._check_broker(context.get('broker'))
        self._check_model(context.get('model_manager'))
        self._check_live_gate()
        self._check_stop_loss()
        self._check_backups()
        self._check_logs()
        self._check_paper_trading()
        
        # Print summary
        self._print_summary()
        
        all_passed = self.failed == 0
        
        if all_passed:
            print("\n✅ ALL CHECKS PASSED - Ready for live trading!\n")
        else:
            print(f"\n❌ {self.failed} CHECKS FAILED - Do NOT go live\n")
        
        return all_passed
    
    def _check_database(self, db):
        """Check database health"""
        try:
            if db is None:
                self._add_check("✗", "Database FAILED", "Database manager not initialized")
                return
            
            # Check tables
            table_count = len(db.get_table_list()) if hasattr(db, 'get_table_list') else 0
            
            if table_count == 0:
                self._add_check("✗", "Database FAILED", "No tables found - DB schema missing")
                return
            
            self._add_check("✓", "Database healthy", f"{table_count} tables present")
        
        except Exception as e:
            self._add_check("✗", "Database error", str(e))
    
    def _check_broker(self, broker):
        """Check broker connection"""
        try:
            if broker is None:
                self._add_check("✗", "Broker FAILED", "Broker not initialized")
                return
            
            # Try to get spot price
            spot_price = broker.get_spot_price('NIFTY')
            
            if spot_price and spot_price > 10000:
                self._add_check("✓", "Broker connected", f"NIFTY={spot_price:.0f}")
            else:
                self._add_check("✗", "Broker FAILED", f"Invalid spot price: {spot_price}")
        
        except Exception as e:
            self._add_check("✗", "Broker error", str(e))
    
    def _check_model(self, model_manager):
        """Check ML model readiness"""
        try:
            if model_manager is None:
                self._add_check("✗", "Model FAILED", "Model manager not initialized")
                return
            
            # Check model version and F1 score
            version = getattr(model_manager, '_model_version', None)
            
            if version is None:
                self._add_check("✗", "Model FAILED", "No model loaded")
                return
            
            model_ver = getattr(version, 'version', 'unknown')
            metrics = getattr(version, 'metrics', {})
            f1_score = metrics.get('f1', 0)
            
            if f1_score < 0.65:
                self._add_check("⚠", "Model warning", f"v{model_ver} F1={f1_score:.3f} < 0.65 threshold")
            else:
                self._add_check("✓", "Model ready", f"v{model_ver} (F1={f1_score:.3f})")
        
        except Exception as e:
            self._add_check("✗", "Model error", str(e))
    
    def _check_live_gate(self):
        """Check live gate configuration"""
        try:
            from trading.live_gate import get_live_gate
            
            live_mode = config.LIVE_TRADING_MODE
            gate = get_live_gate()
            
            if not live_mode:
                self._add_check("⚠", "Live mode", "Disabled (set LIVE_TRADING_MODE=True to enable)")
            else:
                self._add_check("✓", "Live gate", "Configured and active")
        
        except Exception as e:
            self._add_check("✗", "Live gate error", str(e))
    
    def _check_stop_loss(self):
        """Check stop-loss automation"""
        try:
            
            if not config.AUTO_STOP_LOSS_ENABLED:
                self._add_check("✗", "Auto stop-loss", "DISABLED - must be enabled!")
                return
            
            self._add_check("✓", "Auto stop-loss", "ACTIVE")
        
        except Exception as e:
            self._add_check("✗", "Stop-loss error", str(e))
    
    def _check_backups(self):
        """Check if backup database exists"""
        try:
            backup_path = Path('niftytrader.db.backup')
            
            if backup_path.exists():
                backup_size = backup_path.stat().st_size / 1024 / 1024  # MB
                self._add_check("✓", "Backup database", f"Exists ({backup_size:.1f} MB)")
            else:
                self._add_check("⚠", "Backup missing", "Create backup with: cp niftytrader.db niftytrader.db.backup")
        
        except Exception as e:
            self._add_check("✗", "Backup check error", str(e))
    
    def _check_logs(self):
        """Check if logs are being written today"""
        try:
            logs_path = Path('logs')
            
            if not logs_path.exists():
                self._add_check("⚠", "Logs directory", "Not found - will be created")
                return
            
            today_str = datetime.now().strftime('%Y%m%d')
            today_logs = list(logs_path.glob(f'*{today_str}*.log'))
            
            if today_logs:
                self._add_check("✓", "Logging active", f"Found {len(today_logs)} log(s) today")
            else:
                self._add_check("⚠", "No logs today", "Logs will be created on first run")
        
        except Exception as e:
            self._add_check("✗", "Logs error", str(e))
    
    def _check_paper_trading(self):
        """Check if paper trading was done"""
        self._add_check("⚠", "Paper trading", "Verify 24h+ paper run completed successfully")
    
    def _add_check(self, status: str, name: str, detail: str):
        """Add check result"""
        self.checks.append((status, name, detail))
        
        if status == "✓":
            self.passed += 1
        elif status == "✗":
            self.failed += 1
    
    def _print_summary(self):
        """Print all checks"""
        print()
        
        for status, name, detail in self.checks:
            print(f"{status} {name:.<30} {detail}")
        
        print()
        print(f"Passed: {self.passed} | Failed: {self.failed} | Warnings: {len([c for c in self.checks if c[0] == '⚠'])}")


def run_pre_live_checklist(context: dict) -> bool:
    """
    Run pre-live checklist.
    
    Args:
        context: Dict with db, broker, model_manager
    
    Returns:
        True if all critical checks pass
    """
    checker = PreLiveChecker()
    return checker.run_all_checks(context)


# CLI entry point
if __name__ == '__main__':
    print("Running pre-live checklist...")
    
    try:
        # Import required modules
        from database.manager import get_db
        from data.data_manager import get_data_manager
        from ml.model_manager import get_model_manager
        
        # Get context
        context = {
            'db': get_db(),
            'broker': get_data_manager().broker if hasattr(get_data_manager(), 'broker') else None,
            'model_manager': get_model_manager(),
        }
        
        # Run checks
        success = run_pre_live_checklist(context)
        sys.exit(0 if success else 1)
    
    except Exception as e:
        print(f"Error running checklist: {e}")
        sys.exit(1)
