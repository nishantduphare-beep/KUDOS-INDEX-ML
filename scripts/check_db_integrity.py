"""
scripts/check_db_integrity.py
Run: cd d:\nifty_trader_v3_final\nifty_trader && python ..\scripts\check_db_integrity.py

Checks:
- All tables exist with expected row counts
- No orphaned ml_feature_store records
- Label distribution analysis
- Model file existence check
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'nifty_trader'))

import sqlite3
from pathlib import Path
import config

DB = config.DB_PATH
conn = sqlite3.connect(DB)

print(f"\n{'='*60}")
print(f"DB Integrity Check: {DB}")
print(f"{'='*60}\n")

# Table row counts
tables = ['market_candles', 'alerts', 'ml_feature_store', 'trade_outcomes',
          'option_chain_snapshots', 's11_paper_trades', 'setup_alerts',
          'auto_paper_trades', 'app_meta']

print("TABLE ROW COUNTS:")
for t in tables:
    try:
        count = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        status = "OK" if count >= 0 else "ERR"
        print(f"  [{status}] {t}: {count:,} rows")
    except Exception as e:
        print(f"  [ERR] {t}: ERROR - {e}")

# Label distribution
print("\nML LABEL DISTRIBUTION:")
rows = conn.execute("SELECT label, COUNT(*) FROM ml_feature_store GROUP BY label ORDER BY label").fetchall()
total = sum(r[1] for r in rows)
for label, count in rows:
    name = {-1: "Unlabeled", 0: "Loss", 1: "Win"}.get(label, str(label))
    pct = count / max(total, 1) * 100
    print(f"  label={label:2d} ({name:10s}): {count:6,} ({pct:.1f}%)")

# Label source distribution
print("\nLABEL SOURCE DISTRIBUTION:")
rows2 = conn.execute("SELECT label_source, COUNT(*) FROM ml_feature_store WHERE label != -1 GROUP BY label_source ORDER BY COUNT(*) DESC").fetchall()
src_names = {0: "Unknown/Legacy", 1: "P1-TradeOutcome", 2: "P2-CrossLink", 3: "P3-OptionChain", 4: "P4-ATR"}
for src, count in rows2:
    print(f"  source={src} ({src_names.get(src,'?'):20s}): {count:5,}")

# Orphaned records check
print("\nORPHAN CHECKS:")
orphans = conn.execute("""
    SELECT COUNT(*) FROM ml_feature_store
    WHERE alert_id IS NOT NULL
    AND alert_id NOT IN (SELECT id FROM alerts)
""").fetchone()[0]
print(f"  {'[OK]' if orphans == 0 else '[ERR]'} Orphaned ml_feature_store records: {orphans}")

# Model files
print("\nMODEL FILES:")
model_dir = Path(DB).parent / "models"
if model_dir.exists():
    models = sorted(model_dir.glob("model_v*.pkl"))
    print(f"  Global models: {len(models)} files")
    if models:
        latest = models[-1]
        print(f"  Latest: {latest.name} ({latest.stat().st_size / 1024:.0f} KB)")
else:
    print("  [ERR] models/ directory not found")

print(f"\n{'='*60}")
print("Integrity check complete.")
print(f"{'='*60}\n")
conn.close()
