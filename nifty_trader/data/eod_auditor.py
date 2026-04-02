"""
data/eod_auditor.py
──────────────────────────────────────────────────────────────────────
End-of-Day Options Data Auditor

Runs at 15:31 IST (triggered from data_manager tick loop) to:

  Phase 1 — Audit
    • Count option_eod_prices rows vs expected (375 min × 31 strikes)
    • Identify timestamps with no coverage (app was down / fetch failed)
    • Count rows where IV=0 despite LTP>0  (scipy root-find failed)
    • Count rows where Greeks=0 despite IV>0 (greeks compute failed)
    • Count option_chain_snapshots with missing avg_atm_iv / iv_rank

  Phase 2 — In-DB repairs  (no API calls, pure recompute)
    • Recompute IV  from stored LTP + spot + strike + expiry
    • Recompute Greeks from stored IV + spot + strike + expiry
    • Recompute avg_atm_iv from stored chain_data JSON in snapshots
    • Recompute iv_rank from avg_atm_iv history in DB

  Phase 3 — Broker backfill  (Fyers 1-min history API)
    • For each missing timestamp window (entire minute with 0 strikes):
      - Fetch 1-min OHLCV for every ATM±15 CE/PE contract for the day
      - Extract the missing minute's close price as option LTP
      - Compute IV + Greeks and INSERT new option_eod_prices rows
    • Limited to 60 missing timestamps (1 hr) to cap API call volume

  Phase 4 — Final report
    • Returns a structured dict with counts and status per index

Usage (automatic):
    # Triggered from DataManager at 15:31 IST
    auditor = EODOptionsAuditor(db, adapter)
    report  = auditor.run()

Usage (manual):
    from data.eod_auditor import EODOptionsAuditor
    from database.manager import DatabaseManager
    report = EODOptionsAuditor(DatabaseManager()).run()
"""

import json
import logging
import math
import time
from datetime import datetime, date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text

import config
from database.manager import DatabaseManager
from data.bs_utils import bs_iv as _bs_iv, bs_greeks as _bs_greeks

logger = logging.getLogger(__name__)

_IST  = config.IST
_RATE = 0.065          # India risk-free rate (repo rate ~6.5%)

# Trading-session minute boundaries (inclusive)
_SESSION_START_MIN = 9 * 60 + 15    # 09:15
_SESSION_END_MIN   = 15 * 60 + 29   # 15:29
_TRADING_MINUTES   = _SESSION_END_MIN - _SESSION_START_MIN + 1   # 375
_STRIKES_PER_TS    = 31             # ATM −15 … ATM +15

_MONTH_MAP = {m: i + 1 for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
     "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
)}


# ──────────────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────────────

def _parse_expiry_date(expiry_str: str) -> Optional[date]:
    """
    Parse Fyers expiry string to a date object.
    Handles:
      "30-03-2025"  → DD-MM-YYYY
      "30MAR2025"   → DDMMMYYYY
    Returns None on parse failure.
    """
    if not expiry_str:
        return None
    try:
        s = expiry_str.strip()
        if len(s) >= 10 and s[2] == "-":
            return date(int(s[6:10]), int(s[3:5]), int(s[0:2]))
        if len(s) >= 9 and s[2:5].isalpha():
            mo = _MONTH_MAP.get(s[2:5].upper(), 0)
            if mo:
                return date(int(s[5:9]), mo, int(s[0:2]))
    except Exception:
        pass
    return None


def _tte(expiry_str: str, ts: datetime) -> float:
    """Time-to-expiry in years from the given timestamp."""
    exp = _parse_expiry_date(expiry_str)
    if exp is None:
        return 0.0
    ref  = ts.date() if hasattr(ts, "date") else ts
    days = max(0, (exp - ref).days)
    return max(0.0001, days / 365.0)


def _chunks(lst: list, n: int):
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


# ──────────────────────────────────────────────────────────────────────
# MAIN AUDITOR
# ──────────────────────────────────────────────────────────────────────

