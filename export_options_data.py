#!/usr/bin/env python3
"""
export_options_data.py
─────────────────────────────────────────────────────────────────────
Daily Options Data Export Script

Can be run:
  1. Manually: python export_options_data.py
  2. With date: python export_options_data.py 2026-04-01
  3. Via cron:  0 16 * * 1-5 cd /path && python export_options_data.py >> logs/export.log 2>&1

Exports:
  ✓ options_eod_YYYY-MM-DD.csv      — Full EOD prices for all strikes (11K+ rows/day)
  ✓ options_snapshots_YYYY-MM-DD.csv — 15-sec snapshots aggregated OI/PCR/IV
  ✓ options_ml_features_YYYY-MM-DD.csv — Pre-computed ML-ready features for training
  ✓ export_summary_YYYY-MM-DD.json   — Metadata + file paths
"""

import os
import sys
import logging

# Ensure we're in the right directory
if not os.path.exists("nifty_trader"):
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    if not os.path.exists("nifty_trader"):
        print("ERROR: Run from workspace root or nifty_trader subdirectory")
        sys.exit(1)

sys.path.insert(0, "nifty_trader")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)
logger = logging.getLogger("options_export")

if __name__ == "__main__":
    from datetime import datetime
    from ml.options_feature_engine import export_daily_options_data
    
    date_arg = sys.argv[1] if len(sys.argv) > 1 else None
    
    logger.info("=" * 70)
    logger.info("OPTIONS DATA EXPORT")
    logger.info("=" * 70)
    
    if date_arg:
        logger.info(f"Exporting options data for: {date_arg}")
    else:
        logger.info(f"Exporting options data for today: {datetime.now().date()}")
    
    try:
        result = export_daily_options_data(date_arg)
        
        if "error" in result:
            logger.error(f"Export failed: {result['error']}")
            sys.exit(1)
        
        logger.info("=" * 70)
        logger.info("EXPORT SUCCESS")
        logger.info("=" * 70)
        logger.info(f"Date:              {result['date']}")
        logger.info(f"EOD Price Rows:    {result['total_eod_rows']}")
        logger.info(f"Snapshot Rows:     {result['total_snapshot_rows']}")
        logger.info(f"ML Feature Rows:   {result.get('total_ml_feature_rows', 0)}")
        logger.info(f"Output Directory:  {result['exports'].get('eod_prices_csv', '').rsplit('/', 1)[0]}")
        logger.info(f"Summary File:      {result.get('summary_file', 'N/A')}")
        logger.info("=" * 70)
        
        sys.exit(0)
    
    except Exception as e:
        logger.error(f"Export failed with exception: {e}", exc_info=True)
        sys.exit(1)
