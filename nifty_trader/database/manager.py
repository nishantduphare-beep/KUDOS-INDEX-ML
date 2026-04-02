"""
database/manager.py
Async-friendly database manager wrapping SQLAlchemy.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from contextlib import contextmanager

import numpy as np
from sqlalchemy import create_engine, text, Integer
from sqlalchemy.orm import sessionmaker, Session


def _sanitize_for_json(obj):
    """Recursively convert numpy types to native Python for JSON serialization.
    Also replaces NaN/Inf (not valid JSON) with 0.0 to prevent json.dumps crashes.
    """
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_for_json(v) for v in obj]
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        v = float(obj)
        return 0.0 if (v != v or v == float("inf") or v == float("-inf")) else v
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, float):
        return 0.0 if (obj != obj or obj == float("inf") or obj == float("-inf")) else obj
    return obj

from database.models import (
    Base, MarketCandle, OptionChainSnapshot,
    EngineSignal, Alert, TradeOutcome, MLFeatureRecord,
    OptionPriceHistory, SetupAlert, OptionEODPrice, S11PaperTrade,
)
import config

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Thread-safe SQLite database manager."""

    # Increment this whenever a new migration batch is added so we can
    # detect stale databases and warn the user on startup.
    SCHEMA_VERSION = 1

    def __init__(self, db_path: str = config.DB_PATH):
        from sqlalchemy import event as _sa_event
        self.engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False, "timeout": 60},
            echo=config.DB_ECHO
        )
        # Enable WAL mode + 30s busy timeout to prevent "database is locked" under concurrent writes
        @_sa_event.listens_for(self.engine, "connect")
        def _set_sqlite_pragmas(dbapi_conn, _):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=60000")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()
        self.SessionLocal = sessionmaker(
            autocommit=False, autoflush=False, bind=self.engine
        )
        self._init_db()

    def _init_db(self):
        """Create all tables if they don't exist, then migrate new columns."""
        Base.metadata.create_all(bind=self.engine)
        self._ensure_schema_version()
        self._migrate_ml_feature_store()
        self._migrate_market_candles()
        self._migrate_trade_outcomes()
        self._migrate_ml_feature_outcomes()
        self._migrate_alerts()
        self._migrate_indexes()
        self._migrate_setup_alerts()
        self._migrate_option_eod_prices()
        self._migrate_option_chain_snapshots()
        self._migrate_s11_paper_trades()
        self._migrate_auto_paper_trades()
        logger.info("Database initialized")

    def _ensure_schema_version(self):
        """
        Create the app_meta table and track the schema version integer.
        Logs a warning if the DB was created by an older app build.
        All migrations are additive so the app can still run — this is
        informational, not a hard gate.
        """
        try:
            with self.engine.connect() as conn:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS app_meta (
                        key   VARCHAR(40) PRIMARY KEY,
                        value VARCHAR(100)
                    )
                """))
                row = conn.execute(
                    text("SELECT value FROM app_meta WHERE key='schema_version'")
                ).fetchone()
                if row is None:
                    conn.execute(
                        text("INSERT INTO app_meta(key, value) VALUES ('schema_version', :v)"),
                        {"v": str(self.SCHEMA_VERSION)},
                    )
                    logger.info(f"DB: schema_version set to {self.SCHEMA_VERSION}")
                else:
                    stored = int(row[0])
                    if stored < self.SCHEMA_VERSION:
                        conn.execute(
                            text("UPDATE app_meta SET value=:v WHERE key='schema_version'"),
                            {"v": str(self.SCHEMA_VERSION)},
                        )
                        logger.info(
                            f"DB: schema upgraded {stored} → {self.SCHEMA_VERSION}"
                        )
                    elif stored > self.SCHEMA_VERSION:
                        logger.warning(
                            f"DB schema_version={stored} is newer than this build "
                            f"({self.SCHEMA_VERSION}). Consider upgrading the app."
                        )
                conn.commit()
        except Exception as e:
            logger.warning(f"schema_version check failed: {e}")

    def _migrate_ml_feature_store(self):
        """Add any missing columns to ml_feature_store (idempotent)."""
        new_columns = {
            # Engine 5
            "sweep_up":         "BOOLEAN",
            "sweep_down":       "BOOLEAN",
            "liq_wick_ratio":   "FLOAT",
            "liq_volume_ratio": "FLOAT",
            # Engine 6
            "gamma_flip":           "BOOLEAN",
            "near_gamma_wall":      "BOOLEAN",
            "dist_to_gamma_wall":   "FLOAT",
            "dist_to_call_wall":    "FLOAT",
            "dist_to_put_wall":     "FLOAT",
            # Engine 7
            "iv_expanding":     "BOOLEAN",
            "iv_skew_ratio":    "FLOAT",
            "avg_atm_iv":       "FLOAT",
            "iv_change_pct":    "FLOAT",
            # Engine 8
            "market_regime":        "VARCHAR(15)",
            "regime_adx":           "FLOAT",
            "regime_atr_ratio":     "FLOAT",
            # New trigger flags
            "liquidity_trap_triggered": "BOOLEAN",
            "gamma_triggered":          "BOOLEAN",
            "iv_triggered":             "BOOLEAN",
            "regime_triggered":         "BOOLEAN",
            # Timing features (forming-candle and theta-decay)
            "candle_completion_pct": "FLOAT",
            "candles_to_close":      "FLOAT",
            # Group A: Time context
            "mins_since_open": "FLOAT",
            "session":         "INTEGER",
            "is_expiry":       "INTEGER",
            "day_of_week":     "INTEGER",
            "dte":             "INTEGER",
            # Group B: Price context
            "spot_vs_prev_pct": "FLOAT",
            "atr_pct_spot":     "FLOAT",
            "chop":             "FLOAT",
            "efficiency_ratio": "FLOAT",
            "gap_pct":          "FLOAT",
            "preopen_gap_pct":  "FLOAT",   # futures gap captured 9:00–9:14, frozen at 9:15
            # Group C: Candle patterns
            "prev_body_ratio":  "FLOAT",
            "prev_bullish":     "INTEGER",
            "consec_bull":      "INTEGER",
            "consec_bear":      "INTEGER",
            "range_expansion":  "FLOAT",
            # Group D: Index correlation
            "aligned_indices":  "INTEGER",
            "market_breadth":   "FLOAT",
            # Group E: OI & Futures
            "futures_oi_m":        "FLOAT",
            "futures_oi_chg_pct":  "FLOAT",
            "atm_oi_ratio":        "FLOAT",
            # Extended futures — institutional footprint
            "excess_basis_pct":    "FLOAT",
            "futures_basis_slope": "FLOAT",
            "oi_regime":           "INTEGER",
            "oi_regime_bullish":   "INTEGER",
            "oi_regime_bearish":   "INTEGER",
            # Group F: MTF ADX
            "adx_5m":       "FLOAT",
            "plus_di_5m":   "FLOAT",
            "minus_di_5m":  "FLOAT",
            "adx_15m":      "FLOAT",
            # Group F (extended): MTF DI slopes + reversal flags
            "plus_di_slope_5m":   "FLOAT",
            "minus_di_slope_5m":  "FLOAT",
            "plus_di_slope_15m":  "FLOAT",
            "minus_di_slope_15m": "FLOAT",
            "di_reversal_5m":     "INTEGER",
            "di_reversal_15m":    "INTEGER",
            "di_reversal_both":   "INTEGER",
            # Group G: VIX
            "vix":      "FLOAT",
            "vix_high": "INTEGER",
            # Group H: Signal identity
            "direction_encoded": "INTEGER",
            "index_encoded":     "INTEGER",
            "is_trade_signal":   "INTEGER DEFAULT 0",
            # Group G (extended): Price Structure (5m + 15m HH/HL/LH/LL)
            "struct_5m":           "INTEGER",
            "struct_15m":          "INTEGER",
            "struct_5m_aligned":   "INTEGER",
            "struct_15m_aligned":  "INTEGER",
            "struct_both_aligned": "INTEGER",
            # Engine 7-new: VWAP Pressure
            "vwap":             "FLOAT",
            "dist_to_vwap_pct": "FLOAT",
            "vwap_cross_up":    "BOOLEAN",
            "vwap_cross_down":  "BOOLEAN",
            "vwap_bounce":      "BOOLEAN",
            "vwap_rejection":   "BOOLEAN",
            "vwap_vol_ratio":   "FLOAT",
            "vwap_triggered":   "BOOLEAN",
            # Better labeling — graded outcome quality
            "label_quality":    "INTEGER DEFAULT -1",
            # Label source priority (1=TradeOutcome, 2=CrossLink, 3=OptionChain, 4=ATR)
            "label_source":          "INTEGER DEFAULT 0",
            # Historical performance context
            "setup_win_rate":        "FLOAT DEFAULT 0.0",
            "mins_since_last_signal":"FLOAT DEFAULT 0.0",
        }
        try:
            with self.engine.connect() as conn:
                existing = {
                    row[1]
                    for row in conn.execute(
                        text("PRAGMA table_info(ml_feature_store)")
                    )
                }
                for col, col_type in new_columns.items():
                    if col not in existing:
                        conn.execute(
                            text(f"ALTER TABLE ml_feature_store ADD COLUMN {col} {col_type}")
                        )
                        logger.info(f"Migrated ml_feature_store: added column '{col}'")
                conn.commit()
        except Exception as e:
            logger.error(f"ML feature store migration FAILED: {e}")
            raise

    def _migrate_trade_outcomes(self):
        """Add new outcome-tracking columns to trade_outcomes (idempotent)."""
        new_cols = {
            # Post-close tracking
            "post_close_t1_hit":       "BOOLEAN DEFAULT 0",
            "post_close_t1_hit_time":  "DATETIME",
            "post_close_t2_hit":       "BOOLEAN DEFAULT 0",
            "post_close_t2_hit_time":  "DATETIME",
            "post_close_t3_hit":       "BOOLEAN DEFAULT 0",
            "post_close_t3_hit_time":  "DATETIME",
            "post_close_max_fav_atr":  "FLOAT DEFAULT 0",
            "post_close_max_adv_atr":  "FLOAT DEFAULT 0",
            "post_close_eod_spot":     "FLOAT",
            "post_sl_reversal":        "BOOLEAN DEFAULT 0",
            "post_sl_full_recovery":   "BOOLEAN DEFAULT 0",
            # Existing tracking columns (kept for idempotency)
            "direction":       "VARCHAR(10)",
            "entry_spot":      "FLOAT",
            "atr_at_signal":   "FLOAT",
            "spot_sl":         "FLOAT",
            "spot_t1":         "FLOAT",
            "spot_t2":         "FLOAT",
            "spot_t3":         "FLOAT",
            "stop_loss_opt":   "FLOAT",
            "t1_opt":          "FLOAT",
            "t2_opt":          "FLOAT",
            "t3_opt":          "FLOAT",
            "sl_hit":          "BOOLEAN DEFAULT 0",
            "sl_hit_time":     "DATETIME",
            "sl_hit_spot":     "FLOAT",
            "t1_hit":          "BOOLEAN DEFAULT 0",
            "t1_hit_time":     "DATETIME",
            "t2_hit":          "BOOLEAN DEFAULT 0",
            "t2_hit_time":     "DATETIME",
            "t3_hit":          "BOOLEAN DEFAULT 0",
            "t3_hit_time":     "DATETIME",
            "mfe_atr":         "FLOAT DEFAULT 0",
            "mae_atr":         "FLOAT DEFAULT 0",
            "eod_spot":        "FLOAT",
            "status":          "VARCHAR(10) DEFAULT 'OPEN'",
            # ── Rupee P&L tracking ──────────────────────────────────
            "lot_size":        "INTEGER DEFAULT 0",
            "investment_amt":  "FLOAT DEFAULT 0",   # entry_premium × lot_size
            "pnl_sl":          "FLOAT DEFAULT 0",   # rupees if SL hit (negative)
            "pnl_t1":          "FLOAT DEFAULT 0",   # rupees if T1 hit
            "pnl_t2":          "FLOAT DEFAULT 0",   # rupees if T2 hit
            "pnl_t3":          "FLOAT DEFAULT 0",   # rupees if T3 hit
            "realized_pnl":    "FLOAT DEFAULT 0",   # actual rupees at close
            # ── Alert type tag ──────────────────────────────────────
            "alert_type":      "VARCHAR(20) DEFAULT 'TRADE_SIGNAL'",
        }
        try:
            with self.engine.connect() as conn:
                existing = {
                    row[1]
                    for row in conn.execute(text("PRAGMA table_info(trade_outcomes)"))
                }
                for col, col_def in new_cols.items():
                    if col not in existing:
                        conn.execute(text(
                            f"ALTER TABLE trade_outcomes ADD COLUMN {col} {col_def}"
                        ))
                        logger.info(f"Migrated trade_outcomes: added '{col}'")
                conn.commit()
        except Exception as e:
            logger.error(f"trade_outcomes migration FAILED: {e}")
            raise

    def _migrate_ml_feature_outcomes(self):
        """Add outcome feedback columns to ml_feature_store (idempotent)."""
        new_cols = {
            "sl_hit":               "BOOLEAN",
            "t1_hit":               "BOOLEAN",
            "t2_hit":               "BOOLEAN",
            "t3_hit":               "BOOLEAN",
            "max_favorable_atr":    "FLOAT",
            "max_adverse_atr":      "FLOAT",
            "post_sl_reversal":     "BOOLEAN",
            "post_sl_full_recovery":"BOOLEAN",
            "post_close_max_fav_atr":"FLOAT",
        }
        try:
            with self.engine.connect() as conn:
                existing = {
                    row[1]
                    for row in conn.execute(text("PRAGMA table_info(ml_feature_store)"))
                }
                for col, col_def in new_cols.items():
                    if col not in existing:
                        conn.execute(text(
                            f"ALTER TABLE ml_feature_store ADD COLUMN {col} {col_def}"
                        ))
                        logger.info(f"Migrated ml_feature_store: added '{col}'")
                conn.commit()
        except Exception as e:
            logger.error(f"ml_feature_store outcome migration FAILED: {e}")
            raise

    def _migrate_alerts(self):
        """Add ml_score, ml_phase, target1/2/3 columns to alerts (idempotent)."""
        new_cols = {
            "ml_score":  "FLOAT",
            "ml_phase":  "INTEGER",
            "target1":   "FLOAT",
            "target2":   "FLOAT",
            "target3":   "FLOAT",
        }
        with self.engine.connect() as conn:
            existing = {
                row[1]
                for row in conn.execute(text("PRAGMA table_info(alerts)"))
            }
            for col, col_def in new_cols.items():
                if col not in existing:
                    conn.execute(text(f"ALTER TABLE alerts ADD COLUMN {col} {col_def}"))
                    logger.info(f"Migrated alerts: added column '{col}'")
            conn.commit()

    def _migrate_indexes(self):
        """Create missing indexes idempotently (CREATE INDEX IF NOT EXISTS)."""
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_ml_index_label_ts "
            "ON ml_feature_store(index_name, label, timestamp)",
            # Allows fast alert_type='TRADE_SIGNAL' + date range queries
            "CREATE INDEX IF NOT EXISTS idx_alert_type_ts "
            "ON alerts(alert_type, timestamp)",
            # L5 additions — performance indexes for common query patterns
            "CREATE INDEX IF NOT EXISTS idx_outcome_index_entry "
            "ON trade_outcomes(index_name, entry_time)",
            "CREATE INDEX IF NOT EXISTS idx_engine_ts "
            "ON engine_signals(timestamp)",
            "CREATE INDEX IF NOT EXISTS idx_candle_is_futures "
            "ON market_candles(is_futures)",
            # Fast candle lookups by index + time range (most common query pattern)
            "CREATE INDEX IF NOT EXISTS idx_candles_idx_ts "
            "ON market_candles(index_name, timestamp)",
            # Fast ML feature lookup by alert
            "CREATE INDEX IF NOT EXISTS idx_features_alert_idx "
            "ON ml_feature_store(alert_id, index_name)",
            # Fast open-trade queries
            "CREATE INDEX IF NOT EXISTS idx_outcomes_open "
            "ON trade_outcomes(status) WHERE status='OPEN'",
            # Fast alert timestamp + alert_type queries (column is alert_type, not signal_type)
            "CREATE INDEX IF NOT EXISTS idx_alerts_ts_sig "
            "ON alerts(timestamp DESC, alert_type)",
        ]
        try:
            with self.engine.connect() as conn:
                for sql in indexes:
                    conn.execute(text(sql))
                conn.commit()
        except Exception as e:
            logger.warning(f"Index migration: {e}")

    def _migrate_setup_alerts(self):
        """Create setup_alerts table and indexes if they don't exist (idempotent)."""
        try:
            with self.engine.connect() as conn:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS setup_alerts (
                        id            INTEGER PRIMARY KEY AUTOINCREMENT,
                        alert_id      INTEGER REFERENCES alerts(id),
                        index_name    VARCHAR(20) NOT NULL,
                        timestamp     DATETIME NOT NULL,
                        direction     VARCHAR(10) NOT NULL,
                        setup_name    VARCHAR(40) NOT NULL,
                        setup_grade   VARCHAR(4)  NOT NULL,
                        expected_wr   FLOAT NOT NULL,
                        description   VARCHAR(120),
                        spot_price    FLOAT DEFAULT 0,
                        atr           FLOAT DEFAULT 0,
                        engines_count INTEGER DEFAULT 0,
                        regime        VARCHAR(15),
                        volume_ratio  FLOAT DEFAULT 0,
                        pcr           FLOAT DEFAULT 0,
                        label         INTEGER DEFAULT -1,
                        label_quality INTEGER DEFAULT -1,
                        t1_hit        BOOLEAN DEFAULT 0,
                        t2_hit        BOOLEAN DEFAULT 0,
                        t3_hit        BOOLEAN DEFAULT 0,
                        sl_hit        BOOLEAN DEFAULT 0,
                        realized_pnl  FLOAT DEFAULT 0,
                        created_at    DATETIME
                    )
                """))
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS idx_setup_alerts_index_ts "
                    "ON setup_alerts(index_name, timestamp)"
                ))
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS idx_setup_alerts_name_label "
                    "ON setup_alerts(setup_name, label)"
                ))
                # Idempotent: add realized_pnl column if missing (existing DBs)
                existing_sa = {
                    row[1] for row in conn.execute(text("PRAGMA table_info(setup_alerts)"))
                }
                if "realized_pnl" not in existing_sa:
                    conn.execute(text(
                        "ALTER TABLE setup_alerts ADD COLUMN realized_pnl FLOAT DEFAULT 0"
                    ))
                conn.commit()
        except Exception as e:
            logger.warning(f"setup_alerts migration: {e}")

    def _migrate_option_eod_prices(self):
        """Create option_eod_prices table if missing; add new columns idempotently."""
        try:
            with self.engine.connect() as conn:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS option_eod_prices (
                        id            INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp     DATETIME NOT NULL,
                        index_name    VARCHAR(20) NOT NULL,
                        expiry        VARCHAR(15) NOT NULL,
                        spot_price    FLOAT DEFAULT 0,
                        atm_strike    FLOAT DEFAULT 0,
                        strike        FLOAT NOT NULL,
                        strike_offset INTEGER DEFAULT 0,
                        call_ltp      FLOAT DEFAULT 0,
                        call_oi       FLOAT DEFAULT 0,
                        call_iv       FLOAT DEFAULT 0,
                        call_volume   FLOAT DEFAULT 0,
                        put_ltp       FLOAT DEFAULT 0,
                        put_oi        FLOAT DEFAULT 0,
                        put_iv        FLOAT DEFAULT 0,
                        put_volume    FLOAT DEFAULT 0,
                        created_at    DATETIME
                    )
                """))
                # Add Greek + second-expiry columns to existing tables
                existing = {
                    row[1]
                    for row in conn.execute(text("PRAGMA table_info(option_eod_prices)"))
                }
                new_cols = {
                    "delta_call":     "FLOAT DEFAULT 0",
                    "gamma_call":     "FLOAT DEFAULT 0",
                    "theta_call":     "FLOAT DEFAULT 0",
                    "vega_call":      "FLOAT DEFAULT 0",
                    "delta_put":      "FLOAT DEFAULT 0",
                    "gamma_put":      "FLOAT DEFAULT 0",
                    "theta_put":      "FLOAT DEFAULT 0",
                    "vega_put":       "FLOAT DEFAULT 0",
                    "is_next_expiry": "BOOLEAN DEFAULT 0",
                }
                for col, col_def in new_cols.items():
                    if col not in existing:
                        conn.execute(
                            text(f"ALTER TABLE option_eod_prices ADD COLUMN {col} {col_def}")
                        )
                        logger.info(f"Migrated option_eod_prices: added column '{col}'")
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS idx_eod_index_ts "
                    "ON option_eod_prices(index_name, timestamp)"
                ))
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS idx_eod_strike_ts "
                    "ON option_eod_prices(index_name, strike, timestamp)"
                ))
                conn.commit()
        except Exception as e:
            logger.warning(f"option_eod_prices migration: {e}")

    def _migrate_option_chain_snapshots(self):
        """Add avg_atm_iv column to option_chain_snapshots if missing (idempotent)."""
        try:
            with self.engine.connect() as conn:
                existing = {
                    row[1]
                    for row in conn.execute(text("PRAGMA table_info(option_chain_snapshots)"))
                }
                if "avg_atm_iv" not in existing:
                    conn.execute(text(
                        "ALTER TABLE option_chain_snapshots ADD COLUMN avg_atm_iv FLOAT DEFAULT 0"
                    ))
                    logger.info("Migrated option_chain_snapshots: added column 'avg_atm_iv'")
                conn.commit()
        except Exception as e:
            logger.warning(f"option_chain_snapshots migration: {e}")

    def _migrate_market_candles(self):
        """Add oi and is_futures columns to market_candles if missing (idempotent)."""
        new_cols = {"oi": "FLOAT DEFAULT 0", "is_futures": "BOOLEAN DEFAULT 0"}
        try:
            with self.engine.connect() as conn:
                existing = {
                    row[1]
                    for row in conn.execute(text("PRAGMA table_info(market_candles)"))
                }
                for col, col_def in new_cols.items():
                    if col not in existing:
                        conn.execute(
                            text(f"ALTER TABLE market_candles ADD COLUMN {col} {col_def}")
                        )
                        logger.info(f"Migrated market_candles: added column '{col}'")
                conn.commit()
        except Exception as e:
            logger.warning(f"market_candles migration: {e}")

    @contextmanager
    def get_session(self) -> Session:
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"DB session error: {e}")
            raise
        finally:
            session.close()

    # ─── CANDLES ───────────────────────────────────────────────────

    def save_candle(self, candle_data: Dict[str, Any]):
        # B4 fix: guard against duplicate (index_name, timestamp, interval, is_futures).
        # Without this, _persist_latest_candle() called every 3 min accumulates copies.
        with self.get_session() as session:
            exists = session.query(MarketCandle).filter(
                MarketCandle.index_name == candle_data.get("index_name"),
                MarketCandle.timestamp  == candle_data.get("timestamp"),
                MarketCandle.interval   == candle_data.get("interval", 3),
                MarketCandle.is_futures == candle_data.get("is_futures", False),
            ).first()
            if exists:
                return  # Skip duplicate
            candle = MarketCandle(**candle_data)
            session.add(candle)

    def save_candles_bulk(self, candles: List[Dict[str, Any]]):
        with self.get_session() as session:
            session.bulk_insert_mappings(MarketCandle, candles)

    def save_futures_candles_bulk(self, candles: List[Dict[str, Any]]):
        """Persist futures OHLCV+OI candles (is_futures=True) in bulk."""
        rows = [{**c, "is_futures": True} for c in candles]
        with self.get_session() as session:
            session.bulk_insert_mappings(MarketCandle, rows)

    def update_futures_candle_oi(
        self, index_name: str, timestamp, interval: int, oi: float
    ):
        """
        Upsert OI for a futures candle row identified by (index_name, timestamp, interval).
        - If row exists: updates its OI field.
        - If not: inserts a minimal row with the given OI.
        Called from candle loop after live OI is available from quotes API.
        """
        with self.get_session() as session:
            row = session.query(MarketCandle).filter(
                MarketCandle.index_name == index_name,
                MarketCandle.timestamp  == timestamp,
                MarketCandle.interval   == interval,
                MarketCandle.is_futures == True,  # noqa: E712
            ).first()
            if row:
                row.oi = oi
            # If row doesn't exist yet, the candle loop will insert it shortly via
            # _persist_latest_futures_candle(); no action needed here.

    def get_recent_candles(
        self, index_name: str, limit: int = 60
    ) -> List[MarketCandle]:
        with self.get_session() as session:
            return (
                session.query(MarketCandle)
                .filter(MarketCandle.index_name == index_name,
                        MarketCandle.is_futures == False)  # noqa: E712
                .order_by(MarketCandle.timestamp.desc())
                .limit(limit)
                .all()
            )

    def get_oi_history_intraday(
        self, index_name: str, interval: int = 3, ref_date=None
    ) -> List[MarketCandle]:
        """
        Return today's (or ref_date's) futures candles with OI, ordered ascending.
        Used to reconstruct how OI evolved through the session.
        """
        if ref_date is None:
            ref_date = datetime.now().date()
        day_start = datetime(ref_date.year, ref_date.month, ref_date.day)
        day_end   = day_start + timedelta(days=1)
        with self.get_session() as session:
            return (
                session.query(MarketCandle)
                .filter(
                    MarketCandle.index_name == index_name,
                    MarketCandle.is_futures == True,   # noqa: E712
                    MarketCandle.interval   == interval,
                    MarketCandle.timestamp  >= day_start,
                    MarketCandle.timestamp  <  day_end,
                )
                .order_by(MarketCandle.timestamp.asc())
                .all()
            )

    # ─── OPTION CHAIN ──────────────────────────────────────────────

    def save_option_snapshot(self, snapshot_data: Dict[str, Any]):
        with self.get_session() as session:
            snapshot = OptionChainSnapshot(**snapshot_data)
            session.add(snapshot)

    def get_latest_option_snapshot(
        self, index_name: str
    ) -> Optional[OptionChainSnapshot]:
        with self.get_session() as session:
            return (
                session.query(OptionChainSnapshot)
                .filter(OptionChainSnapshot.index_name == index_name)
                .order_by(OptionChainSnapshot.timestamp.desc())
                .first()
            )

    def get_option_snapshots(
        self, index_name: str, limit: int = 10
    ) -> List[OptionChainSnapshot]:
        with self.get_session() as session:
            return (
                session.query(OptionChainSnapshot)
                .filter(OptionChainSnapshot.index_name == index_name)
                .order_by(OptionChainSnapshot.timestamp.desc())
                .limit(limit)
                .all()
            )

    def get_iv_rank(self, index_name: str, current_iv: float,
                    lookback_days: int = 20) -> float:
        """
        Compute IV Rank (0-100 percentile) for current_iv vs last lookback_days
        of avg_atm_iv stored in option_chain_snapshots.
        Returns 0.0 if insufficient history.
        """
        if current_iv <= 0:
            return 0.0
        try:
            cutoff = datetime.now() - timedelta(days=lookback_days)
            with self.get_session() as session:
                rows = (
                    session.query(OptionChainSnapshot.avg_atm_iv)
                    .filter(
                        OptionChainSnapshot.index_name == index_name,
                        OptionChainSnapshot.timestamp  >= cutoff,
                        OptionChainSnapshot.avg_atm_iv > 0,
                    )
                    .all()
                )
            hist = [float(r[0]) for r in rows if r[0]]
            if not hist:
                return 0.0
            below = sum(1 for v in hist if v <= current_iv)
            return round(below / len(hist) * 100.0, 1)
        except Exception as e:
            logger.debug(f"get_iv_rank [{index_name}]: {e}")
            return 0.0

    # ─── ENGINE SIGNALS ────────────────────────────────────────────

    def save_engine_signal(self, signal_data: Dict[str, Any]):
        data = dict(signal_data)
        data["features"] = _sanitize_for_json(data.get("features", {}))
        with self.get_session() as session:
            signal = EngineSignal(**data)
            session.add(signal)

    def get_engine_signals(
        self, index_name: str, since_minutes: int = 15
    ) -> List[EngineSignal]:
        since = datetime.now() - timedelta(minutes=since_minutes)
        with self.get_session() as session:
            rows = (
                session.query(EngineSignal)
                .filter(
                    EngineSignal.index_name == index_name,
                    EngineSignal.timestamp >= since
                )
                .order_by(EngineSignal.timestamp.desc())
                .all()
            )
            session.expunge_all()
            return rows

    # ─── SETUP ALERTS ──────────────────────────────────────────────

    def save_setup_alerts(self, hits: list, alert_id: int = 0) -> int:
        """
        Save a batch of SetupHit objects to setup_alerts table.
        Returns number of rows inserted.
        hits: list of SetupHit from SetupScreener.evaluate()
        """
        if not hits:
            return 0
        rows = []
        for h in hits:
            rows.append({
                "alert_id":      alert_id or None,
                "index_name":    h.index_name,
                "timestamp":     h.timestamp,
                "direction":     h.direction,
                "setup_name":    h.setup_name,
                "setup_grade":   h.setup_grade,
                "expected_wr":   h.expected_wr,
                "description":   h.description,
                "spot_price":    float(h.spot_price),
                "atr":           float(h.atr),
                "engines_count": int(h.engines_count),
                "regime":        h.regime,
                "volume_ratio":  float(h.volume_ratio),
                "pcr":           float(h.pcr),
                "label":         -1,
                "label_quality": -1,
                "created_at":    datetime.now(),
            })
        try:
            with self.get_session() as session:
                session.bulk_insert_mappings(SetupAlert, rows)
            return len(rows)
        except Exception as e:
            logger.warning(f"save_setup_alerts failed: {e}")
            return 0

    def get_setups_for_alert(self, alert_id: int) -> List[Dict[str, Any]]:
        """Return all setup_alerts rows for a given alert_id (for UI display)."""
        try:
            with self.get_session() as session:
                rows = (
                    session.query(SetupAlert)
                    .filter(SetupAlert.alert_id == alert_id)
                    .order_by(SetupAlert.setup_grade)
                    .all()
                )
                return [
                    {
                        "setup_name":   r.setup_name,
                        "setup_grade":  r.setup_grade,
                        "expected_wr":  r.expected_wr,
                        "label":        r.label,
                        "label_quality": r.label_quality,
                        "t2_hit":       r.t2_hit,
                        "t3_hit":       r.t3_hit,
                        "sl_hit":       r.sl_hit,
                    }
                    for r in rows
                ]
        except Exception as e:
            logger.warning(f"get_setups_for_alert: {e}")
            return []

    def get_setup_alert_stats(self) -> List[Dict[str, Any]]:
        """
        Returns win rate stats per setup — for reporting and ML.
        Only includes setups with label >= 0 (labeled records).
        """
        try:
            with self.get_session() as session:
                from sqlalchemy import func
                rows = (
                    session.query(
                        SetupAlert.setup_name,
                        SetupAlert.setup_grade,
                        SetupAlert.expected_wr,
                        func.count(SetupAlert.id).label("total"),
                        func.sum(
                            (SetupAlert.label == 1).cast(Integer)
                        ).label("wins"),
                        func.avg(SetupAlert.label_quality).label("avg_quality"),
                        func.sum(
                            (SetupAlert.t2_hit == True).cast(Integer)  # noqa: E712
                        ).label("t2_count"),
                        func.sum(
                            (SetupAlert.t3_hit == True).cast(Integer)  # noqa: E712
                        ).label("t3_count"),
                        func.sum(SetupAlert.realized_pnl).label("total_pnl"),
                        func.avg(SetupAlert.realized_pnl).label("avg_pnl"),
                    )
                    .filter(SetupAlert.label >= 0)
                    .group_by(SetupAlert.setup_name)
                    .order_by(func.count(SetupAlert.id).desc())
                    .all()
                )
                result = []
                for r in rows:
                    total = r.total or 0
                    wins  = r.wins  or 0
                    wr    = (wins / total * 100) if total > 0 else 0.0
                    result.append({
                        "setup_name":   r.setup_name,
                        "setup_grade":  r.setup_grade,
                        "expected_wr":  r.expected_wr,
                        "total":        total,
                        "wins":         wins,
                        "actual_wr":    round(wr, 1),
                        "avg_quality":  round(float(r.avg_quality or 0), 2),
                        "t2_count":     r.t2_count or 0,
                        "t3_count":     r.t3_count or 0,
                        "total_pnl":    round(float(r.total_pnl or 0), 2),
                        "avg_pnl":      round(float(r.avg_pnl or 0), 2),
                    })
                return result
        except Exception as e:
            logger.warning(f"get_setup_alert_stats: {e}")
            return []

    # ─── OPTION EOD PRICES ─────────────────────────────────────────

    def save_option_eod_prices(self, rows: List[Dict[str, Any]]) -> int:
        """
        Bulk-insert option strike prices (ATM ± N strikes) from a chain update.
        rows: list of dicts with keys matching option_eod_prices columns.
        Returns number of rows inserted.
        """
        if not rows:
            return 0
        try:
            with self.get_session() as session:
                session.bulk_insert_mappings(OptionEODPrice, rows)
            return len(rows)
        except Exception as e:
            logger.warning(f"save_option_eod_prices failed: {e}")
            return 0

    # ─── ALERTS ────────────────────────────────────────────────────

    def save_alert(self, alert_data: Dict[str, Any]) -> int:
        data = dict(alert_data)
        data["raw_features"]      = _sanitize_for_json(data.get("raw_features", {}))
        data["engines_triggered"] = _sanitize_for_json(data.get("engines_triggered", []))
        # M4 fix: strip keys that don't exist in the Alert model to prevent
        # SQLAlchemy "unexpected keyword argument" crashes when new fields are
        # passed before a migration has run, or when callers include extra data.
        valid_cols = {c.name for c in Alert.__table__.columns}
        data = {k: v for k, v in data.items() if k in valid_cols}
        with self.get_session() as session:
            alert = Alert(**data)
            session.add(alert)
            session.flush()
            return alert.id

    def get_recent_alerts(self, limit: int = 50) -> List[Alert]:
        with self.get_session() as session:
            return (
                session.query(Alert)
                .order_by(Alert.timestamp.desc())
                .limit(limit)
                .all()
            )

    def update_alert_outcome(
        self,
        alert_id: int,
        outcome: str,
        pnl: float,
        notes: str = ""
    ):
        with self.get_session() as session:
            alert = session.query(Alert).filter(Alert.id == alert_id).first()
            if alert:
                alert.outcome = outcome
                alert.outcome_pnl = pnl
                alert.outcome_notes = notes
                alert.outcome_timestamp = datetime.now()

    # ─── OPTION PRICE HISTORY ──────────────────────────────────────

    def save_option_price(self, alert_id: int, instrument: str, timestamp,
                          ltp: float, entry_price: float, candle_num: int):
        """Store one option LTP data point for a tracked signal."""
        pct = round((ltp - entry_price) / max(entry_price, 0.01) * 100, 3) if entry_price else 0.0
        with self.get_session() as session:
            session.add(OptionPriceHistory(
                alert_id=alert_id,
                instrument=instrument,
                timestamp=timestamp,
                ltp=ltp,
                entry_price=entry_price,
                pct_from_entry=pct,
                candle_num=candle_num,
            ))

    def get_option_price_history(self, alert_id: int) -> list:
        """Return all LTP records for a given alert, ordered by candle_num."""
        with self.get_session() as session:
            rows = session.query(OptionPriceHistory).filter(
                OptionPriceHistory.alert_id == alert_id
            ).order_by(OptionPriceHistory.candle_num).all()
            return [{"candle_num": r.candle_num, "ltp": r.ltp,
                     "pct_from_entry": r.pct_from_entry,
                     "timestamp": r.timestamp} for r in rows]

    def get_option_price_histories_bulk(self, alert_ids: list) -> dict:
        """Return option price histories for multiple alert_ids as dict keyed by alert_id."""
        if not alert_ids:
            return {}
        with self.get_session() as session:
            rows = session.query(OptionPriceHistory).filter(
                OptionPriceHistory.alert_id.in_(alert_ids)
            ).order_by(OptionPriceHistory.alert_id, OptionPriceHistory.candle_num).all()
            result = {}
            for r in rows:
                result.setdefault(r.alert_id, []).append({
                    "candle_num": r.candle_num, "ltp": r.ltp,
                    "pct_from_entry": r.pct_from_entry,
                    "timestamp": r.timestamp,
                })
            return result

    # ─── ML FEATURE STORE ──────────────────────────────────────────

    def get_rolling_setup_win_rates(
        self,
        index_name: str,
        lookback: int = 20
    ) -> Dict[str, float]:
        """
        Return a dict {setup_name: win_rate_pct (0-100)} based on the last
        `lookback` labeled trades per setup for the given index.

        Only labeled rows (label >= 0) are counted. Win = label == 1.
        Returns empty dict if no data.
        """
        with self.get_session() as session:
            from database.models import SetupAlert
            from sqlalchemy import func, case

            rows = (
                session.query(
                    SetupAlert.setup_name,
                    func.count(SetupAlert.id).label("total"),
                    func.sum(case((SetupAlert.label == 1, 1), else_=0)).label("wins"),
                )
                .filter(
                    SetupAlert.index_name == index_name,
                    SetupAlert.label >= 0,
                )
                .group_by(SetupAlert.setup_name)
                .all()
            )
            result: Dict[str, float] = {}
            for r in rows:
                if r.total and r.total > 0:
                    result[r.setup_name] = round((r.wins or 0) / r.total * 100.0, 1)
            return result

    def save_ml_features(self, features: Dict[str, Any]):
        with self.get_session() as session:
            record = MLFeatureRecord(**features)
            session.add(record)

    def get_ml_dataset(
        self,
        index_name: Optional[str] = None,
        labeled_only: bool = True
    ) -> List[Dict[str, Any]]:
        """Return ML records as plain dicts (not ORM objects) to avoid detached-instance errors."""
        with self.get_session() as session:
            q = session.query(MLFeatureRecord)
            if index_name:
                q = q.filter(MLFeatureRecord.index_name == index_name)
            if labeled_only:
                q = q.filter(MLFeatureRecord.label != -1)
            records = q.order_by(MLFeatureRecord.timestamp).all()
            # Convert inside session — accessing ORM attributes after session closes
            # triggers a lazy-load on a detached instance and raises an error.
            return [
                {c.name: getattr(r, c.name) for c in r.__table__.columns}
                for r in records
            ]

    # ─── TRADE OUTCOMES ────────────────────────────────────────────

    def save_trade_outcome(self, outcome_data: Dict[str, Any]) -> int:
        """Insert a new TradeOutcome row. Returns its id."""
        with self.get_session() as session:
            row = TradeOutcome(**outcome_data)
            session.add(row)
            session.flush()
            return row.id

    def update_trade_outcome(self, outcome_id: int, updates: Dict[str, Any]):
        """Patch an existing TradeOutcome row with arbitrary field updates."""
        with self.get_session() as session:
            row = session.query(TradeOutcome).filter(TradeOutcome.id == outcome_id).first()
            if row:
                for k, v in updates.items():
                    setattr(row, k, v)

    def get_open_outcomes(self) -> List[TradeOutcome]:
        """Return all OPEN TradeOutcome rows — used by OutcomeTracker on startup."""
        with self.get_session() as session:
            rows = (
                session.query(TradeOutcome)
                .filter(TradeOutcome.status == "OPEN")
                .all()
            )
            # Detach from session so caller can use them freely
            session.expunge_all()
            return rows

    def get_trade_outcome_by_alert(self, alert_id: int):
        """Return the most recent TradeOutcome for the given alert_id, or None."""
        with self.get_session() as session:
            row = (
                session.query(TradeOutcome)
                .filter(TradeOutcome.alert_id == alert_id)
                .order_by(TradeOutcome.id.desc())
                .first()
            )
            if row:
                session.expunge(row)
            return row

    def update_ml_feature_outcome(
        self,
        alert_id: int,
        sl_hit: bool,
        t1_hit: bool,
        t2_hit: bool,
        t3_hit: bool,
        max_favorable_atr: float,
        max_adverse_atr: float,
        candles_to_close: float = 0.0,
        realized_pnl: float = 0.0,
    ):
        """
        Write outcome feedback into the ML feature record for this alert.
        Also sets a time-adjusted label:
          T3 hit             → label = 1 (always — strong enough move to overcome theta)
          T2 hit ≤ 8 candles → label = 1
          T1 hit ≤ 5 candles → label = 1
          T1/T2 hit slowly   → label = 0 (theta decay likely eroded option value)
          SL hit             → label = 0 (false signal)
        BUG-3 fix: previously any T1 hit → label=1 regardless of time taken.
        Options lose theta each candle; a T1 hit after 6+ candles (18+ min) may be
        a net loss in option P&L even though the spot level was reached.
        Updates the parent Alert row outcome too (WIN/LOSS).
        """
        import config as _cfg
        t1_max = getattr(_cfg, "OPTION_WIN_T1_MAX_CANDLES", 5)
        t2_max = getattr(_cfg, "OPTION_WIN_T2_MAX_CANDLES", 8)

        if t3_hit:
            # T3 always WIN — move was strong enough that theta is irrelevant
            label = 1
        elif t2_hit and (candles_to_close < 0 or candles_to_close <= t2_max):
            # candles_to_close < 0 = unknown entry_time (rehydrated trade) — skip time check
            label = 1
        elif t1_hit and (candles_to_close < 0 or candles_to_close <= t1_max):
            label = 1
        else:
            # SL hit, or slow target hit (theta eroded option value)
            label = 0

        # Compute graded quality from hit flags (mirrors auto_labeler logic)
        if t3_hit:
            quality = 3
        elif t2_hit:
            quality = 2
        elif t1_hit:
            quality = 1
        else:
            quality = 0  # SL hit or no move

        outcome_str = "WIN" if label == 1 else "LOSS"

        with self.get_session() as session:
            AlertModel = Alert   # alias for readability
            rec = session.query(MLFeatureRecord).filter(
                MLFeatureRecord.alert_id == alert_id
            ).first()
            if rec:
                rec.sl_hit            = sl_hit
                rec.t1_hit            = t1_hit
                rec.t2_hit            = t2_hit
                rec.t3_hit            = t3_hit
                rec.max_favorable_atr = max_favorable_atr
                rec.max_adverse_atr   = max_adverse_atr
                rec.candles_to_close  = candles_to_close
                rec.label             = label
                rec.label_quality     = quality

            # Propagate outcome to setup_alerts linked to this alert_id.
            # update_ml_feature_outcome() bypasses auto_labeler (sets label directly),
            # so we must propagate here — auto_labeler only touches label==-1 records.
            session.query(SetupAlert).filter(
                SetupAlert.alert_id == alert_id,
                SetupAlert.label == -1,
            ).update({
                "label":         label,
                "label_quality": quality,
                "t1_hit":        t1_hit,
                "t2_hit":        t2_hit,
                "t3_hit":        t3_hit,
                "sl_hit":        sl_hit,
                "realized_pnl":  realized_pnl,
            }, synchronize_session=False)

            # Also update parent Alert outcome
            alert = session.query(AlertModel).filter(AlertModel.id == alert_id).first()
            if alert:
                alert.outcome           = outcome_str
                alert.outcome_timestamp = datetime.now()

    def update_post_close_outcome(
        self,
        outcome_id: int,
        alert_id: int,
        post_close_t1_hit: bool,
        post_close_t2_hit: bool,
        post_close_t3_hit: bool,
        post_close_max_fav_atr: float,
        post_close_max_adv_atr: float,
        post_close_eod_spot: float,
        post_sl_reversal: bool,
        post_sl_full_recovery: bool,
        t1_hit_time=None,
        t2_hit_time=None,
        t3_hit_time=None,
    ):
        """
        Write post-close monitoring results (price data after trade was closed).
        Called at EOD for every trade closed during the session.
        Also patches the ML feature record so the model learns from the full day.
        """
        with self.get_session() as session:
            row = session.query(TradeOutcome).filter(TradeOutcome.id == outcome_id).first()
            if row:
                row.post_close_t1_hit       = post_close_t1_hit
                row.post_close_t1_hit_time  = t1_hit_time
                row.post_close_t2_hit       = post_close_t2_hit
                row.post_close_t2_hit_time  = t2_hit_time
                row.post_close_t3_hit       = post_close_t3_hit
                row.post_close_t3_hit_time  = t3_hit_time
                row.post_close_max_fav_atr  = round(post_close_max_fav_atr, 3)
                row.post_close_max_adv_atr  = round(post_close_max_adv_atr, 3)
                row.post_close_eod_spot     = post_close_eod_spot
                row.post_sl_reversal        = post_sl_reversal
                row.post_sl_full_recovery   = post_sl_full_recovery

            # Patch ML feature record
            rec = session.query(MLFeatureRecord).filter(
                MLFeatureRecord.alert_id == alert_id
            ).first()
            if rec:
                rec.post_sl_reversal      = post_sl_reversal
                rec.post_sl_full_recovery = post_sl_full_recovery
                rec.post_close_max_fav_atr= round(post_close_max_fav_atr, 3)

    def get_outcome_stats(self) -> Dict[str, Any]:
        """
        Aggregate outcome statistics for alerts tab and ML reporting.
        Returns counts of SL/T1/T2/T3 hits plus average MFE/MAE.
        Single-query aggregation — replaces 9 separate COUNT/AVG queries.
        """
        from sqlalchemy import func, case
        with self.get_session() as session:
            row = session.query(
                func.count().label("total"),
                func.sum(case((TradeOutcome.sl_hit  == True, 1), else_=0)).label("sl_cnt"),   # noqa
                func.sum(case((TradeOutcome.t1_hit  == True, 1), else_=0)).label("t1_cnt"),   # noqa
                func.sum(case((TradeOutcome.t2_hit  == True, 1), else_=0)).label("t2_cnt"),   # noqa
                func.sum(case((TradeOutcome.t3_hit  == True, 1), else_=0)).label("t3_cnt"),   # noqa
                func.sum(case((TradeOutcome.outcome == "WIN",  1), else_=0)).label("wins"),
                func.sum(case((TradeOutcome.outcome == "LOSS", 1), else_=0)).label("losses"),
                func.avg(TradeOutcome.mfe_atr).label("avg_mfe"),
                func.avg(TradeOutcome.mae_atr).label("avg_mae"),
            ).filter(TradeOutcome.status == "CLOSED").one()

            total   = row.total   or 0
            sl_cnt  = row.sl_cnt  or 0
            t1_cnt  = row.t1_cnt  or 0
            t2_cnt  = row.t2_cnt  or 0
            t3_cnt  = row.t3_cnt  or 0
            wins    = row.wins    or 0
            losses  = row.losses  or 0

            return {
                "total":    total,
                "sl_count": sl_cnt,
                "t1_count": t1_cnt,
                "t2_count": t2_cnt,
                "t3_count": t3_cnt,
                "wins":     wins,
                "losses":   losses,
                "win_rate": round(wins / max(wins + losses, 1) * 100, 1),
                "t1_rate":  round(t1_cnt / max(total, 1) * 100, 1),
                "t2_rate":  round(t2_cnt / max(total, 1) * 100, 1),
                "t3_rate":  round(t3_cnt / max(total, 1) * 100, 1),
                "sl_rate":  round(sl_cnt / max(total, 1) * 100, 1),
                "avg_mfe_atr": round(row.avg_mfe or 0, 2),
                "avg_mae_atr": round(row.avg_mae or 0, 2),
            }

    def _migrate_s11_paper_trades(self):
        """Create s11_paper_trades table and indexes if they don't exist (idempotent).
        Base.metadata.create_all() handles new installs; this handles existing DBs."""
        try:
            with self.engine.connect() as conn:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS s11_paper_trades (
                        id               INTEGER PRIMARY KEY AUTOINCREMENT,
                        alert_id         INTEGER DEFAULT 0,
                        index_name       VARCHAR(20) NOT NULL,
                        direction        VARCHAR(10) NOT NULL,
                        confidence_score FLOAT  DEFAULT 0.0,
                        date             VARCHAR(12) NOT NULL,
                        entry_time       DATETIME NOT NULL,
                        entry_spot       FLOAT  DEFAULT 0.0,
                        entry_price      FLOAT  DEFAULT 0.0,
                        instrument       VARCHAR(50) DEFAULT '',
                        strike           FLOAT  DEFAULT 0.0,
                        option_type      VARCHAR(4) DEFAULT '',
                        atr_at_signal    FLOAT  DEFAULT 0.0,
                        lot_size         INTEGER DEFAULT 0,
                        lots             INTEGER DEFAULT 2,
                        units            INTEGER DEFAULT 0,
                        sl_price         FLOAT  DEFAULT 0.0,
                        t1_price         FLOAT  DEFAULT 0.0,
                        t2_price         FLOAT  DEFAULT 0.0,
                        t3_price         FLOAT  DEFAULT 0.0,
                        spot_sl          FLOAT  DEFAULT 0.0,
                        spot_t1          FLOAT  DEFAULT 0.0,
                        spot_t2          FLOAT  DEFAULT 0.0,
                        spot_t3          FLOAT  DEFAULT 0.0,
                        pnl_at_sl        FLOAT  DEFAULT 0.0,
                        pnl_at_t1        FLOAT  DEFAULT 0.0,
                        pnl_at_t2        FLOAT  DEFAULT 0.0,
                        pnl_at_t3        FLOAT  DEFAULT 0.0,
                        t1_hit           BOOLEAN DEFAULT 0,
                        t1_hit_time      DATETIME,
                        t2_hit           BOOLEAN DEFAULT 0,
                        t2_hit_time      DATETIME,
                        t3_hit           BOOLEAN DEFAULT 0,
                        t3_hit_time      DATETIME,
                        sl_hit           BOOLEAN DEFAULT 0,
                        sl_hit_time      DATETIME,
                        mfe_atr          FLOAT  DEFAULT 0.0,
                        mae_atr          FLOAT  DEFAULT 0.0,
                        status           VARCHAR(10) DEFAULT 'OPEN',
                        exit_time        DATETIME,
                        exit_price       FLOAT  DEFAULT 0.0,
                        exit_spot        FLOAT  DEFAULT 0.0,
                        exit_reason      VARCHAR(20) DEFAULT '',
                        outcome          VARCHAR(10) DEFAULT '',
                        realized_pnl     FLOAT  DEFAULT 0.0,
                        created_at       DATETIME
                    )
                """))
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS idx_s11_index_date "
                    "ON s11_paper_trades(index_name, date)"
                ))
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS idx_s11_status "
                    "ON s11_paper_trades(status)"
                ))
                conn.commit()
        except Exception as e:
            logger.warning(f"s11_paper_trades migration: {e}")

    # ─── AUTO PAPER TRADES ─────────────────────────────────────────

    def _migrate_auto_paper_trades(self):
        """Create auto_paper_trades table if it doesn't exist."""
        try:
            from database.models import AutoPaperTrade
            AutoPaperTrade.__table__.create(self.engine, checkfirst=True)
        except Exception as e:
            logger.warning(f"auto_paper_trades migration: {e}")

    def save_auto_paper_trade(self, rec: dict) -> None:
        """Insert or update an AutoPaperTrade row by order_id."""
        try:
            from database.models import AutoPaperTrade
            with self.get_session() as session:
                row = session.query(AutoPaperTrade).filter(
                    AutoPaperTrade.order_id == rec["order_id"]
                ).first()
                if row is None:
                    valid = {c.name for c in AutoPaperTrade.__table__.columns}
                    row = AutoPaperTrade(**{k: v for k, v in rec.items() if k in valid})
                    session.add(row)
                else:
                    valid = {c.name for c in AutoPaperTrade.__table__.columns}
                    for k, v in rec.items():
                        if k in valid and k != "id":
                            setattr(row, k, v)
        except Exception as e:
            logger.warning(f"save_auto_paper_trade: {e}")

    def get_auto_paper_trades_today(self, date_str: str) -> list:
        """Return all AutoPaperTrade rows for a given date (YYYY-MM-DD)."""
        try:
            from database.models import AutoPaperTrade
            with self.get_session() as session:
                rows = (
                    session.query(AutoPaperTrade)
                    .filter(AutoPaperTrade.date == date_str)
                    .order_by(AutoPaperTrade.placed_at)
                    .all()
                )
                session.expunge_all()
                return rows
        except Exception as e:
            logger.warning(f"get_auto_paper_trades_today: {e}")
            return []

    # ─── S11 PAPER TRADES ──────────────────────────────────────────

    def save_s11_paper_trade(self, data: Dict[str, Any]) -> int:
        """Insert a new S11PaperTrade row. Returns its id."""
        valid_cols = {c.name for c in S11PaperTrade.__table__.columns}
        row_data = {k: v for k, v in data.items() if k in valid_cols}
        with self.get_session() as session:
            row = S11PaperTrade(**row_data)
            session.add(row)
            session.flush()
            return row.id

    def update_s11_paper_trade(self, trade_id: int, updates: Dict[str, Any]):
        """Patch an existing S11PaperTrade row with arbitrary field updates."""
        with self.get_session() as session:
            row = session.query(S11PaperTrade).filter(
                S11PaperTrade.id == trade_id
            ).first()
            if row:
                for k, v in updates.items():
                    setattr(row, k, v)

    def get_open_s11_trades(self) -> List[S11PaperTrade]:
        """Return today's OPEN S11PaperTrade rows — used by S11Monitor on startup (rehydrate)."""
        today = datetime.now().strftime("%Y-%m-%d")
        with self.get_session() as session:
            rows = (
                session.query(S11PaperTrade)
                .filter(S11PaperTrade.status == "OPEN")
                .filter(S11PaperTrade.date == today)
                .order_by(S11PaperTrade.entry_time)
                .all()
            )
            session.expunge_all()
            return rows

    def get_s11_trades_by_date(self, date_str: str) -> List[S11PaperTrade]:
        """Return all S11PaperTrade rows for a given date string 'YYYY-MM-DD'."""
        with self.get_session() as session:
            rows = (
                session.query(S11PaperTrade)
                .filter(S11PaperTrade.date == date_str)
                .order_by(S11PaperTrade.entry_time)
                .all()
            )
            session.expunge_all()
            return rows

    def get_s11_stats(self) -> Dict[str, Any]:
        """Aggregate S11 paper trade stats: total, wins, losses, T1/T2/T3 rates, P&L."""
        from sqlalchemy import func, case
        with self.get_session() as session:
            row = session.query(
                func.count().label("total"),
                func.sum(case((S11PaperTrade.sl_hit  == True,  1), else_=0)).label("sl_cnt"),   # noqa
                func.sum(case((S11PaperTrade.t1_hit  == True,  1), else_=0)).label("t1_cnt"),   # noqa
                func.sum(case((S11PaperTrade.t2_hit  == True,  1), else_=0)).label("t2_cnt"),   # noqa
                func.sum(case((S11PaperTrade.t3_hit  == True,  1), else_=0)).label("t3_cnt"),   # noqa
                func.sum(case((S11PaperTrade.outcome == "WIN",  1), else_=0)).label("wins"),
                func.sum(case((S11PaperTrade.outcome == "LOSS", 1), else_=0)).label("losses"),
                func.sum(S11PaperTrade.realized_pnl).label("total_pnl"),
                func.avg(S11PaperTrade.mfe_atr).label("avg_mfe"),
                func.avg(S11PaperTrade.mae_atr).label("avg_mae"),
            ).filter(S11PaperTrade.status == "CLOSED").one()

            total   = row.total   or 0
            sl_cnt  = row.sl_cnt  or 0
            t1_cnt  = row.t1_cnt  or 0
            t2_cnt  = row.t2_cnt  or 0
            t3_cnt  = row.t3_cnt  or 0
            wins    = row.wins    or 0
            losses  = row.losses  or 0
            return {
                "total":     total,
                "sl_count":  sl_cnt,
                "t1_count":  t1_cnt,
                "t2_count":  t2_cnt,
                "t3_count":  t3_cnt,
                "wins":      wins,
                "losses":    losses,
                "win_rate":  round(wins / max(wins + losses, 1) * 100, 1),
                "t1_rate":   round(t1_cnt / max(total, 1) * 100, 1),
                "t2_rate":   round(t2_cnt / max(total, 1) * 100, 1),
                "t3_rate":   round(t3_cnt / max(total, 1) * 100, 1),
                "sl_rate":   round(sl_cnt / max(total, 1) * 100, 1),
                "total_pnl": round(float(row.total_pnl or 0), 2),
                "avg_mfe_atr": round(float(row.avg_mfe or 0), 2),
                "avg_mae_atr": round(float(row.avg_mae or 0), 2),
            }

    # ─── LIFECYCLE ────────────────────────────────────────────────

    def close(self):
        """
        Flush the WAL to the main DB file and dispose the engine pool.
        Call on clean application shutdown so no data is left in the WAL.
        Without this, SQLite WAL accumulates indefinitely when the process
        is stopped without a checkpoint (e.g. window closed, SIGTERM).
        """
        try:
            with self.engine.connect() as conn:
                conn.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
                conn.commit()
            logger.info("WAL checkpoint complete")
        except Exception as e:
            logger.warning(f"WAL checkpoint failed (non-fatal): {e}")
        try:
            self.engine.dispose()
        except Exception:
            pass

    # ─── RETENTION / PURGE ────────────────────────────────────────

    def purge_old_data(self) -> Dict[str, int]:
        """
        Delete rows older than configured retention windows.
        Safe to call on startup and once per trading day.
        Returns counts of deleted rows per table.
        """
        now = datetime.now()
        cutoffs = {
            "option_chain_snapshots": now - timedelta(days=config.OC_RETENTION_DAYS),
            "engine_signals":         now - timedelta(days=config.ENGINE_SIGNAL_RETENTION_DAYS),
            "market_candles":         now - timedelta(days=config.CANDLE_RETENTION_DAYS),
            "option_eod_prices":      now - timedelta(days=config.OPTION_EOD_RETENTION_DAYS),
            "option_price_history":   now - timedelta(days=config.OPTION_PRICE_HISTORY_RETENTION_DAYS),
            "alerts":                 now - timedelta(days=config.ALERT_RETENTION_DAYS),
            "ml_feature_store":       now - timedelta(days=config.ML_FEATURE_RETENTION_DAYS),
            "trade_outcomes":         now - timedelta(days=config.TRADE_OUTCOME_RETENTION_DAYS),
        }
        deleted = {}
        table_ts_col = {
            "option_chain_snapshots": "timestamp",
            "engine_signals":         "timestamp",
            "market_candles":         "timestamp",
            "option_eod_prices":      "timestamp",
            "option_price_history":   "created_at",
            "alerts":                 "timestamp",
            "ml_feature_store":       "created_at",
            "trade_outcomes":         "entry_time",
        }
        try:
            with self.engine.connect() as conn:
                for table, cutoff in cutoffs.items():
                    ts_col = table_ts_col[table]
                    result = conn.execute(
                        text(f"DELETE FROM {table} WHERE {ts_col} < :cutoff"),
                        {"cutoff": cutoff}
                    )
                    deleted[table] = result.rowcount
                conn.commit()
            logger.info(
                f"DB purge complete: "
                + ", ".join(f"{t}={n}" for t, n in deleted.items())
            )
        except Exception as e:
            logger.error(f"DB purge error: {e}")
        return deleted

    # ─── STATS ─────────────────────────────────────────────────────

    def get_alert_stats(self) -> Dict[str, Any]:
        from sqlalchemy import func, case
        with self.get_session() as session:
            today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            row = session.query(
                func.count().label("total"),
                func.sum(case((Alert.outcome == "WIN",  1), else_=0)).label("wins"),
                func.sum(case((Alert.outcome == "LOSS", 1), else_=0)).label("losses"),
                func.sum(case((Alert.timestamp >= today, 1), else_=0)).label("today"),
            ).one()
            total  = row.total  or 0
            wins   = row.wins   or 0
            losses = row.losses or 0
            return {
                "total":    total,
                "wins":     wins,
                "losses":   losses,
                "today":    row.today or 0,
                "win_rate": round(wins / max(wins + losses, 1) * 100, 1),
            }


# Global singleton (thread-safe initialization)
_db: Optional[DatabaseManager] = None
_db_lock = __import__("threading").Lock()


def get_db() -> DatabaseManager:
    global _db
    if _db is None:
        with _db_lock:
            if _db is None:  # double-checked locking
                _db = DatabaseManager()
    return _db