class EODOptionsAuditor:
    """
    Audits and repairs options data for the current trading day.
    Designed to run once after 15:30 IST.
    """

    def __init__(self, db: DatabaseManager, adapter=None):
        self._db      = db
        self._adapter = adapter          # FyersAdapter (or any broker adapter)
        self._today   = date.today().isoformat()   # "YYYY-MM-DD"
        self._report: Dict[str, Any] = {
            "date":         self._today,
            "indices":      {},
            "total_issues": 0,
            "status":       "PENDING",
            "completed_at": None,
        }

    # ──────────────────────────────────────────────────────────────
    # PUBLIC ENTRY POINT
    # ──────────────────────────────────────────────────────────────

    def run(self) -> Dict[str, Any]:
        """
        Execute full audit → repair → report cycle.
        Returns the report dict (also stored in self._report).
        """
        logger.info(f"EOD Audit starting [{self._today}]")
        total_issues = 0

        for idx in config.INDICES:
            try:
                idx_report = self._audit_index(idx)
                self._report["indices"][idx] = idx_report
                total_issues += idx_report.get("issues_found", 0)
            except Exception as e:
                logger.error(f"EOD Audit [{idx}] fatal: {e}", exc_info=True)
                self._report["indices"][idx] = {"error": str(e)}

        self._report["total_issues"] = total_issues
        self._report["status"]       = "CLEAN" if total_issues == 0 else "REPAIRED"
        self._report["completed_at"] = datetime.now(_IST).isoformat()

        self._log_report()
        return self._report

    # ──────────────────────────────────────────────────────────────
    # PER-INDEX ORCHESTRATION
    # ──────────────────────────────────────────────────────────────

    def _audit_index(self, idx: str) -> Dict[str, Any]:
        report: Dict[str, Any] = {"index": idx, "issues_found": 0,
                                   "eod_prices": {}, "chain_snapshots": {}}

        # ── Phase 1: audit what exists ────────────────────────────
        eod_audit  = self._audit_eod_prices(idx)
        snap_audit = self._audit_snapshots(idx)
        report["eod_prices"]      = eod_audit
        report["chain_snapshots"] = snap_audit

        issues = (
            eod_audit.get("zero_iv_rows",       0) +
            eod_audit.get("zero_greeks_rows",    0) +
            eod_audit.get("missing_count",       0) +
            snap_audit.get("zero_avg_atm_iv",    0) +
            snap_audit.get("zero_iv_rank",       0)
        )

        # ── Phase 2: in-DB repairs ────────────────────────────────
        eod_audit["repaired_iv"]     = self._repair_iv(idx)
        eod_audit["repaired_greeks"] = self._repair_greeks(idx)

        snap_audit["repaired_avg_iv"] = (
            self._repair_snapshot_avg_iv(idx)
            if snap_audit.get("zero_avg_atm_iv", 0) > 0 else 0
        )
        snap_audit["repaired_iv_rank"] = (
            self._repair_snapshot_iv_rank(idx)
            if snap_audit.get("zero_iv_rank", 0) > 0 else 0
        )

        # ── Phase 3: broker backfill ──────────────────────────────
        missing_ts = eod_audit.get("missing_timestamps", [])
        eod_audit["backfilled_rows"] = (
            self._backfill_missing(idx, missing_ts)
            if missing_ts else 0
        )

        report["issues_found"] = issues
        return report

    # ──────────────────────────────────────────────────────────────
    # PHASE 1 — AUDIT
    # ──────────────────────────────────────────────────────────────

    def _audit_eod_prices(self, idx: str) -> Dict[str, Any]:
        """
        Check option_eod_prices coverage for today.
        Returns metrics + list of missing 1-min timestamp strings.
        """
        try:
            with self._db.engine.connect() as conn:

                # Total rows collected today (primary expiry only)
                total = conn.execute(text(
                    "SELECT COUNT(*) FROM option_eod_prices "
                    "WHERE index_name=:i AND DATE(timestamp)=:d "
                    "AND (is_next_expiry IS NULL OR is_next_expiry=0)"
                ), {"i": idx, "d": self._today}).scalar() or 0

                # Next-expiry rows
                total_next = conn.execute(text(
                    "SELECT COUNT(*) FROM option_eod_prices "
                    "WHERE index_name=:i AND DATE(timestamp)=:d "
                    "AND is_next_expiry=1"
                ), {"i": idx, "d": self._today}).scalar() or 0

                # Distinct minutes present (primary)
                ts_rows = conn.execute(text(
                    "SELECT DISTINCT strftime('%Y-%m-%dT%H:%M', timestamp) "
                    "FROM option_eod_prices "
                    "WHERE index_name=:i AND DATE(timestamp)=:d "
                    "AND (is_next_expiry IS NULL OR is_next_expiry=0)"
                ), {"i": idx, "d": self._today}).fetchall()

                # Zero IV where LTP > 0  (primary only)
                zero_iv = conn.execute(text(
                    "SELECT COUNT(*) FROM option_eod_prices "
                    "WHERE index_name=:i AND DATE(timestamp)=:d "
                    "AND (is_next_expiry IS NULL OR is_next_expiry=0) "
                    "AND ( (call_iv=0 AND call_ltp>0) "
                    "   OR (put_iv=0  AND put_ltp>0) )"
                ), {"i": idx, "d": self._today}).scalar() or 0

                # Zero Greeks where IV > 0  (primary only)
                zero_greeks = conn.execute(text(
                    "SELECT COUNT(*) FROM option_eod_prices "
                    "WHERE index_name=:i AND DATE(timestamp)=:d "
                    "AND (is_next_expiry IS NULL OR is_next_expiry=0) "
                    "AND delta_call=0 AND call_iv>0"
                ), {"i": idx, "d": self._today}).scalar() or 0

            present_min = {r[0] for r in ts_rows}
            expected    = self._expected_timestamps()
            missing     = sorted(expected - present_min)

            expected_rows = _TRADING_MINUTES * _STRIKES_PER_TS
            coverage      = round(min(100.0, total / max(expected_rows, 1) * 100), 1)

            logger.info(
                f"[{idx}] EOD prices — "
                f"primary: {total}/{expected_rows} ({coverage}%), "
                f"next_expiry: {total_next}, "
                f"missing_ts: {len(missing)}, "
                f"zero_iv: {zero_iv}, zero_greeks: {zero_greeks}"
            )
            return {
                "total_rows":         total,
                "total_next_expiry":  total_next,
                "expected_rows":      expected_rows,
                "coverage_pct":       coverage,
                "missing_timestamps": missing,
                "missing_count":      len(missing),
                "zero_iv_rows":       zero_iv,
                "zero_greeks_rows":   zero_greeks,
            }
        except Exception as e:
            logger.error(f"_audit_eod_prices [{idx}]: {e}")
            return {"error": str(e), "missing_timestamps": [], "missing_count": 0}

    def _audit_snapshots(self, idx: str) -> Dict[str, Any]:
        """Check option_chain_snapshots coverage for today."""
        try:
            s = f"{self._today} 00:00:00"
            e = f"{self._today} 23:59:59"
            with self._db.engine.connect() as conn:
                total = conn.execute(text(
                    "SELECT COUNT(*) FROM option_chain_snapshots "
                    "WHERE index_name=:i AND timestamp BETWEEN :s AND :e"
                ), {"i": idx, "s": s, "e": e}).scalar() or 0

                zero_avg = conn.execute(text(
                    "SELECT COUNT(*) FROM option_chain_snapshots "
                    "WHERE index_name=:i AND timestamp BETWEEN :s AND :e "
                    "AND (avg_atm_iv IS NULL OR avg_atm_iv=0)"
                ), {"i": idx, "s": s, "e": e}).scalar() or 0

                zero_rank = conn.execute(text(
                    "SELECT COUNT(*) FROM option_chain_snapshots "
                    "WHERE index_name=:i AND timestamp BETWEEN :s AND :e "
                    "AND (iv_rank IS NULL OR iv_rank=0)"
                ), {"i": idx, "s": s, "e": e}).scalar() or 0

            # ~1 snapshot every 15 s for 375 min = ~1500 snapshots
            expected = 1500
            coverage = round(min(100.0, total / max(expected, 1) * 100), 1)

            logger.info(
                f"[{idx}] Snapshots — "
                f"{total}/{expected} ({coverage}%), "
                f"zero_avg_iv: {zero_avg}, zero_rank: {zero_rank}"
            )
            return {
                "total_rows":      total,
                "expected_rows":   expected,
                "coverage_pct":    coverage,
                "zero_avg_atm_iv": zero_avg,
                "zero_iv_rank":    zero_rank,
            }
        except Exception as e:
            logger.error(f"_audit_snapshots [{idx}]: {e}")
            return {"error": str(e), "zero_avg_atm_iv": 0, "zero_iv_rank": 0}

    def _expected_timestamps(self) -> set:
        """
        Return set of 'YYYY-MM-DDTHH:MM' strings for every trading minute
        09:15–15:29 IST on today's date.
        """
        result = set()
        for total_min in range(_SESSION_START_MIN, _SESSION_END_MIN + 1):
            h, m = divmod(total_min, 60)
            result.add(f"{self._today}T{h:02d}:{m:02d}")
        return result

    # ──────────────────────────────────────────────────────────────
    # PHASE 2 — IN-DB REPAIRS
    # ──────────────────────────────────────────────────────────────

    def _repair_iv(self, idx: str) -> int:
        """
        Recompute IV for rows where LTP > 0 but IV = 0.
        All required inputs (spot, strike, expiry, timestamp) are in the row.
        Returns count of rows updated.
        """
        try:
            with self._db.engine.connect() as conn:
                rows = conn.execute(text(
                    "SELECT id, call_ltp, put_ltp, spot_price, strike, expiry, timestamp "
                    "FROM option_eod_prices "
                    "WHERE index_name=:i AND DATE(timestamp)=:d "
                    "AND (is_next_expiry IS NULL OR is_next_expiry=0) "
                    "AND ( (call_iv=0 AND call_ltp>0) "
                    "   OR (put_iv=0  AND put_ltp>0) )"
                ), {"i": idx, "d": self._today}).fetchall()

            if not rows:
                return 0

            updates = []
            for row in rows:
                rid, call_ltp, put_ltp, spot, strike, expiry, ts = row
                if isinstance(ts, str):
                    try:
                        ts = datetime.fromisoformat(ts)
                    except Exception:
                        continue
                t = _tte(expiry, ts)
                if t <= 0 or not spot or spot <= 0:
                    continue
                call_iv = _bs_iv(float(call_ltp or 0), spot, strike, t, _RATE, "CE")
                put_iv  = _bs_iv(float(put_ltp  or 0), spot, strike, t, _RATE, "PE")
                if call_iv > 0 or put_iv > 0:
                    updates.append({"id": rid, "ci": call_iv, "pi": put_iv})

            if updates:
                with self._db.engine.connect() as conn:
                    for batch in _chunks(updates, 500):
                        for u in batch:
                            conn.execute(text(
                                "UPDATE option_eod_prices "
                                "SET call_iv=:ci, put_iv=:pi WHERE id=:id"
                            ), u)
                    conn.commit()

            logger.info(f"[{idx}] IV repair: {len(updates)} rows updated")
            return len(updates)
        except Exception as e:
            logger.error(f"_repair_iv [{idx}]: {e}")
            return 0

    def _repair_greeks(self, idx: str) -> int:
        """
        Recompute Greeks for rows where IV > 0 but delta_call = 0.
        Returns count of rows updated.
        """
        try:
            with self._db.engine.connect() as conn:
                rows = conn.execute(text(
                    "SELECT id, call_iv, put_iv, spot_price, strike, expiry, timestamp "
                    "FROM option_eod_prices "
                    "WHERE index_name=:i AND DATE(timestamp)=:d "
                    "AND (is_next_expiry IS NULL OR is_next_expiry=0) "
                    "AND delta_call=0 AND call_iv>0"
                ), {"i": idx, "d": self._today}).fetchall()

            if not rows:
                return 0

            updates = []
            for row in rows:
                rid, call_iv, put_iv, spot, strike, expiry, ts = row
                if isinstance(ts, str):
                    try:
                        ts = datetime.fromisoformat(ts)
                    except Exception:
                        continue
                t = _tte(expiry, ts)
                if t <= 0 or not spot or spot <= 0:
                    continue
                cg = _bs_greeks(spot, strike, t, _RATE, "CE", float(call_iv or 0))
                pg = _bs_greeks(spot, strike, t, _RATE, "PE", float(put_iv  or 0))
                updates.append({
                    "id": rid,
                    "dc": cg["delta"], "gc": cg["gamma"],
                    "tc": cg["theta"], "vc": cg["vega"],
                    "dp": pg["delta"], "gp": pg["gamma"],
                    "tp": pg["theta"], "vp": pg["vega"],
                })

            if updates:
                with self._db.engine.connect() as conn:
                    for batch in _chunks(updates, 500):
                        for u in batch:
                            conn.execute(text(
                                "UPDATE option_eod_prices SET "
                                "delta_call=:dc, gamma_call=:gc, "
                                "theta_call=:tc, vega_call=:vc, "
                                "delta_put=:dp,  gamma_put=:gp, "
                                "theta_put=:tp,  vega_put=:vp "
                                "WHERE id=:id"
                            ), u)
                    conn.commit()

            logger.info(f"[{idx}] Greeks repair: {len(updates)} rows updated")
            return len(updates)
        except Exception as e:
            logger.error(f"_repair_greeks [{idx}]: {e}")
            return 0

    def _repair_snapshot_avg_iv(self, idx: str) -> int:
        """
        Recompute avg_atm_iv from stored chain_data JSON for snapshots
        where avg_atm_iv is 0 or NULL.
        """
        try:
            s = f"{self._today} 00:00:00"
            e = f"{self._today} 23:59:59"
            gap = config.SYMBOL_MAP.get(idx, {}).get("strike_gap", 50)

            with self._db.engine.connect() as conn:
                rows = conn.execute(text(
                    "SELECT id, atm_strike, chain_data FROM option_chain_snapshots "
                    "WHERE index_name=:i AND timestamp BETWEEN :s AND :e "
                    "AND (avg_atm_iv IS NULL OR avg_atm_iv=0) "
                    "AND chain_data IS NOT NULL"
                ), {"i": idx, "s": s, "e": e}).fetchall()

            if not rows:
                return 0

            updates = []
            for snap_id, atm, chain_json in rows:
                try:
                    data = (json.loads(chain_json)
                            if isinstance(chain_json, str) else chain_json) or []
                    ivs = []
                    for strike_row in data:
                        if abs(strike_row.get("strike", 0) - (atm or 0)) <= 2 * gap:
                            for col in ("call_iv", "put_iv"):
                                v = strike_row.get(col, 0)
                                if v and float(v) > 0:
                                    ivs.append(float(v))
                    if ivs:
                        updates.append({
                            "id":  snap_id,
                            "avg": round(sum(ivs) / len(ivs), 2),
                        })
                except Exception:
                    continue

            if updates:
                with self._db.engine.connect() as conn:
                    for u in updates:
                        conn.execute(text(
                            "UPDATE option_chain_snapshots "
                            "SET avg_atm_iv=:avg WHERE id=:id"
                        ), u)
                    conn.commit()

            logger.info(f"[{idx}] Snapshot avg_atm_iv repair: {len(updates)} rows")
            return len(updates)
        except Exception as e:
            logger.error(f"_repair_snapshot_avg_iv [{idx}]: {e}")
            return 0

    def _repair_snapshot_iv_rank(self, idx: str) -> int:
        """
        Recompute iv_rank for snapshots where avg_atm_iv > 0 but iv_rank = 0.
        Uses the same 20-day lookback as the live computation.
        """
        try:
            s = f"{self._today} 00:00:00"
            e = f"{self._today} 23:59:59"

            with self._db.engine.connect() as conn:
                rows = conn.execute(text(
                    "SELECT id, avg_atm_iv FROM option_chain_snapshots "
                    "WHERE index_name=:i AND timestamp BETWEEN :s AND :e "
                    "AND avg_atm_iv>0 "
                    "AND (iv_rank IS NULL OR iv_rank=0)"
                ), {"i": idx, "s": s, "e": e}).fetchall()

            if not rows:
                return 0

            updated = 0
            with self._db.engine.connect() as conn:
                for snap_id, avg_iv in rows:
                    rank = self._db.get_iv_rank(idx, float(avg_iv), lookback_days=20)
                    conn.execute(text(
                        "UPDATE option_chain_snapshots "
                        "SET iv_rank=:r WHERE id=:id"
                    ), {"r": rank, "id": snap_id})
                    updated += 1
                conn.commit()

            logger.info(f"[{idx}] Snapshot iv_rank repair: {updated} rows")
            return updated
        except Exception as e:
            logger.error(f"_repair_snapshot_iv_rank [{idx}]: {e}")
            return 0

    # ──────────────────────────────────────────────────────────────
    # PHASE 3 — BROKER BACKFILL
    # ──────────────────────────────────────────────────────────────

    def _backfill_missing(self, idx: str, missing_ts: List[str]) -> int:
        """
        For each missing 1-min timestamp, fetch historical 1-min candles
        from Fyers for all ATM±15 option contracts and INSERT new rows.

        Strategy:
          • Get expiry + approximate ATM from surrounding DB rows
          • For each strike × type (CE/PE), call fyers.history() once per day
          • Extract the needed minute(s) from the returned candles
          • Merge CE + PE data into one row per (strike, timestamp)
          • Insert all new rows in one bulk INSERT

        Capped at 60 missing timestamps to limit API call volume.
        Requires self._adapter to be a live FyersAdapter.
        """
        if not missing_ts:
            return 0
        if not self._adapter or not getattr(self._adapter, "_fyers", None):
            logger.debug(f"[{idx}] Backfill skipped — no live adapter")
            return 0

        # Limit to most recent 60 missing timestamps
        to_fill = set(missing_ts[-60:])
        if not to_fill:
            return 0

        # Get context: expiry string + latest spot price from existing rows
        ctx = self._get_fill_context(idx)
        if not ctx:
            logger.warning(f"[{idx}] Backfill: no context rows in DB — skipping")
            return 0

        expiry      = ctx["expiry"]
        spot_approx = ctx["spot"]
        gap         = config.SYMBOL_MAP.get(idx, {}).get("strike_gap", 50)
        atm_approx  = round(spot_approx / gap) * gap
        strikes     = [atm_approx + i * gap for i in range(-15, 16)]

        # For each (strike, type) fetch 1-min candles for the full day.
        # Build a lookup: {ts_key → {"CE": ltp, "PE": ltp, "vol_CE": ..., "vol_PE": ...}}
        candle_lookup: Dict[str, Dict[str, Any]] = {}
        api_calls = 0

        for strike in strikes:
            for opt_type in ("CE", "PE"):
                if api_calls >= 124:          # hard cap: 62 strikes × 2
                    break
                symbol = self._build_option_symbol(idx, expiry, int(strike), opt_type)
                if not symbol:
                    continue

                raw = self._fetch_1min_history(symbol, self._today)
                api_calls += 1

                for candle in raw:
                    try:
                        ts_unix, _, _, _, close_px, volume = candle[:6]
                        dt  = datetime.fromtimestamp(float(ts_unix))
                        key = dt.strftime("%Y-%m-%dT%H:%M")
                        if key not in to_fill:
                            continue
                        entry = candle_lookup.setdefault(key, {})
                        s_entry = entry.setdefault(str(int(strike)), {
                            "ts": dt, "spot": spot_approx, "strike": float(strike),
                        })
                        s_entry[opt_type]              = float(close_px)
                        s_entry[f"vol_{opt_type}"]     = float(volume)
                    except Exception:
                        continue

                time.sleep(0.05)    # ~50 ms between calls → ~6 s for full 124-call set

        if not candle_lookup:
            logger.info(f"[{idx}] Backfill: no candle data returned for {len(to_fill)} gaps")
            return 0

        # Build insert rows (one row per strike per minute, with both CE + PE)
        new_rows: List[Dict] = []
        for ts_key, strike_map in candle_lookup.items():
            for strike_str, sd in strike_map.items():
                if "ts" not in sd:
                    continue
                dt_val     = sd["ts"]
                spot       = sd["spot"]
                strike_val = sd["strike"]
                t          = _tte(expiry, dt_val)
                atm        = round(spot / gap) * gap
                offset     = int((strike_val - atm) / gap)

                ce_ltp = float(sd.get("CE", 0) or 0)
                pe_ltp = float(sd.get("PE", 0) or 0)

                call_iv = _bs_iv(ce_ltp, spot, strike_val, t, _RATE, "CE") if ce_ltp > 0 else 0.0
                put_iv  = _bs_iv(pe_ltp, spot, strike_val, t, _RATE, "PE") if pe_ltp > 0 else 0.0

                cg = _bs_greeks(spot, strike_val, t, _RATE, "CE", call_iv)
                pg = _bs_greeks(spot, strike_val, t, _RATE, "PE", put_iv)

                new_rows.append({
                    "timestamp":      dt_val,
                    "index_name":     idx,
                    "expiry":         expiry,
                    "spot_price":     spot,
                    "atm_strike":     float(atm),
                    "strike":         strike_val,
                    "strike_offset":  offset,
                    "call_ltp":       ce_ltp,
                    "call_oi":        0.0,
                    "call_iv":        call_iv,
                    "call_volume":    float(sd.get("vol_CE", 0) or 0),
                    "put_ltp":        pe_ltp,
                    "put_oi":         0.0,
                    "put_iv":         put_iv,
                    "put_volume":     float(sd.get("vol_PE", 0) or 0),
                    "delta_call":     cg["delta"],
                    "gamma_call":     cg["gamma"],
                    "theta_call":     cg["theta"],
                    "vega_call":      cg["vega"],
                    "delta_put":      pg["delta"],
                    "gamma_put":      pg["gamma"],
                    "theta_put":      pg["theta"],
                    "vega_put":       pg["vega"],
                    "is_next_expiry": False,
                    "created_at":     datetime.now(),
                })

        if not new_rows:
            return 0

        inserted = self._db.save_option_eod_prices(new_rows)
        logger.info(
            f"[{idx}] Backfill: inserted {inserted} rows "
            f"({len(to_fill)} missing ts × ~{_STRIKES_PER_TS} strikes, "
            f"{api_calls} API calls)"
        )
        return inserted

    def _get_fill_context(self, idx: str) -> Optional[Dict]:
        """
        Return expiry + approximate spot from the most recent existing row today.
        """
        try:
            with self._db.engine.connect() as conn:
                row = conn.execute(text(
                    "SELECT expiry, spot_price FROM option_eod_prices "
                    "WHERE index_name=:i AND DATE(timestamp)=:d "
                    "AND (is_next_expiry IS NULL OR is_next_expiry=0) "
                    "ORDER BY timestamp DESC LIMIT 1"
                ), {"i": idx, "d": self._today}).fetchone()
            if row and row[0] and row[1]:
                return {"expiry": row[0], "spot": float(row[1])}
        except Exception as e:
            logger.debug(f"_get_fill_context [{idx}]: {e}")
        return None

    def _build_option_symbol(self, idx: str, expiry: str,
                              strike: int, opt_type: str) -> Optional[str]:
        """Build a Fyers option trading symbol (e.g. NSE:NIFTY25MAR22500CE)."""
        try:
            from trading.order_manager import build_fyers_symbol
            return build_fyers_symbol(idx, strike, opt_type, expiry)  # fixed arg order: (index, strike, type, expiry)
        except Exception as e:
            logger.debug(f"_build_option_symbol: {e}")
            return None

    def _fetch_1min_history(self, symbol: str, date_str: str) -> List:
        """
        Call Fyers history API for 1-min candles on a given date.
        Returns list of [ts_unix, open, high, low, close, volume] or [].
        """
        try:
            resp = self._adapter._fyers.history({
                "symbol":      symbol,
                "resolution":  "1",
                "date_format": "1",
                "range_from":  date_str,
                "range_to":    date_str,
                "cont_flag":   "1",
            })
            return resp.get("candles", []) or []
        except Exception as e:
            logger.debug(f"_fetch_1min_history [{symbol}]: {e}")
            return []

    # ──────────────────────────────────────────────────────────────
    # REPORT LOGGING
    # ──────────────────────────────────────────────────────────────

    def _log_report(self):
        lines = [f"═══ EOD Options Audit — {self._today} ═══"]
        for idx, r in self._report["indices"].items():
            if "error" in r:
                lines.append(f"  [{idx}] ERROR: {r['error']}")
                continue
            ep = r.get("eod_prices", {})
            sn = r.get("chain_snapshots", {})
            lines.append(
                f"  [{idx}] EOD prices: "
                f"{ep.get('total_rows',0)}/{ep.get('expected_rows',0)} "
                f"({ep.get('coverage_pct',0)}%) | "
                f"missing_ts={ep.get('missing_count',0)} "
                f"zero_iv={ep.get('zero_iv_rows',0)} "
                f"zero_greeks={ep.get('zero_greeks_rows',0)} | "
                f"repaired iv={ep.get('repaired_iv',0)} "
                f"greeks={ep.get('repaired_greeks',0)} "
                f"backfilled={ep.get('backfilled_rows',0)}"
            )
            lines.append(
                f"  [{idx}] Snapshots:  "
                f"{sn.get('total_rows',0)}/{sn.get('expected_rows',0)} "
                f"({sn.get('coverage_pct',0)}%) | "
                f"zero_avg_iv={sn.get('zero_avg_atm_iv',0)} "
                f"zero_rank={sn.get('zero_iv_rank',0)} | "
                f"repaired avg={sn.get('repaired_avg_iv',0)} "
                f"rank={sn.get('repaired_iv_rank',0)}"
            )
        lines.append(
            f"  TOTAL ISSUES: {self._report['total_issues']}  "
            f"STATUS: {self._report['status']}"
        )
        logger.info("\n".join(lines))
