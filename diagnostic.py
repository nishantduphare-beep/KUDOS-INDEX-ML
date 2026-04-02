#!/usr/bin/env python3
"""Diagnostic script to check NiftyTrader health"""

import sqlite3
import json
import os
import sys
from pathlib import Path
from datetime import datetime

print("=" * 70)
print("NIFTYTRADER DIAGNOSTIC REPORT")
print("=" * 70)
print(f"Generated: {datetime.now().isoformat()}")
print()

# ===== DATABASE STATUS =====
print("DATABASE STATUS")
print("-" * 70)
try:
    db = sqlite3.connect('niftytrader.db')
    cursor = db.cursor()
    
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    print(f"Tables: {len(tables)}")
    
    for t in tables:
        cursor.execute(f"SELECT COUNT(*) FROM {t[0]}")
        cnt = cursor.fetchone()[0]
        print(f"  {t[0]:.<40} {cnt:>8} rows")
    
    print()
    print("ALERT STATISTICS")
    cursor.execute('SELECT COUNT(*) FROM alerts WHERE alert_type="TRADE_SIGNAL"')
    trade_signals = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM alerts WHERE alert_type="EARLY_MOVE"')
    early_moves = cursor.fetchone()[0]
    print(f"  TRADE_SIGNAL alerts.......... {trade_signals}")
    print(f"  EARLY_MOVE alerts........... {early_moves}")
    
    print()
    print("ML TRAINING DATA")
    cursor.execute('SELECT COUNT(*) FROM ml_feature_store WHERE label >= 0')
    labeled = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM ml_feature_store')
    total_features = cursor.fetchone()[0]
    print(f"  Labeled features............ {labeled} / {total_features}")
    
    cursor.execute('SELECT COUNT(*) FROM trade_outcomes WHERE status="CLOSED"')
    closed = cursor.fetchone()[0]
    cursor.execute('SELECT SUM(CASE WHEN outcome="WIN" THEN 1 ELSE 0 END) FROM trade_outcomes WHERE status="CLOSED"')
    wins = cursor.fetchone()[0] or 0
    win_rate = 100 * wins / max(closed, 1)
    print(f"  Closed trades............... {closed}")
    print(f"  Wins........................ {wins}")
    print(f"  Win rate.................... {win_rate:.1f}%")
    
    db.close()
    print("\n✓ Database healthy")
except Exception as e:
    print(f"\n✗ Database error: {e}")

print()

# ===== CONFIGURATION =====
print("CONFIGURATION")
print("-" * 70)
try:
    from nifty_trader import config
    print(f"Broker...................... {config.BROKER}")
    print(f"Developer Mode.............. {config.DEVELOPER_MODE}")
    print("✓ Config loaded")
except Exception as e:
    print(f"✗ Config error: {e}")

print()

# ===== CREDENTIALS =====
print("CREDENTIALS & AUTHENTICATION")
print("-" * 70)
auth_file = Path('auth/credentials.json')
if auth_file.exists():
    try:
        with open(auth_file) as f:
            creds = json.load(f)
        print(f"Saved Broker................ {creds.get('broker', 'N/A')}")
        print("✓ Credentials file found")
    except Exception as e:
        print(f"✗ Credentials read error: {e}")
else:
    print("✗ Credentials file NOT FOUND")

token_file = Path('auth/fyers_token.json')
if token_file.exists():
    try:
        with open(token_file) as f:
            token = json.load(f)
        expires = token.get('expires_at', 'N/A')
        print(f"Fyers Token Expires......... {expires}")
        print("✓ Fyers token found")
    except Exception as e:
        print(f"✗ Token read error: {e}")
else:
    print("✗ Fyers token NOT FOUND (needs OAuth)")

print()

# ===== MODEL STATUS =====
print("ML MODEL STATUS")
print("-" * 70)
model_dir = Path('nifty_trader/models')
try:
    meta_files = sorted(model_dir.glob('model_v*_meta.json'), key=lambda x: int(x.stem.split('_v')[1].split('_')[0]))
except:
    meta_files = sorted(model_dir.glob('latest_meta.json'))
if meta_files:
    latest = meta_files[-1]
    try:
        with open(latest) as f:
            meta = json.load(f)
        print(f"Latest model............... v{meta.get('version', '?')}")
        print(f"Trained at................. {meta.get('trained_at', 'N/A')}")
        print(f"Samples used............... {meta.get('samples_used', '?')}")
        print(f"Model type................. {meta.get('model_type', 'N/A')}")
        metrics = meta.get('metrics', {})
        print(f"F1 Score................... {metrics.get('f1', 0):.4f}")
        print(f"Precision.................. {metrics.get('precision', 0):.4f}")
        print(f"Recall..................... {metrics.get('recall', 0):.4f}")
        print(f"AUC........................ {metrics.get('roc_auc', 0):.4f}")
        print(f"Is Active.................. {meta.get('is_active', False)}")
        
        # Feature count
        feature_cols = meta.get('feature_cols', [])
        print(f"Feature count.............. {len(feature_cols)}")
        
        # Class balance
        pos = metrics.get('pos_samples', 0)
        neg = metrics.get('neg_samples', 0)
        total = pos + neg
        if total > 0:
            print(f"Class balance.............. {pos}/{neg} ({100*pos/total:.1f}% positive)")
        
        print("✓ Model loaded successfully")
    except Exception as e:
        print(f"✗ Model read error: {e}")
else:
    print("✗ No model files found")

print()

# ===== DEPENDENCIES =====
print("DEPENDENCIES")
print("-" * 70)
deps = {
    'PySide6': 'UI Framework',
    'pandas': 'Data processing',
    'numpy': 'Numerical computing',
    'sqlalchemy': 'Database ORM',
    'requests': 'HTTP client',
    'xgboost': 'ML - XGBoost',
    'sklearn': 'ML - scikit-learn',
}
missing = []
for dep, desc in deps.items():
    try:
        __import__(dep)
        print(f"  {dep:.<30} ✓")
    except ImportError:
        print(f"  {dep:.<30} ✗ MISSING")
        missing.append(dep)

if missing:
    print(f"\n⚠  Missing dependencies: {', '.join(missing)}")
else:
    print("\n✓ All core dependencies installed")

print()

# ===== LOGS =====
print("RECENT LOGS")
print("-" * 70)
logs_dir = Path('logs')
if logs_dir.exists():
    log_files = sorted(logs_dir.glob('niftytrader_*.log'), reverse=True)[:3]
    for log_file in log_files:
        size_kb = log_file.stat().st_size / 1024
        print(f"  {log_file.name:.<40} {size_kb:>6.1f} KB")
    
    # Check for errors in latest log
    if log_files:
        with open(log_files[0]) as f:
            content = f.read()
            error_count = content.count('ERROR')
            warning_count = content.count('WARNING')
            print(f"  Latest log errors.......... {error_count}")
            print(f"  Latest log warnings........ {warning_count}")
else:
    print("✗ No logs directory found")

print()
print("=" * 70)
print("DIAGNOSTIC COMPLETE")
print("=" * 70)
