"""
ml/options_feature_engine.py
────────────────────────────────────────────────────────────────────
Options Data → ML Features Conversion

Extracts options chain data (price, OI, volume, IV, Greeks) from daily
option_eod_prices and option_chain_snapshots tables and converts into
ML training features.

Features extracted:
  • IV percentile (ATM IV vs 20-day range)
  • OI imbalance (Call OI - Put OI)
  • Max Pain proximity
  • Greeks aggregates (delta, gamma, theta weighted by OI)
  • Volatility skew (Call IV - Put IV)
  • PCR (Put-Call Ratio)
"""

import logging
import math
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
import numpy as np
import pandas as pd

import config
from database.manager import get_db

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────
# OPTIONS FEATURE COLUMNS
# ──────────────────────────────────────────────────────────────────

OPTIONS_FEATURE_COLUMNS = [
    # Volatility Context
    "atm_iv",                 # ATM (spot ± 50) IV (%)
    "iv_percentile",          # IV vs 20-day range (0-100)
    "call_iv_skew",           # Call IV - Put IV (skew direction)
    "iv_smile",               # Max(ITM, OTM) IV - ATM IV
    
    # OI Context
    "call_oi",                # Total call OI
    "put_oi",                 # Total put OI
    "pcr",                    # Put-Call Ratio (PUT OI / CALL OI)
    "pcr_volume",             # PCR by volume (PUT VOL / CALL VOL)
    "oi_imbalance",           # (CALL OI - PUT OI) / (CALL OI + PUT OI)
    
    # Greeks Aggregate (OI-weighted)
    "delta_aggregate",        # OI-weighted delta (call - put, bearish = negative)
    "gamma_aggregate",        # Total gamma (OI-weighted)
    "theta_aggregate",        # Total theta per day (OI-weighted, usually negative)
    "max_gamma_strike",       # Strike with max gamma (volatility peak)
    
    # Price Context
    "max_pain",               # Market maker max pain level
    "price_to_max_pain",      # (Spot - Max Pain) / ATR %
    "atm_volume",             # Average volume in ATM strikes
    
    # Setup Strength (0-1)
    "options_setup_strength", # Composite (OI imbalance + IV expansion + gamma = strong)
]

# Combine with main FEATURE_COLUMNS
FEATURE_COLUMNS_WITH_OPTIONS = [
    # ...existing main features...
    # (Will be combined at load time in feature_store.py)
] + OPTIONS_FEATURE_COLUMNS


# ──────────────────────────────────────────────────────────────────
# OPTIONS SNAPSHOT AGGREGATOR
# ──────────────────────────────────────────────────────────────────

