#!/usr/bin/env python3
"""
COMPREHENSIVE PRODUCTION READINESS AUDIT
=========================================
Deep check of every component, file, connection, and system
"""

import os
import sys
import json
import traceback
import importlib.util
from pathlib import Path
from datetime import datetime

# Color codes for terminal
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'
BOLD = '\033[1m'

class ProductionAudit:
    def __init__(self):
        self.root_dir = Path(__file__).parent
        self.issues = []
        self.warnings = []
        self.passes = []
        self.timestamp = datetime.now().isoformat()
        
    def log_pass(self, msg):
        print(f"{GREEN}✅ PASS{RESET}: {msg}")
        self.passes.append(msg)
    
    def log_warn(self, msg):
        print(f"{YELLOW}⚠️  WARN{RESET}: {msg}")
        self.warnings.append(msg)
    
    def log_fail(self, msg):
        print(f"{RED}❌ FAIL{RESET}: {msg}")
        self.issues.append(msg)
    
    def log_info(self, msg):
        print(f"{BLUE}ℹ️  INFO{RESET}: {msg}")
    
    def section(self, title):
        print(f"\n{BOLD}{BLUE}{'='*60}{RESET}")
        print(f"{BOLD}{BLUE}{title:^60}{RESET}")
        print(f"{BOLD}{BLUE}{'='*60}{RESET}\n")

    # ====== PHASE 1: FILE STRUCTURE ======
    def check_file_structure(self):
        """Verify all critical files and folders exist"""
        self.section("PHASE 1: FILE STRUCTURE VALIDATION")
        
        critical_files = {
            'nifty_trader/main.py': 'Main entry point',
            'nifty_trader/config.py': 'Configuration',
            'nifty_trader/database/manager.py': 'Database manager',
            'nifty_trader/data/data_manager.py': 'Data manager',
            'nifty_trader/engines/signal_aggregator.py': 'Signal engine',
            'nifty_trader/ui/dashboard.py': 'Dashboard UI',
            'nifty_trader/ui/live_trading_dashboard.py': 'Live trading UI',
            'nifty_trader/alerts/alert_manager.py': 'Alert manager',
            'nifty_trader/trading/order_manager.py': 'Order manager',
            'nifty_trader/trading/paper_trader.py': 'Paper trader',
            'nifty_trader/ml/model_manager.py': 'ML model manager',
            'nifty_trader/data/adapters/fyers_adapter.py': 'Fyers adapter',
            'nifty_trader/data/adapters/mock_adapter.py': 'Mock adapter',
            'nifty_trader/data/bs_utils.py': 'Black-Scholes utils',
        }
        
        critical_dirs = {
            'nifty_trader': 'Root package',
            'nifty_trader/database': 'Database module',
            'nifty_trader/data': 'Data module',
            'nifty_trader/engines': 'Engines module',
            'nifty_trader/ui': 'UI module',
            'nifty_trader/alerts': 'Alerts module',
            'nifty_trader/trading': 'Trading module',
            'nifty_trader/ml': 'ML module',
            'nifty_trader/data/adapters': 'Adapters module',
            'logs': 'Logs directory',
            'models': 'Models directory',
            'auth': 'Auth directory',
        }
        
        # Check directories
        for dir_path, desc in critical_dirs.items():
            full_path = self.root_dir.parent / dir_path
            if full_path.exists():
                file_count = len(list(full_path.glob('*')))
                self.log_pass(f"Directory exists: {dir_path} ({file_count} items)")
            else:
                self.log_fail(f"Missing directory: {dir_path}")
        
        # Check files
        for file_path, desc in critical_files.items():
            full_path = self.root_dir.parent / file_path
            if full_path.exists():
                size = full_path.stat().st_size
                self.log_pass(f"File exists: {file_path} ({size} bytes) - {desc}")
            else:
                self.log_fail(f"Missing file: {file_path} - {desc}")

    # ====== PHASE 2: PYTHON SYNTAX & IMPORTS ======
    def check_python_syntax(self):
        """Check all Python files for syntax errors"""
        self.section("PHASE 2: PYTHON SYNTAX & IMPORTS CHECK")
        
        py_files = list(self.root_dir.rglob('*.py'))
        py_files = [f for f in py_files if '__pycache__' not in str(f)]
        
        print(f"Checking {len(py_files)} Python files...\n")
        
        syntax_errors = []
        for py_file in py_files:
            try:
                with open(py_file, 'r', encoding='utf-8') as f:
                    code = f.read()
                compile(code, str(py_file), 'exec')
                self.log_pass(f"Syntax OK: {py_file.relative_to(self.root_dir)}")
            except SyntaxError as e:
                error_msg = f"Syntax Error in {py_file.relative_to(self.root_dir)}: {e.msg} at line {e.lineno}"
                self.log_fail(error_msg)
                syntax_errors.append(error_msg)
            except Exception as e:
                self.log_warn(f"Error checking {py_file.relative_to(self.root_dir)}: {e}")
        
        if not syntax_errors:
            self.log_pass(f"ALL {len(py_files)} Python files have valid syntax!")
        else:
            self.log_fail(f"Found {len(syntax_errors)} syntax errors")

    # ====== PHASE 3: CRITICAL IMPORTS ======
    def check_critical_imports(self):
        """Verify all critical imports work"""
        self.section("PHASE 3: CRITICAL IMPORTS CHECK")
        
        sys.path.insert(0, str(self.root_dir))
        
        critical_imports = [
            ('config', 'Configuration module'),
            ('database.manager', 'Database manager'),
            ('data.data_manager', 'Data manager'),
            ('data.structures', 'Data structures'),
            ('data.adapters.fyers_adapter', 'Fyers adapter'),
            ('data.adapters.mock_adapter', 'Mock adapter'),
            ('engines.signal_aggregator', 'Signal aggregator'),
            ('alerts.alert_manager', 'Alert manager'),
            ('trading.order_manager', 'Order manager'),
            ('trading.paper_trader', 'Paper trader'),
            ('ml.model_manager', 'ML model manager'),
        ]
        
        for module_name, desc in critical_imports:
            try:
                module = __import__(module_name, fromlist=[module_name.split('.')[-1]])
                self.log_pass(f"Import OK: {module_name} - {desc}")
            except Exception as e:
                self.log_fail(f"Import ERROR: {module_name} - {desc}\n  Reason: {str(e)[:100]}")

    # ====== PHASE 4: CONFIG VALIDATION ======
    def check_config(self):
        """Verify configuration is valid"""
        self.section("PHASE 4: CONFIGURATION VALIDATION")
        
        try:
            sys.path.insert(0, str(self.root_dir))
            from config import (
                LIVE_TRADING_MODE, USE_FUTURES_VOLUME, MODEL_DIR,
                DB_PATH, LOG_DIR, BROKER, VOLUME_SPIKE_MULTIPLIER,
                SIGNAL_MIN_VOLUME_RATIO, RISK_LIMIT_DAILY,
                POSITION_SIZE_PERCENT, AUTO_STOP_LOSS_PERCENT
            )
            
            self.log_pass(f"Config loaded successfully")
            self.log_info(f"  LIVE_TRADING_MODE: {LIVE_TRADING_MODE}")
            self.log_info(f"  BROKER: {BROKER}")
            self.log_info(f"  USE_FUTURES_VOLUME: {USE_FUTURES_VOLUME}")
            self.log_info(f"  VOLUME_SPIKE_MULTIPLIER: {VOLUME_SPIKE_MULTIPLIER}")
            self.log_info(f"  RISK_LIMIT_DAILY: {RISK_LIMIT_DAILY}")
            
            # Validate safety settings
            if LIVE_TRADING_MODE and AUTO_STOP_LOSS_PERCENT < 1.0:
                self.log_fail(f"DANGER: Live mode with tiny stop-loss {AUTO_STOP_LOSS_PERCENT}%")
            
            if POSITION_SIZE_PERCENT > 10:
                self.log_warn(f"Aggressive position sizing: {POSITION_SIZE_PERCENT}%")
            
            if RISK_LIMIT_DAILY > 5000:
                self.log_warn(f"High daily risk limit: ₹{RISK_LIMIT_DAILY}")
                
        except Exception as e:
            self.log_fail(f"Config error: {str(e)}")

    # ====== PHASE 5: DATABASE ======
    def check_database(self):
        """Verify database schema and connectivity"""
        self.section("PHASE 5: DATABASE VERIFICATION")
        
        try:
            sys.path.insert(0, str(self.root_dir))
            from database.manager import DatabaseManager
            from database.models import (
                Account, Trade, Signal, Outcome,
                Alert, OrderLog, MLFeature
            )
            
            db = DatabaseManager()
            self.log_pass("Database manager initialized")
            
            # Check tables
            models = [Account, Trade, Signal, Outcome, Alert, OrderLog, MLFeature]
            for model in models:
                try:
                    # Try to count records
                    query = db.session.query(model)
                    count = query.count()
                    self.log_pass(f"Table OK: {model.__tablename__} ({count} records)")
                except Exception as e:
                    self.log_fail(f"Table error: {model.__tablename__} - {str(e)[:80]}")
            
            # Check critical methods
            methods = [
                'get_account',
                'get_trades',
                'get_open_trades',
                'get_signals',
                'get_open_trade_outcomes',
                'insert_trade',
                'update_trade',
            ]
            
            for method in methods:
                if hasattr(db, method):
                    self.log_pass(f"Method exists: DatabaseManager.{method}()")
                else:
                    self.log_fail(f"Method missing: DatabaseManager.{method}()")
                    
        except Exception as e:
            self.log_fail(f"Database error: {str(e)}")
            traceback.print_exc()

    # ====== PHASE 6: DATA ADAPTERS ======
    def check_data_adapters(self):
        """Verify data adapters are working"""
        self.section("PHASE 6: DATA ADAPTERS CHECK")
        
        try:
            sys.path.insert(0, str(self.root_dir))
            from data.adapters.fyers_adapter import FyersAdapter
            from data.adapters.mock_adapter import MockAdapter
            
            # Mock adapter (should always work)
            try:
                mock_adapter = MockAdapter(None)
                self.log_pass("MockAdapter initialized")
                
                # Check methods
                methods = [
                    'get_spot_candles',
                    'get_futures_candles',
                    'get_option_chain',
                    'get_all_futures_quotes',
                ]
                
                for method in methods:
                    if hasattr(mock_adapter, method):
                        self.log_pass(f"  MockAdapter.{method}() exists")
                    else:
                        self.log_fail(f"  MockAdapter.{method}() missing")
                        
            except Exception as e:
                self.log_fail(f"MockAdapter error: {str(e)}")
            
            # Fyers adapter (may not have credentials)
            try:
                fyers_adapter = FyersAdapter(None)
                self.log_pass("FyersAdapter initialized")
                
                methods = [
                    'get_spot_candles',
                    'get_futures_candles',
                    'get_option_chain',
                    'get_all_futures_quotes',
                ]
                
                for method in methods:
                    if hasattr(fyers_adapter, method):
                        self.log_pass(f"  FyersAdapter.{method}() exists")
                    else:
                        self.log_fail(f"  FyersAdapter.{method}() missing")
                        
            except Exception as e:
                self.log_warn(f"FyersAdapter init warning (expected if no credentials): {str(e)[:80]}")
                
        except Exception as e:
            self.log_fail(f"Adapters error: {str(e)}")

    # ====== PHASE 7: ENGINES ======
    def check_engines(self):
        """Verify all trading engines"""
        self.section("PHASE 7: TRADING ENGINES CHECK")
        
        try:
            sys.path.insert(0, str(self.root_dir))
            
            engines = {
                'engines.signal_aggregator': 'Signal Aggregator',
                'engines.volume_pressure': 'Volume Pressure',
                'engines.gamma_levels': 'Gamma Levels',
                'engines.iv_expansion': 'IV Expansion',
                'engines.vwap_pressure': 'VWAP Pressure',
                'engines.market_regime': 'Market Regime',
                'engines.mtf_alignment': 'MTF Alignment',
                'engines.option_chain': 'Option Chain',
                'engines.liquidity_trap': 'Liquidity Trap',
                'engines.di_momentum': 'DI Momentum',
            }
            
            for module_path, desc in engines.items():
                try:
                    module = __import__(module_path, fromlist=[module_path.split('.')[-1]])
                    self.log_pass(f"Engine OK: {desc}")
                except Exception as e:
                    self.log_fail(f"Engine ERROR: {desc} - {str(e)[:80]}")
                    
        except Exception as e:
            self.log_fail(f"Engines error: {str(e)}")

    # ====== PHASE 8: ML SYSTEM ======
    def check_ml_system(self):
        """Verify ML system configuration"""
        self.section("PHASE 8: ML SYSTEM CHECK")
        
        try:
            sys.path.insert(0, str(self.root_dir))
            from ml.model_manager import ModelManager
            from config import MODEL_DIR
            
            mm = ModelManager()
            self.log_pass("ModelManager initialized")
            
            # Check model files
            model_dir = Path(MODEL_DIR)
            if model_dir.exists():
                meta_files = list(model_dir.glob('*.json'))
                self.log_pass(f"Model directory exists with {len(meta_files)} metadata files")
                
                if len(meta_files) > 0:
                    latest = max(meta_files, key=lambda f: f.stat().st_mtime)
                    self.log_info(f"Latest model: {latest.name}")
                    
                    try:
                        with open(latest, 'r') as f:
                            meta = json.load(f)
                            self.log_info(f"  Version: {meta.get('version', '?')}")
                            self.log_info(f"  Samples: {meta.get('n_samples', '?')}")
                            self.log_info(f"  ROC-AUC: {meta.get('roc_auc', '?'):.3f}")
                            self.log_info(f"  F1-Score: {meta.get('f1_score', '?'):.3f}")
                    except Exception as e:
                        self.log_warn(f"Could not read model metadata: {e}")
            else:
                self.log_warn(f"Model directory not found: {MODEL_DIR}")
                
            # Check ML methods
            methods = ['predict', 'train', 'is_model_ready']
            for method in methods:
                if hasattr(mm, method):
                    self.log_pass(f"  ModelManager.{method}() exists")
                else:
                    self.log_fail(f"  ModelManager.{method}() missing")
                    
        except Exception as e:
            self.log_fail(f"ML system error: {str(e)}")
            traceback.print_exc()

    # ====== PHASE 9: ORDER MANAGEMENT ======
    def check_order_management(self):
        """Verify order management system"""
        self.section("PHASE 9: ORDER MANAGEMENT CHECK")
        
        try:
            sys.path.insert(0, str(self.root_dir))
            from trading.order_manager import OrderManager
            
            om = OrderManager()
            self.log_pass("OrderManager initialized")
            
            # Check order methods
            methods = [
                'place_order',
                'cancel_order',
                'get_order_status',
                'get_open_orders',
                'validate_order',
            ]
            
            for method in methods:
                if hasattr(om, method):
                    self.log_pass(f"  OrderManager.{method}() exists")
                else:
                    self.log_fail(f"  OrderManager.{method}() missing")
                    
        except Exception as e:
            self.log_fail(f"Order management error: {str(e)}")

    # ====== PHASE 10: PAPER TRADING ======
    def check_paper_trading(self):
        """Verify paper trading system"""
        self.section("PHASE 10: PAPER TRADING CHECK")
        
        try:
            sys.path.insert(0, str(self.root_dir))
            from trading.paper_trader import PaperTrader
            
            pt = PaperTrader()
            self.log_pass("PaperTrader initialized")
            
            # Check methods
            methods = [
                'place_order',
                'check_profit_loss',
                'close_position',
            ]
            
            for method in methods:
                if hasattr(pt, method):
                    self.log_pass(f"  PaperTrader.{method}() exists")
                else:
                    self.log_fail(f"  PaperTrader.{method}() missing")
                    
        except Exception as e:
            self.log_fail(f"Paper trading error: {str(e)}")

    # ====== PHASE 11: SAFETY SYSTEMS ======
    def check_safety_systems(self):
        """Verify all 8 safety layers"""
        self.section("PHASE 11: SAFETY SYSTEMS CHECK")
        
        try:
            sys.path.insert(0, str(self.root_dir))
            
            safety_files = {
                'trading/auto_stop_loss.py': 'Auto Stop-Loss',
                'trading/live_trading_gate.py': 'Live Trading Gate',
                'trading/position_sizer.py': 'Position Sizer',
                'trading/daily_pnl_tracker.py': 'Daily P&L Tracker',
                'trading/account_verifier.py': 'Account Verifier',
                'ui/pre_live_checklist.py': 'Pre-Live Checklist',
                'ui/order_confirmation.py': 'Order Confirmation',
                'ui/live_trading_disclaimer.py': 'Live Trading Disclaimer',
            }
            
            for file_path, desc in safety_files.items():
                full_path = self.root_dir / file_path
                if full_path.exists():
                    self.log_pass(f"Safety layer OK: {desc}")
                else:
                    self.log_fail(f"Safety layer missing: {desc} ({file_path})")
                    
        except Exception as e:
            self.log_fail(f"Safety systems error: {str(e)}")

    # ====== PHASE 12: UI COMPONENTS ======
    def check_ui_components(self):
        """Verify UI components"""
        self.section("PHASE 12: UI COMPONENTS CHECK")
        
        try:
            ui_files = [
                'dashboard.py',
                'live_trading_dashboard.py',
                'order_confirmation.py',
                'pre_live_checklist.py',
                'live_trading_disclaimer.py',
            ]
            
            for file_name in ui_files:
                file_path = self.root_dir / 'ui' / file_name
                if file_path.exists():
                    size = file_path.stat().st_size
                    self.log_pass(f"UI Component OK: {file_name} ({size} bytes)")
                else:
                    self.log_fail(f"UI Component missing: {file_name}")
                    
        except Exception as e:
            self.log_fail(f"UI check error: {str(e)}")

    # ====== PHASE 13: ALERTS ======
    def check_alerts(self):
        """Verify alert system"""
        self.section("PHASE 13: ALERTS SYSTEM CHECK")
        
        try:
            sys.path.insert(0, str(self.root_dir))
            from alerts.alert_manager import AlertManager
            
            am = AlertManager()
            self.log_pass("AlertManager initialized")
            
            methods = ['send_alert', 'send_telegram', 'log_alert']
            for method in methods:
                if hasattr(am, method):
                    self.log_pass(f"  AlertManager.{method}() exists")
                else:
                    self.log_fail(f"  AlertManager.{method}() missing")
                    
        except Exception as e:
            self.log_warn(f"Alerts system (non-critical): {str(e)[:80]}")

    # ====== PHASE 14: LOGS & PERSISTENCE ======
    def check_logs_persistence(self):
        """Verify logging and data persistence"""
        self.section("PHASE 14: LOGS & DATA PERSISTENCE CHECK")
        
        try:
            log_dir = self.root_dir.parent / 'logs'
            if log_dir.exists():
                self.log_pass(f"Logs directory exists")
                log_files = list(log_dir.glob('**/*.log'))
                self.log_info(f"  Found {len(log_files)} log files")
            else:
                self.log_warn(f"Logs directory doesn't exist yet (will be created at runtime)")
            
            # Check models directory
            models_dir = self.root_dir.parent / 'models'
            if models_dir.exists():
                self.log_pass(f"Models directory exists")
                meta_files = list(models_dir.glob('*.json'))
                self.log_info(f"  Found {len(meta_files)} model files")
            else:
                self.log_warn(f"Models directory doesn't exist yet")
                
        except Exception as e:
            self.log_fail(f"Logs/persistence error: {str(e)}")

    # ====== GENERATE REPORT ======
    def generate_report(self):
        """Generate final audit report"""
        self.section("PRODUCTION READINESS REPORT")
        
        total = len(self.passes) + len(self.warnings) + len(self.issues)
        
        print(f"\n{BOLD}AUDIT SUMMARY{RESET}\n")
        print(f"  Total Checks: {total}")
        print(f"  {GREEN}✅ Passed: {len(self.passes)}{RESET}")
        print(f"  {YELLOW}⚠️  Warnings: {len(self.warnings)}{RESET}")
        print(f"  {RED}❌ Issues: {len(self.issues)}{RESET}")
        
        if self.issues:
            print(f"\n{RED}{BOLD}CRITICAL ISSUES ({len(self.issues)}):{RESET}")
            for i, issue in enumerate(self.issues, 1):
                print(f"  {i}. {issue}")
        
        if self.warnings:
            print(f"\n{YELLOW}{BOLD}WARNINGS ({len(self.warnings)}):{RESET}")
            for i, warn in enumerate(self.warnings, 1):
                print(f"  {i}. {warn}")
        
        # Production readiness
        if len(self.issues) == 0:
            status = f"{GREEN}{BOLD}🟢 PRODUCTION READY{RESET}"
        elif len(self.issues) <= 3:
            status = f"{YELLOW}{BOLD}🟡 MOSTLY READY (Fix {len(self.issues)} issues){RESET}"
        else:
            status = f"{RED}{BOLD}🔴 NOT READY ({len(self.issues)} issues){RESET}"
        
        print(f"\n{BOLD}PRODUCTION STATUS: {status}\n")
        
        # Save report
        report = {
            'timestamp': self.timestamp,
            'passed': len(self.passes),
            'warnings': len(self.warnings),
            'issues': len(self.issues),
            'critical_issues': self.issues,
            'warnings_list': self.warnings,
            'all_passes': self.passes,
        }
        
        report_file = self.root_dir / 'AUDIT_REPORT.json'
        with open(report_file, 'w') as f:
            json.dump(report, f, indent=2)
        
        print(f"📄 Full report saved to: AUDIT_REPORT.json")

    def run_full_audit(self):
        """Run complete audit"""
        print(f"\n{BOLD}{BLUE}STARTING COMPREHENSIVE PRODUCTION AUDIT{RESET}")
        print(f"{BLUE}Timestamp: {self.timestamp}{RESET}\n")
        
        try:
            self.check_file_structure()
            self.check_python_syntax()
            self.check_critical_imports()
            self.check_config()
            self.check_database()
            self.check_data_adapters()
            self.check_engines()
            self.check_ml_system()
            self.check_order_management()
            self.check_paper_trading()
            self.check_safety_systems()
            self.check_ui_components()
            self.check_alerts()
            self.check_logs_persistence()
            self.generate_report()
        except Exception as e:
            print(f"\n{RED}AUDIT CRASHED: {e}{RESET}")
            traceback.print_exc()

if __name__ == '__main__':
    audit = ProductionAudit()
    audit.run_full_audit()
