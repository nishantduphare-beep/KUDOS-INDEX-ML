"""
database/backup_manager.py
Daily SQLite backup utility — copies nifty_trader.db to backups/ folder at 15:35 IST.
Triggered from main.py via threading.Timer.
"""
import shutil
import logging
import threading
from pathlib import Path
from datetime import datetime, timedelta

import config

logger = logging.getLogger(__name__)


def _backup_now():
    """Copy database file to backups/ folder with timestamp."""
    try:
        db_path = Path(config.DB_PATH)
        if not db_path.exists():
            logger.warning("Backup skipped: DB file not found")
            return
        backup_dir = db_path.parent / "backups"
        backup_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        dest = backup_dir / f"nifty_trader_{timestamp}.db"
        shutil.copy2(db_path, dest)
        logger.info(f"DB backed up → {dest}")
        # Keep only last 7 backups
        backups = sorted(backup_dir.glob("nifty_trader_*.db"), key=lambda p: p.stat().st_mtime)
        for old in backups[:-7]:
            old.unlink()
            logger.debug(f"Old backup removed: {old}")
    except Exception as e:
        logger.error(f"Backup failed: {e}")


def _seconds_until(hour: int, minute: int) -> float:
    """Seconds until next occurrence of HH:MM IST (uses local time)."""
    now = datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def schedule_daily_backup(hour: int = 15, minute: int = 35):
    """
    Schedule a daily DB backup at HH:MM local time (default 15:35 IST = post-market).
    Non-blocking — uses threading.Timer; reschedules itself each day.
    """
    def _run_and_reschedule():
        _backup_now()
        schedule_daily_backup(hour, minute)  # reschedule for next day

    delay = _seconds_until(hour, minute)
    t = threading.Timer(delay, _run_and_reschedule)
    t.daemon = True
    t.name = "DailyBackupTimer"
    t.start()
    logger.info(
        f"Daily backup scheduled at {hour:02d}:{minute:02d} "
        f"(in {delay/3600:.1f}h)"
    )