class OptionsSnapshotAggregator:
    """
    Loads option chain snapshot and computes ML-ready features.
    """
    
    def __init__(self, db=None):
        self._db = db or get_db()
    
    def compute_features_for_timestamp(
        self,
        index_name: str,
        timestamp: datetime
    ) -> Dict[str, float]:
        """
        Load snapshot at exact timestamp and compute options features.
        Returns dict with all OPTIONS_FEATURE_COLUMNS populated.
        """
        try:
            snap = self._get_snapshot(index_name, timestamp)
            if not snap:
                return self._zero_features()
            
            return self._compute_from_snapshot(snap, index_name, timestamp)
        except Exception as e:
            logger.debug(f"Options features error [{index_name} @ {timestamp}]: {e}")
            return self._zero_features()
    
    def _get_snapshot(self, idx: str, ts: datetime) -> Optional[Dict]:
        """Fetch closest snapshot at or before given timestamp."""
        try:
            with self._db.engine.connect() as conn:
                from sqlalchemy import text
                row = conn.execute(text(
                    "SELECT id, spot_price, atm_strike, total_call_oi, total_put_oi, "
                    "pcr, pcr_volume, max_pain, avg_atm_iv, chain_data "
                    "FROM option_chain_snapshots "
                    "WHERE index_name=:i AND timestamp <= :ts "
                    "ORDER BY timestamp DESC LIMIT 1"
                ), {"i": idx, "ts": ts}).fetchone()
            
            if not row:
                return None
            
            return {
                "snap_id": row[0],
                "spot": float(row[1]),
                "atm": float(row[2]),
                "call_oi": float(row[3]),
                "put_oi": float(row[4]),
                "pcr": float(row[5]),
                "pcr_volume": float(row[6]),
                "max_pain": float(row[7]),
                "avg_atm_iv": float(row[8]),
                "chain_data": row[9],  # JSON string
            }
        except Exception as e:
            logger.debug(f"_get_snapshot error: {e}")
            return None
    
    def _compute_from_snapshot(
        self,
        snap: Dict,
        idx: str,
        ts: datetime
    ) -> Dict[str, float]:
        """Extract all options features from snapshot."""
        import json
        
        result = {}
        call_oi = snap.get("call_oi") or 0
        put_oi = snap.get("put_oi") or 0
        spot = snap.get("spot") or 0
        atm = snap.get("atm") or 0
        pcr = snap.get("pcr") or 0
        max_pain = snap.get("max_pain") or 0
        avg_iv = snap.get("avg_atm_iv") or 15
        
        # Parse chain_data JSON
        try:
            chain_json = snap.get("chain_data", "[]")
            if isinstance(chain_json, str):
                chain = json.loads(chain_json) if chain_json else []
            else:
                chain = chain_json or []
        except Exception:
            chain = []
        
        # ── IV Analysis ──────────────────────────────────────────
        result["atm_iv"] = avg_iv  # Already in DB
        result["iv_percentile"] = self._compute_iv_percentile(idx, avg_iv)
        
        # IV skew: call_iv - put_iv for ATM strikes
        call_ivs = []
        put_ivs = []
        atm_volume_sum = 0
        max_gamma = 0
        max_gamma_strike = atm
        
        for s in chain:
            strike = float(s.get("strike", 0))
            call_iv = float(s.get("call_iv", 0))
            put_iv = float(s.get("put_iv", 0))
            call_vol = float(s.get("call_volume", 0))
            put_vol = float(s.get("put_volume", 0))
            call_gamma = float(s.get("call_gamma", 0))
            put_gamma = float(s.get("put_gamma", 0))
            
            # ATM ± 50 bands for IV aggregates
            if abs(strike - atm) <= 50:
                if call_iv > 0:
                    call_ivs.append(call_iv)
                if put_iv > 0:
                    put_ivs.append(put_iv)
                atm_volume_sum += call_vol + put_vol
            
            # Max gamma strike
            total_gamma = call_gamma + put_gamma
            if total_gamma > max_gamma:
                max_gamma = total_gamma
                max_gamma_strike = strike
        
        avg_call_iv = np.mean(call_ivs) if call_ivs else 15
        avg_put_iv = np.mean(put_ivs) if put_ivs else 15
        result["call_iv_skew"] = avg_call_iv - avg_put_iv
        result["iv_smile"] = max(avg_call_iv, avg_put_iv) - avg_iv if avg_iv > 0 else 0
        
        # ── OI Context ───────────────────────────────────────────
        result["call_oi"] = call_oi
        result["put_oi"] = put_oi
        result["pcr"] = pcr
        result["pcr_volume"] = snap.get("pcr_volume", 0) or 0
        
        # OI imbalance: normalized (-1 to +1, negative = more call OI = bullish)
        total_oi = call_oi + put_oi
        result["oi_imbalance"] = (
            (call_oi - put_oi) / total_oi if total_oi > 0 else 0
        )  # Negative = bullish (call heavy), positive = bearish (put heavy)
        
        # ── Greeks Aggregate ─────────────────────────────────────
        delta_agg = 0
        gamma_agg = 0
        theta_agg = 0
        
        for s in chain:
            call_oi_s = float(s.get("call_oi", 0))
            put_oi_s = float(s.get("put_oi", 0))
            call_delta = float(s.get("call_delta", 0))
            put_delta = float(s.get("put_delta", 0))
            call_gamma = float(s.get("call_gamma", 0))
            put_gamma = float(s.get("put_gamma", 0))
            call_theta = float(s.get("call_theta", 0))
            put_theta = float(s.get("put_theta", 0))
            
            # OI-weighted Greeks
            if call_oi_s > 0:
                delta_agg += call_delta * call_oi_s
                gamma_agg += call_gamma * call_oi_s
                theta_agg += call_theta * call_oi_s
            if put_oi_s > 0:
                delta_agg += put_delta * put_oi_s  # put delta is negative
                gamma_agg += put_gamma * put_oi_s
                theta_agg += put_theta * put_oi_s
        
        # Normalize by total OI
        if total_oi > 0:
            result["delta_aggregate"] = delta_agg / total_oi / 100  # Scale down
            result["gamma_aggregate"] = gamma_agg / total_oi / 100000  # Very small
            result["theta_aggregate"] = theta_agg / total_oi  # Per day
        else:
            result["delta_aggregate"] = 0
            result["gamma_aggregate"] = 0
            result["theta_aggregate"] = 0
        
        result["max_gamma_strike"] = max_gamma_strike
        
        # ── Price Context ────────────────────────────────────────
        result["max_pain"] = max_pain
        if spot > 0 and max_pain > 0:
            dist_pct = ((spot - max_pain) / max_pain) * 100
            result["price_to_max_pain"] = dist_pct
        else:
            result["price_to_max_pain"] = 0
        
        result["atm_volume"] = atm_volume_sum / 2 if atm_volume_sum > 0 else 0  # average
        
        # ── Setup Strength ───────────────────────────────────────
        # Composite score: OI imbalance strength + IV expansion + Gamma concentration
        oi_strength = abs(result["oi_imbalance"])  # 0-1, higher = more directional bias
        iv_expansion = min(1.0, (result["call_iv_skew"] + 50) / 100)  # Normalized skew
        gamma_strength = min(1.0, max_gamma / 1000000) if max_gamma > 0 else 0
        
        result["options_setup_strength"] = (oi_strength * 0.5 + iv_expansion * 0.25 + gamma_strength * 0.25)
        
        return result
    
    def _compute_iv_percentile(self, idx: str, current_iv: float) -> float:
        """
        Compute IV percentile (0-100) vs 20-day IV range for index.
        Returns 0-100 where 0 = lowest IV in range, 100 = highest.
        """
        try:
            lookback_days = 20
            date_from = (datetime.now() - timedelta(days=lookback_days)).date()
            
            with self._db.engine.connect() as conn:
                from sqlalchemy import text
                rows = conn.execute(text(
                    "SELECT avg_atm_iv FROM option_chain_snapshots "
                    "WHERE index_name=:i AND DATE(timestamp) >= :d "
                    "ORDER BY timestamp ASC"
                ), {"i": idx, "d": date_from}).fetchall()
            
            if not rows:
                return 50
            
            ivs = [float(r[0]) for r in rows if r[0] is not None and r[0] > 0]
            if not ivs or len(ivs) < 5:
                return 50
            
            min_iv = np.percentile(ivs, 10)
            max_iv = np.percentile(ivs, 90)
            
            if max_iv <= min_iv:
                return 50
            
            pct = ((current_iv - min_iv) / (max_iv - min_iv)) * 100
            return max(0, min(100, pct))
        except Exception as e:
            logger.debug(f"_compute_iv_percentile error: {e}")
            return 50
    
    def _zero_features(self) -> Dict[str, float]:
        """Return zeroed dict for all options features."""
        return {col: 0.0 for col in OPTIONS_FEATURE_COLUMNS}


