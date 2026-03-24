"""
ml/auto_labeler.py
─────────────────────────────────────────────────────────────────
Automatically labels historical ML feature records by comparing
the predicted direction against subsequent price movement.

Labeling produces TWO outputs per record:

  label         (binary)  — 1 = valid move, 0 = false signal
  label_quality (graded)  — 0=SL_hit, 1=T1_hit, 2=T2_hit, 3=T3_hit

Priority (highest to lowest accuracy):
  1. Real TradeOutcome (SL/T1/T2/T3 hit) — actual option P&L
  2. Cross-link with nearby closed TradeOutcome on same index (±10 min)
  3. Option chain LTP vs computed SL/T1/T2/T3 option price levels
  4. ATR-tiered heuristic on spot price (fallback — no real option data)

Runs as a background job — once at startup, then every N seconds.
Never blocks the UI thread.
"""

import logging
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import List, Optional, Dict

import config
from database.manager import get_db

logger = logging.getLogger(__name__)

# How many candles to look ahead for outcome
LABEL_LOOKAHEAD_CANDLES = config.ML_LOOKAHEAD_CANDLES

# ATR thresholds for the spot-price heuristic (Priority 4)
# T1 ≈ 1×ATR, T2 ≈ 2×ATR, T3 ≈ 3×ATR from entry; SL ≈ 0.5×ATR adverse
VALID_MOVE_ATR_THRESHOLD  = 0.8   # minimum for binary label = 1 (T1-equivalent)
T2_ATR_THRESHOLD          = 1.6   # T2-equivalent move
T3_ATR_THRESHOLD          = 2.5   # T3-equivalent move
SL_ATR_THRESHOLD          = 0.5   # SL-equivalent adverse move

# Run labeling every N seconds (configurable via config.AUTO_LABEL_INTERVAL_SECONDS)
LABEL_INTERVAL_SECONDS = getattr(__import__("config"), "AUTO_LABEL_INTERVAL_SECONDS", 900)


