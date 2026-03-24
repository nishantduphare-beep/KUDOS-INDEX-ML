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
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session


def _sanitize_for_json(obj):
    """Recursively convert numpy types to native Python for JSON serialization."""
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_for_json(v) for v in obj]
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj

from database.models import (
    Base, MarketCandle, OptionChainSnapshot,
    EngineSignal, Alert, TradeOutcome, MLFeatureRecord
)
import config

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Thread-safe SQLite database manager."""

    def __init__(self, db_path: str = config.DB_PATH):
        self.engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False},
            echo=config.DB_ECHO
        )
        self.SessionLocal = sessionmaker(
            autocommit=False, autoflush=False, bind=self.engine
        )
        self._init_db()

    def _init_db(self):
        """Create all tables if they don't exist, then migrate new columns."""
        Base.metadata.create_all(bind=self.engine)
        self._migrate_ml_feature_store()
        self._migrate_market_candles()
        self._migrate_trade_outcomes()
        self._migrate_ml_feature_outcomes()
        self._migrate_alerts()
        self._migrate_indexes()
        logger.info("Database initialized")

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
        ]
        try:
            with self.engine.connect() as conn:
                for sql in indexes:
                    conn.execute(text(sql))
                conn.commit()
        except Exception as e:
            logger.warning(f"Index migration: {e}")

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
            ref_date = datetime.utcnow().date()
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
        since = datetime.utcnow() - timedelta(minutes=since_minutes)
        with self.get_session() as session:
            return (
                session.query(EngineSignal)
                .filter(
                    EngineSignal.index_name == index_name,
                    EngineSignal.timestamp >= since
                )
                .order_by(EngineSignal.timestamp.desc())
                .all()
            )

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
                alert.outcome_timestamp = datetime.utcnow()

    # ─── OPTION PRICE HISTORY ──────────────────────────────────────

    def save_option_price(self, alert_id: int, instrument: str, timestamp,
                          ltp: float, entry_price: float, candle_num: int):
        """Store one option LTP data point for a tracked signal."""
        from database.models import OptionPriceHistory
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
        from database.models import OptionPriceHistory
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
        from database.models import OptionPriceHistory
        from sqlalchemy import and_
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

        outcome_str = "WIN" if label == 1 else "LOSS"

        with self.get_session() as session:
            from database.models import MLFeatureRecord, Alert as AlertModel
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

            # Also update parent Alert outcome
            alert = session.query(AlertModel).filter(AlertModel.id == alert_id).first()
            if alert:
                alert.outcome           = outcome_str
                alert.outcome_timestamp = datetime.utcnow()

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
            from database.models import MLFeatureRecord
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

    # ─── RETENTION / PURGE ────────────────────────────────────────

    def purge_old_data(self) -> Dict[str, int]:
        """
        Delete rows older than configured retention windows.
        Safe to call on startup and once per trading day.
        Returns counts of deleted rows per table.
        """
        now = datetime.utcnow()
        cutoffs = {
            "option_chain_snapshots": now - timedelta(days=config.OC_RETENTION_DAYS),
            "engine_signals":         now - timedelta(days=config.ENGINE_SIGNAL_RETENTION_DAYS),
            "market_candles":         now - timedelta(days=config.CANDLE_RETENTION_DAYS),
        }
        deleted = {}
        table_ts_col = {
            "option_chain_snapshots": "timestamp",
            "engine_signals":         "timestamp",
            "market_candles":         "timestamp",
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
            today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
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


# Global singleton
_db: Optional[DatabaseManager] = None


def get_db() -> DatabaseManager:
    global _db
    if _db is None:
        _db = DatabaseManager()
    return _db