# ──────────────────────────────────────────────────────────────────
# DAILY OPTIONS DATA EXPORT
# ──────────────────────────────────────────────────────────────────

def export_daily_options_data(date_str: Optional[str] = None) -> Dict[str, Any]:
    """
    Export all options data collected on a given date to CSV + JSON.
    Returns summary dict with file paths and record counts.
    
    Usage:
        export_daily_options_data("2026-04-02")  # specific date
        export_daily_options_data()              # today
    """
    from pathlib import Path
    import json
    from sqlalchemy import text
    
    db = get_db()
    date_str = date_str or datetime.now().date().isoformat()
    
    export_dir = Path(config.LOG_DIR) / "options_data_exports"
    export_dir.mkdir(exist_ok=True, parents=True)
    
    result = {
        "date": date_str,
        "exports": {},
        "total_eod_rows": 0,
        "total_snapshot_rows": 0,
    }
    
    try:
        # ── Export EOD Prices ────────────────────────────────────
        with db.engine.connect() as conn:
            eod_rows = conn.execute(text(
                "SELECT index_name, timestamp, strike, expiry, spot_price, "
                "call_ltp, call_oi, call_iv, call_volume, "
                "call_delta, call_gamma, call_theta, call_vega, "
                "put_ltp, put_oi, put_iv, put_volume, "
                "put_delta, put_gamma, put_theta, put_vega "
                "FROM option_eod_prices "
                "WHERE DATE(timestamp)=:d "
                "ORDER BY timestamp, index_name, strike"
            ), {"d": date_str}).fetchall()
        
        if eod_rows:
            eod_df = pd.DataFrame(
                eod_rows,
                columns=[
                    "index", "timestamp", "strike", "expiry", "spot",
                    "call_price", "call_oi", "call_iv", "call_vol",
                    "call_delta", "call_gamma", "call_theta", "call_vega",
                    "put_price", "put_oi", "put_iv", "put_vol",
                    "put_delta", "put_gamma", "put_theta", "put_vega"
                ]
            )
            
            eod_csv = export_dir / f"options_eod_{date_str}.csv"
            eod_df.to_csv(eod_csv, index=False)
            
            result["exports"]["eod_prices_csv"] = str(eod_csv)
            result["total_eod_rows"] = len(eod_rows)
            logger.info(f"Exported {len(eod_rows)} EOD price rows → {eod_csv}")
        
        # ── Export Snapshots ─────────────────────────────────────
        with db.engine.connect() as conn:
            snap_rows = conn.execute(text(
                "SELECT index_name, timestamp, spot_price, atm_strike, "
                "total_call_oi, total_put_oi, pcr, pcr_volume, max_pain, "
                "avg_atm_iv, iv_rank, chain_data "
                "FROM option_chain_snapshots "
                "WHERE DATE(timestamp)=:d "
                "ORDER BY timestamp, index_name"
            ), {"d": date_str}).fetchall()
        
        if snap_rows:
            snap_df = pd.DataFrame(
                snap_rows,
                columns=[
                    "index", "timestamp", "spot", "atm", 
                    "call_oi", "put_oi", "pcr", "pcr_volume", "max_pain",
                    "avg_iv", "iv_rank", "chain_data"
                ]
            )
            
            snap_csv = export_dir / f"options_snapshots_{date_str}.csv"
            snap_df.to_csv(snap_csv, index=False)
            
            result["exports"]["snapshots_csv"] = str(snap_csv)
            result["total_snapshot_rows"] = len(snap_rows)
            logger.info(f"Exported {len(snap_rows)} snapshot rows → {snap_csv}")
        
        # ── Export ML-ready Features ─────────────────────────────
        agg = OptionsSnapshotAggregator(db)
        ml_features = []
        
        for idx in config.INDICES:
            # Get all unique timestamps for this index
            with db.engine.connect() as conn:
                ts_rows = conn.execute(text(
                    "SELECT DISTINCT timestamp FROM option_chain_snapshots "
                    "WHERE index_name=:i AND DATE(timestamp)=:d "
                    "ORDER BY timestamp"
                ), {"i": idx, "d": date_str}).fetchall()
            
            for (ts,) in ts_rows:
                feat = agg.compute_features_for_timestamp(idx, ts)
                feat["index"] = idx
                feat["timestamp"] = ts
                ml_features.append(feat)
        
        if ml_features:
            ml_df = pd.DataFrame(ml_features)
            ml_csv = export_dir / f"options_ml_features_{date_str}.csv"
            ml_df.to_csv(ml_csv, index=False)
            
            result["exports"]["ml_features_csv"] = str(ml_csv)
            result["total_ml_feature_rows"] = len(ml_features)
            logger.info(f"Exported {len(ml_features)} ML feature rows → {ml_csv}")
        
        # ── Write summary ────────────────────────────────────────
        summary_file = export_dir / f"export_summary_{date_str}.json"
        with open(summary_file, "w") as f:
            json.dump(result, f, indent=2, default=str)
        
        result["summary_file"] = str(summary_file)
        logger.info(f"\nOptions data export complete [{date_str}]:")
        logger.info(f"  EOD Prices:    {result['total_eod_rows']} rows")
        logger.info(f"  Snapshots:     {result['total_snapshot_rows']} rows")
        logger.info(f"  ML Features:   {result.get('total_ml_feature_rows', 0)} rows")
        logger.info(f"  Output Dir:    {export_dir}")
        
        return result
    
    except Exception as e:
        logger.error(f"Export failed: {e}", exc_info=True)
        result["error"] = str(e)
        return result