class AutoLabeler:
    """
    Background thread that periodically scans unlabeled ML feature records
    and assigns outcome labels based on subsequent price data.
    """

    def __init__(self):
        self._db       = get_db()
        self._running  = False
        self._thread:  Optional[threading.Thread] = None
        self._label_count = 0

    def start(self):
        """Start background labeling thread."""
        self._running = True
        self._thread  = threading.Thread(
            target=self._loop, daemon=True, name="AutoLabelThread"
        )
        self._thread.start()
        logger.info("AutoLabeler started")

    def stop(self):
        self._running = False

    def run_once(self) -> int:
        """
        Label all unlabeled records immediately.
        Returns number of records labeled.
        """
        return self._label_pending()

    # ─── Main labeling logic ─────────────────────────────────────

    def _loop(self):
        # Run immediately on start
        time.sleep(30)  # Give system time to stabilize
        while self._running:
            try:
                count = self._label_pending()
                if count > 0:
                    logger.info(f"AutoLabeler: labeled {count} records")
                    self._label_count += count
            except Exception as e:
                logger.error(f"AutoLabeler error: {e}")
            time.sleep(LABEL_INTERVAL_SECONDS)

    def _label_pending(self) -> int:
        """
        Find unlabeled records and assign labels using candle price data.

        Performance: batch-loads all related TradeOutcome, Alert, MarketCandle,
        and OptionChainSnapshot rows upfront instead of N×queries per record.
        """
        labeled = 0
        with self._db.get_session() as session:
            from database.models import (MLFeatureRecord, MarketCandle, Alert,
                                         TradeOutcome, OptionChainSnapshot)
            from sqlalchemy import and_, or_

            # Use datetime.now() (local time) — records are stored with datetime.now()
            # in signal_aggregator. Using utcnow() would create a 5.5h offset in IST,
            # meaning same-session records would never be labeled intraday.
            cutoff = datetime.now() - timedelta(minutes=30)

            # Alert IDs that already have a CLOSED TradeOutcome — label these
            # immediately regardless of age (no need to wait for lookahead candles).
            closed_alert_ids = {
                row[0] for row in session.query(TradeOutcome.alert_id).filter(
                    TradeOutcome.status == "CLOSED",
                    TradeOutcome.alert_id.isnot(None),
                ).all()
            }

            pending = session.query(MLFeatureRecord).filter(
                MLFeatureRecord.label == -1,
            ).filter(
                or_(
                    MLFeatureRecord.timestamp <= cutoff,
                    MLFeatureRecord.alert_id.in_(closed_alert_ids)
                    if closed_alert_ids else MLFeatureRecord.timestamp <= cutoff,
                )
            ).all()

            if not pending:
                return 0

            # ── Batch pre-load 1: closed TradeOutcome rows ────────
            alert_ids = [r.alert_id for r in pending if r.alert_id]
            outcomes_by_alert: Dict[int, object] = {}
            alerts_by_id: Dict[int, object] = {}
            if alert_ids:
                for o in session.query(TradeOutcome).filter(
                    TradeOutcome.alert_id.in_(alert_ids),
                    TradeOutcome.status == "CLOSED",
                ).all():
                    outcomes_by_alert[o.alert_id] = o

                # ── Batch pre-load 2: Alert rows (for direction + instrument) ──
                for a in session.query(Alert).filter(
                    Alert.id.in_(alert_ids)
                ).all():
                    alerts_by_id[a.id] = a

            # ── Batch pre-load 3: future candles + chain snapshots per index ──
            lookahead_mins = config.CANDLE_INTERVAL_MINUTES * LABEL_LOOKAHEAD_CANDLES
            by_index: Dict[str, list] = defaultdict(list)
            for r in pending:
                by_index[r.index_name].append(r)

            candles_map: Dict[str, list] = {}
            chain_map:   Dict[str, list] = {}
            # Batch pre-load 4: closed TradeOutcome rows per index (for cross-linking)
            # When an EARLY_MOVE has no direct TradeOutcome link, we look for a nearby
            # TRADE_SIGNAL outcome on the same index (within 10 min) — real WIN/LOSS
            # is more accurate than the ATR spot heuristic.
            nearby_outcomes_map: Dict[str, list] = {}
            for idx, records in by_index.items():
                min_ts = min(r.timestamp for r in records)
                max_ts = max(r.timestamp for r in records) + timedelta(minutes=lookahead_mins)
                candles_map[idx] = session.query(MarketCandle).filter(
                    and_(
                        MarketCandle.index_name == idx,
                        MarketCandle.timestamp  >  min_ts,
                        MarketCandle.timestamp  <= max_ts,
                        MarketCandle.is_futures == False,  # noqa: E712
                    )
                ).order_by(MarketCandle.timestamp).all()
                # Option chain snapshots — used to read real option LTPs
                chain_map[idx] = session.query(OptionChainSnapshot).filter(
                    and_(
                        OptionChainSnapshot.index_name == idx,
                        OptionChainSnapshot.timestamp  >  min_ts,
                        OptionChainSnapshot.timestamp  <= max_ts,
                    )
                ).order_by(OptionChainSnapshot.timestamp).all()
                # Closed TradeOutcome rows — for cross-linking EARLY_MOVE labels
                nearby_outcomes_map[idx] = session.query(TradeOutcome).filter(
                    and_(
                        TradeOutcome.index_name == idx,
                        TradeOutcome.status     == "CLOSED",
                        TradeOutcome.entry_time >= min_ts - timedelta(minutes=10),
                        TradeOutcome.entry_time <= max_ts,
                    )
                ).order_by(TradeOutcome.entry_time).all()

            # ── Label each record using pre-loaded data ───────────
            for record in pending:
                outcome  = outcomes_by_alert.get(record.alert_id) if record.alert_id else None
                alert    = alerts_by_id.get(record.alert_id)       if record.alert_id else None
                candles  = candles_map.get(record.index_name, [])
                chains   = chain_map.get(record.index_name, [])
                nearby   = nearby_outcomes_map.get(record.index_name, [])

                result = self._compute_label_cached(record, outcome, alert, candles, chains, nearby)
                if result is not None:
                    label, quality = result
                    record.label         = label
                    record.label_quality = quality
                    record.label_direction = self._direction_from_label(label, alert)
                    labeled += 1

        return labeled

    def _compute_label_cached(
        self,
        record,
        outcome,              # pre-loaded TradeOutcome | None (direct link via alert_id)
        alert,                # pre-loaded Alert | None
        all_candles,          # pre-loaded MarketCandle list for this index (wide range)
        all_chains=None,      # pre-loaded OptionChainSnapshot list for this index
        nearby_outcomes=None, # pre-loaded closed TradeOutcome list for this index
    ) -> Optional[tuple]:
        """
        Compute label from pre-loaded data — no DB queries inside.

        Returns Optional[Tuple[int, int]] = (label, label_quality) where:
          label         1 = valid move, 0 = false signal
          label_quality 0 = SL_hit, 1 = T1_hit, 2 = T2_hit, 3 = T3_hit

        Priority:
          1. Real TradeOutcome data (SL/T1/T2/T3 hit) — actual option P&L.
          2. Cross-link with nearby closed TradeOutcome on same index (±10 min).
          3. Option chain LTP vs computed SL/T1/T2/T3 option price levels.
          4. ATR-tiered heuristic on spot price (fallback, no real option data).
        """
        # ── Priority 1: use real outcome if trade was tracked ─────
        if outcome is not None:
            has_post_close = outcome.post_close_eod_spot is not None
            if outcome.sl_hit:
                if has_post_close and outcome.post_sl_full_recovery:
                    return (1, 1)  # SL hit but fully recovered to T3+ → count as T1
                if has_post_close and outcome.post_sl_reversal:
                    return (1, 1)  # SL hit but recovered to T1+ → marginal win
                return (0, 0)      # Clean SL hit → loss
            if outcome.t3_hit:
                return (1, 3)
            if outcome.t2_hit:
                return (1, 2)
            if outcome.t1_hit:
                return (1, 1)
            if outcome.eod_spot is not None:
                return (0, 0)
            # Outcome row exists but post-close data not yet written → fall through

        # ── Priority 2: cross-link with nearby closed TradeOutcome ──
        # EARLY_MOVE records have no direct TradeOutcome link.
        # A nearby same-direction TRADE_SIGNAL outcome is far more accurate
        # than the ATR spot heuristic for option trade learning.
        if outcome is None and nearby_outcomes:
            record_dir = getattr(alert, "direction", None) if alert else None
            nearby = self._find_nearby_outcome(record, record_dir, nearby_outcomes)
            if nearby is not None:
                if nearby.t3_hit:
                    return (1, 3)
                if nearby.t2_hit:
                    return (1, 2)
                if nearby.t1_hit:
                    return (1, 1)
                if nearby.sl_hit:
                    return (0, 0)

        # ── Priority 3: option chain LTP vs SL/T1/T2/T3 levels ───
        # Only for trade/confirmed signals with a known instrument and price levels.
        if (all_chains and alert
                and getattr(alert, "alert_type", "") in ("TRADE_SIGNAL", "CONFIRMED_SIGNAL")
                and getattr(alert, "suggested_instrument", None)
                and getattr(alert, "entry_reference", None)
                and getattr(alert, "stop_loss_reference", None)
                and getattr(alert, "target_reference", None)):
            opt_result = self._label_from_option_chain(record, alert, all_chains)
            if opt_result is not None:
                return opt_result

        # ── Priority 4: ATR-tiered heuristic on spot price ────────
        # Grades the move quality using ATR multiples:
        #   ≥ T3_ATR_THRESHOLD (2.5×) → quality 3
        #   ≥ T2_ATR_THRESHOLD (1.6×) → quality 2
        #   ≥ VALID_MOVE_ATR_THRESHOLD (0.8×) → quality 1
        #   adverse ≥ SL_ATR_THRESHOLD (0.5×) OR no move → quality 0
        ts  = record.timestamp
        atr = record.atr or 20.0

        lookahead = timedelta(minutes=config.CANDLE_INTERVAL_MINUTES * LABEL_LOOKAHEAD_CANDLES)
        future_candles = [
            c for c in all_candles
            if ts < c.timestamp <= ts + lookahead
        ]

        if len(future_candles) < 2:
            return None

        direction = alert.direction if alert else None
        if not direction:
            return (0, 0)

        entry_price  = future_candles[0].open
        max_fav      = 0.0   # max favorable move
        max_adverse  = 0.0   # max adverse move
        for candle in future_candles:
            if direction == "BULLISH":
                max_fav     = max(max_fav,     candle.high - entry_price)
                max_adverse = max(max_adverse, entry_price - candle.low)
            else:
                max_fav     = max(max_fav,     entry_price - candle.low)
                max_adverse = max(max_adverse, candle.high - entry_price)

        if max_fav >= atr * T3_ATR_THRESHOLD:
            return (1, 3)
        if max_fav >= atr * T2_ATR_THRESHOLD:
            return (1, 2)
        if max_fav >= atr * VALID_MOVE_ATR_THRESHOLD:
            return (1, 1)
        # No significant favorable move — label as false signal
        return (0, 0)

    @staticmethod
    def _find_nearby_outcome(record, record_direction, nearby_outcomes,
                             window_minutes: int = 10):
        """
        Find the closest closed TradeOutcome on the same index within window_minutes
        of the record's timestamp, with a matching direction.

        Returns the TradeOutcome or None.
        """
        best = None
        best_delta = None
        for o in nearby_outcomes:
            # Direction must match so we don't mislabel a bearish early move
            # with a bullish trade outcome
            if record_direction and o.direction != record_direction:
                continue
            delta = abs((o.entry_time - record.timestamp).total_seconds())
            if delta <= window_minutes * 60:
                if best_delta is None or delta < best_delta:
                    best = o
                    best_delta = delta
        return best

    def _label_from_option_chain(self, record, alert, all_chains) -> Optional[tuple]:
        """
        Use stored option chain snapshots to label based on actual option LTP movement.

        Checks snapshots in the lookahead window and finds which level was hit first:
          T3 (3×risk above entry), T2 (2×risk), T1 (1×risk), or SL (≤sl).

        T2 and T3 are computed from the risk unit: risk = entry - sl.
        This is option-price-centric (LTP movement), not spot-centric.

        Returns Optional[Tuple[int, int]] = (label, label_quality), or None.
        """
        import re
        instrument = alert.suggested_instrument or ""
        m = re.search(r'(\d{4,6})(CE|PE)$', instrument)
        if not m:
            return None

        strike   = float(m.group(1))
        opt_type = m.group(2)       # "CE" or "PE"
        ltp_key  = "call_ltp" if opt_type == "CE" else "put_ltp"

        entry = float(alert.entry_reference)
        sl    = float(alert.stop_loss_reference)
        t1    = float(alert.target_reference)

        if entry <= 0 or sl <= 0 or t1 <= 0 or sl >= entry or t1 <= entry:
            return None

        # Compute T2 and T3 from the risk unit (1R = t1 - entry)
        risk = t1 - entry          # 1R in option price terms
        t2   = entry + risk * 2.0  # 2R above entry
        t3   = entry + risk * 3.0  # 3R above entry

        ts        = record.timestamp
        lookahead = timedelta(minutes=config.CANDLE_INTERVAL_MINUTES * LABEL_LOOKAHEAD_CANDLES)
        future_snaps = [s for s in all_chains
                        if ts < s.timestamp <= ts + lookahead]

        if len(future_snaps) < 2:
            return None

        best_quality = -1   # highest quality level reached in the window
        sl_hit       = False

        for snap in future_snaps:
            chain_data = snap.chain_data or []
            for row in chain_data:
                if abs(float(row.get("strike", -1)) - strike) < 0.5:
                    ltp = float(row.get(ltp_key, 0) or 0)
                    if ltp <= 0:
                        break
                    if ltp <= sl:
                        sl_hit = True
                    elif ltp >= t3:
                        best_quality = max(best_quality, 3)
                    elif ltp >= t2:
                        best_quality = max(best_quality, 2)
                    elif ltp >= t1:
                        best_quality = max(best_quality, 1)
                    break  # found the strike row; move to next snapshot

        if best_quality >= 1:
            return (1, best_quality)   # at least T1 hit — WIN
        if sl_hit:
            return (0, 0)              # SL hit, never recovered to T1
        # Neither SL nor T1 hit within lookahead — treat as false signal
        return (0, 0)

    @staticmethod
    def _direction_from_label(label: int, alert) -> int:
        """Returns +1 (bullish), -1 (bearish), or 0 (no move)."""
        if label == 0 or alert is None:
            return 0
        if alert.direction == "BULLISH":
            return 1
        if alert.direction == "BEARISH":
            return -1
        return 0

    def get_label_stats(self) -> dict:
        """Stats on labeled vs unlabeled records plus quality distribution."""
        from sqlalchemy import func, case
        with self._db.get_session() as session:
            from database.models import MLFeatureRecord
            row = session.query(
                func.count().label("total"),
                func.sum(case((MLFeatureRecord.label != -1, 1), else_=0)).label("labeled"),
                func.sum(case((MLFeatureRecord.label == 1,  1), else_=0)).label("positive"),
                func.sum(case((MLFeatureRecord.label_quality == 0, 1), else_=0)).label("q_sl"),
                func.sum(case((MLFeatureRecord.label_quality == 1, 1), else_=0)).label("q_t1"),
                func.sum(case((MLFeatureRecord.label_quality == 2, 1), else_=0)).label("q_t2"),
                func.sum(case((MLFeatureRecord.label_quality == 3, 1), else_=0)).label("q_t3"),
            ).one()
            total    = row.total    or 0
            labeled  = row.labeled  or 0
            positive = row.positive or 0
            return {
                "total":            total,
                "labeled":          labeled,
                "unlabeled":        total - labeled,
                "positive":         positive,
                "negative":         labeled - positive,
                "accuracy_estimate": round(positive / max(labeled, 1) * 100, 1),
                "lifetime_labeled": self._label_count,
                # Quality breakdown (how many wins were T1 vs T2 vs T3)
                "quality_sl":  row.q_sl or 0,
                "quality_t1":  row.q_t1 or 0,
                "quality_t2":  row.q_t2 or 0,
                "quality_t3":  row.q_t3 or 0,
            }
