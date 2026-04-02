"""
main.py — NiftyTrader Intelligence System v2.0

Usage:
    python main.py                        # Mock data (no broker needed)
    BROKER=fyers python main.py           # Fyers (complete OAuth in Credentials tab)
    BROKER=dhan   python main.py          # Dhan
"""

import sys
import os
import logging
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.makedirs("logs",   exist_ok=True)
os.makedirs("auth",   exist_ok=True)
os.makedirs("models", exist_ok=True)

log_file = f"logs/niftytrader_{datetime.now().strftime('%Y%m%d')}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)-28s  %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler(
            open(sys.stdout.fileno(), mode="w", encoding="utf-8", buffering=1, closefd=False)
        ),
    ]
)
logger = logging.getLogger("main")


def _on_exit():
    """Flush WAL and close resources on app exit."""
    try:
        from database.manager import get_db
        get_db().close()
        logger.info("Graceful shutdown: DB WAL flushed")
    except Exception:
        pass

import atexit
atexit.register(_on_exit)


def main():
    import config as _cfg
    logger.info("=" * 60)
    logger.info("NiftyTrader Intelligence v2.0 — Starting")
    logger.info(f"Broker: {_cfg.BROKER}")
    logger.info("=" * 60)

    # Validate config settings
    try:
        from config_validator import validate_config
        validate_config()
    except Exception as _cv_err:
        logger.warning(f"Config validation error: {_cv_err}")

    try:
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import Qt
    except ImportError:
        logger.error("PySide6 not installed. Run: pip install PySide6")
        sys.exit(1)

    app = QApplication(sys.argv)
    app.setApplicationName("NiftyTrader")
    app.setApplicationVersion("2.0.0")
    app.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    from data.data_manager     import DataManager
    from engines.signal_aggregator import SignalAggregator
    from alerts.alert_manager  import AlertManager

    # Start event calendar updater (background — non-blocking).
    # Fetches RBI MPC + FOMC dates from official websites if cache is stale (>7 days).
    try:
        from data.event_updater import start_background_updater
        start_background_updater()
    except Exception as _ecu_err:
        logger.warning(f"Event calendar updater could not start: {_ecu_err}")

    # Schedule daily DB backup at 15:35 IST (post-market close)
    try:
        from database.backup_manager import schedule_daily_backup
        schedule_daily_backup()
    except Exception as _bu_err:
        logger.warning(f"Backup scheduler could not start: {_bu_err}")

    # Schedule daily options data export at 15:36 IST (right after backup)
    try:
        from ml.options_feature_engine import schedule_daily_options_export
        schedule_daily_options_export()
    except Exception as _oe_err:
        logger.warning(f"Options export scheduler could not start: {_oe_err}")

    data_manager      = DataManager()
    signal_aggregator = SignalAggregator()
    alert_manager     = AlertManager()

    from ui.main_window import MainWindow
    window = MainWindow(data_manager, signal_aggregator, alert_manager)
    window.show()

    # Auto-start mock only if no saved broker preference exists.
    # If credentials_tab loaded a saved broker, config.BROKER is already set.
    import config
    if config.BROKER == "mock":
        ok = data_manager.start()
        if ok:
            logger.info("Mock broker started automatically")

    logger.info("Application ready.")
    exit_code = app.exec()

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