# ──────────────────────────────────────────────────────────────────
# STANDALONE EXPORT TRIGGER
# ──────────────────────────────────────────────────────────────────

def schedule_daily_options_export(hour: int = 15, minute: int = 36):
    """
    Schedule daily options data export at HH:MM local time (default 15:36 IST = post-market).
    Non-blocking — uses threading.Timer; reschedules itself each day.
    """
    import threading
    from datetime import datetime, timedelta
    
    def _seconds_until(h: int, m: int) -> float:
        """Seconds until next occurrence of HH:MM (local time)."""
        now = datetime.now()
        next_run = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)
        return (next_run - now).total_seconds()
    
    def _run_and_reschedule():
        try:
            logger.info("Running daily options data export...")
            result = export_daily_options_data()
            if "error" not in result:
                logger.info(
                    f"Options export done: "
                    f"{result['total_eod_rows']} EOD + "
                    f"{result['total_snapshot_rows']} snapshots + "
                    f"{result.get('total_ml_feature_rows', 0)} ML features"
                )
            else:
                logger.error(f"Options export error: {result['error']}")
        except Exception as e:
            logger.error(f"Options export failed: {e}", exc_info=False)
        
        # Reschedule for next day
        schedule_daily_options_export(hour, minute)
    
    delay = _seconds_until(hour, minute)
    t = threading.Timer(delay, _run_and_reschedule)
    t.daemon = True
    t.name = "DailyOptionsExportTimer"
    t.start()
    logger.info(
        f"Daily options export scheduled at {hour:02d}:{minute:02d} "
        f"(in {delay/3600:.1f}h)"
    )


if __name__ == "__main__":
    import sys
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
    )
    
    date_arg = sys.argv[1] if len(sys.argv) > 1 else None
    result = export_daily_options_data(date_arg)
    print(f"\n{'='*60}")
    print(f"Export completed: {result.get('summary_file', 'N/A')}")
    print(f"{'='*60}")
