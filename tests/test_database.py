"""tests/test_database.py — Database integration tests"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'nifty_trader'))

import pytest
import sqlite3
import config


@pytest.fixture
def conn():
    c = sqlite3.connect(config.DB_PATH)
    yield c
    c.close()


def test_all_tables_exist(conn):
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    required = {'market_candles', 'alerts', 'ml_feature_store', 'trade_outcomes',
                'option_chain_snapshots', 's11_paper_trades', 'setup_alerts'}
    missing = required - tables
    assert not missing, f"Missing tables: {missing}"


def test_ml_feature_store_has_data(conn):
    count = conn.execute("SELECT COUNT(*) FROM ml_feature_store").fetchone()[0]
    assert count > 0, "ml_feature_store is empty"


def test_no_orphaned_ml_records(conn):
    orphans = conn.execute("""
        SELECT COUNT(*) FROM ml_feature_store
        WHERE alert_id IS NOT NULL
        AND alert_id NOT IN (SELECT id FROM alerts)
    """).fetchone()[0]
    assert orphans == 0, f"Found {orphans} orphaned ml_feature_store records"


def test_alerts_table_has_data(conn):
    count = conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
    assert count > 0, "alerts table is empty"


def test_wal_mode_active(conn):
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal", f"Expected WAL mode, got: {mode}"
