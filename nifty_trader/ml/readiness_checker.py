"""
ml/readiness_checker.py
─────────────────────────────────────────────────────────────────
ML Readiness Checker — validates data quality before model training.

Checks performed:
  1. Sample count — enough labeled records to train meaningfully?
  2. Label quality — what % came from real TradeOutcome (P1) vs ATR heuristic (P4)?
  3. Label balance — is the WIN/LOSS split reasonable (not too skewed)?
  4. Feature completeness — what % of key features are non-zero/non-null?
  5. Option chain zero rate — are Greeks, IV rank, PCR populated?
  6. Gate threshold recommendation — based on model accuracy vs current threshold.

Usage:
    checker = MLReadinessChecker(db)
    report  = checker.check()
    print(report.summary())
    if report.is_ready:
        train_model()
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# ─── Thresholds ────────────────────────────────────────────────
MIN_SAMPLES_TOTAL        = 200    # Minimum labeled records before any training
MIN_SAMPLES_QUALITY      = 100    # Minimum high-quality (P1+P2+P3) labeled records
MIN_HIGH_QUALITY_PCT     = 20.0   # At least 20% labels must be P1/P2/P3 (not pure ATR)
MAX_ATR_HEURISTIC_PCT    = 80.0   # Warn if >80% labels are ATR heuristic (P4)
MIN_WIN_RATE             = 20.0   # Warn if win rate < 20% (likely mis-labeling)
MAX_WIN_RATE             = 80.0   # Warn if win rate > 80% (likely mis-labeling)
MIN_FEATURE_FILL_PCT     = 50.0   # Key features must be ≥50% non-zero to pass
MIN_OPTIONS_FILL_PCT     = 30.0   # Options features (Greeks, IV) must be ≥30% non-zero

# Key features grouped for targeted completeness checks
CORE_FEATURES = [
    "compression_ratio", "atr", "plus_di", "minus_di", "adx", "di_spread",
    "volume_ratio", "engines_count", "candle_completion_pct",
    "mins_since_open", "session", "day_of_week",
]

OPTIONS_FEATURES = [
    "pcr", "iv_rank", "avg_atm_iv", "call_oi_change", "put_oi_change",
    "max_pain_distance", "iv_skew_ratio",
]

MTF_FEATURES = [
    "adx_5m", "plus_di_5m", "minus_di_5m", "adx_15m",
    "struct_5m", "struct_15m",
]

FUTURES_FEATURES = [
    "futures_oi_m", "futures_oi_chg_pct", "atm_oi_ratio",
    "excess_basis_pct", "futures_basis_slope",
]


# ─── Report dataclass ──────────────────────────────────────────

@dataclass
class ReadinessIssue:
    severity: str          # "ERROR", "WARNING", "INFO"
    code:     str          # short machine-readable code
    message:  str          # human-readable description


@dataclass
class ReadinessReport:
    checked_at:          datetime = field(default_factory=datetime.now)
    is_ready:            bool     = False   # True = safe to train

    # Sample counts
    total_records:       int   = 0
    labeled_records:     int   = 0
    unlabeled_records:   int   = 0

    # Label quality
    source_p1:           int   = 0    # TradeOutcome (real P&L)
    source_p2:           int   = 0    # CrossLink (nearby outcome)
    source_p3:           int   = 0    # OptionChain LTP
    source_p4:           int   = 0    # ATR Heuristic (weakest)
    high_quality_pct:    float = 0.0
    atr_heuristic_pct:   float = 0.0

    # Label balance
    win_count:           int   = 0
    loss_count:          int   = 0
    win_rate_pct:        float = 0.0

    # Feature completeness (% non-zero across labeled records)
    core_fill_pct:       float = 0.0
    options_fill_pct:    float = 0.0
    mtf_fill_pct:        float = 0.0
    futures_fill_pct:    float = 0.0

    # Recommendations
    recommended_gate_threshold: float = 0.50
    issues:              List[ReadinessIssue] = field(default_factory=list)

    def summary(self) -> str:
        """One-line summary for logging."""
        status = "READY" if self.is_ready else "NOT READY"
        errors  = sum(1 for i in self.issues if i.severity == "ERROR")
        warns   = sum(1 for i in self.issues if i.severity == "WARNING")
        return (
            f"MLReadiness [{status}] "
            f"labeled={self.labeled_records} "
            f"hq={self.high_quality_pct:.0f}% "
            f"win={self.win_rate_pct:.0f}% "
            f"core_fill={self.core_fill_pct:.0f}% "
            f"opts_fill={self.options_fill_pct:.0f}% "
            f"errors={errors} warns={warns}"
        )

    def full_report(self) -> str:
        """Multi-line detailed report for logging or UI display."""
        lines = [
            "═" * 60,
            f"ML READINESS CHECK  {self.checked_at.strftime('%Y-%m-%d %H:%M')}",
            "═" * 60,
            "",
            "── SAMPLES ──────────────────────────────",
            f"  Total records   : {self.total_records}",
            f"  Labeled         : {self.labeled_records}",
            f"  Unlabeled       : {self.unlabeled_records}",
            "",
            "── LABEL QUALITY ────────────────────────",
            f"  P1 TradeOutcome : {self.source_p1:>6}  (real option P&L — best)",
            f"  P2 CrossLink    : {self.source_p2:>6}  (nearby trade outcome)",
            f"  P3 OptionChain  : {self.source_p3:>6}  (LTP vs SL/T1/T2/T3)",
            f"  P4 ATR heuristic: {self.source_p4:>6}  (spot move — weakest)",
            f"  High quality    : {self.high_quality_pct:.1f}%  (P1+P2+P3 / labeled)",
            f"  ATR heuristic   : {self.atr_heuristic_pct:.1f}%  (lower is better)",
            "",
            "── LABEL BALANCE ────────────────────────",
            f"  Wins (label=1)  : {self.win_count}",
            f"  Losses (label=0): {self.loss_count}",
            f"  Win rate        : {self.win_rate_pct:.1f}%",
            "",
            "── FEATURE COMPLETENESS ─────────────────",
            f"  Core features   : {self.core_fill_pct:.1f}%",
            f"  Options features: {self.options_fill_pct:.1f}%",
            f"  MTF features    : {self.mtf_fill_pct:.1f}%",
            f"  Futures features: {self.futures_fill_pct:.1f}%",
            "",
            "── RECOMMENDATION ───────────────────────",
            f"  Gate threshold  : {self.recommended_gate_threshold:.2f}",
            f"  Training status : {'✓ READY' if self.is_ready else '✗ NOT READY'}",
        ]
        if self.issues:
            lines.append("")
            lines.append("── ISSUES ───────────────────────────────")
            for issue in self.issues:
                lines.append(f"  [{issue.severity:7}] {issue.code}: {issue.message}")
        lines.append("═" * 60)
        return "\n".join(lines)


# ─── Checker ───────────────────────────────────────────────────

class MLReadinessChecker:
    """
    Validates ML training data quality before a model training run.

    Usage:
        checker = MLReadinessChecker(db)
        report  = checker.check()
        if report.is_ready:
            model_manager.force_retrain()
    """

    def __init__(self, db):
        self._db = db

    def check(self, model_metrics: Optional[Dict] = None) -> ReadinessReport:
        """
        Run all readiness checks and return a ReadinessReport.

        model_metrics — optional dict from ModelVersion.metrics:
            {"accuracy": 0.58, "auc": 0.61, ...}
            Used to recommend gate threshold adjustments.
        """
        report = ReadinessReport()
        issues = report.issues

        try:
            self._check_samples(report, issues)
            self._check_label_quality(report, issues)
            self._check_label_balance(report, issues)
            self._check_feature_completeness(report, issues)
            self._recommend_gate(report, issues, model_metrics)

            errors = [i for i in issues if i.severity == "ERROR"]
            report.is_ready = len(errors) == 0
        except Exception as e:
            issues.append(ReadinessIssue("ERROR", "CHECK_FAILED",
                                         f"Readiness check exception: {e}"))
            report.is_ready = False
            logger.error(f"MLReadinessChecker error: {e}", exc_info=True)

        logger.info(report.summary())
        return report

    # ── Private checks ─────────────────────────────────────────

    def _check_samples(self, report: ReadinessReport, issues: list):
        """Check 1: Are there enough labeled samples?"""
        with self._db.get_session() as session:
            from database.models import MLFeatureRecord
            from sqlalchemy import func, case

            row = session.query(
                func.count().label("total"),
                func.sum(case((MLFeatureRecord.label != -1, 1), else_=0)).label("labeled"),
            ).one()

            report.total_records    = row.total   or 0
            report.labeled_records  = row.labeled or 0
            report.unlabeled_records = report.total_records - report.labeled_records

        if report.labeled_records < MIN_SAMPLES_TOTAL:
            issues.append(ReadinessIssue(
                "ERROR", "INSUFFICIENT_SAMPLES",
                f"Only {report.labeled_records} labeled records — need ≥{MIN_SAMPLES_TOTAL}"
            ))
        elif report.labeled_records < MIN_SAMPLES_TOTAL * 2:
            issues.append(ReadinessIssue(
                "WARNING", "LOW_SAMPLES",
                f"{report.labeled_records} labeled records — model accuracy will be limited (recommend ≥{MIN_SAMPLES_TOTAL * 2})"
            ))

    def _check_label_quality(self, report: ReadinessReport, issues: list):
        """Check 2: Label source distribution — P1 real outcomes vs P4 ATR heuristic."""
        with self._db.get_session() as session:
            from database.models import MLFeatureRecord
            from sqlalchemy import func, case

            row = session.query(
                func.sum(case((MLFeatureRecord.label_source == 1, 1), else_=0)).label("p1"),
                func.sum(case((MLFeatureRecord.label_source == 2, 1), else_=0)).label("p2"),
                func.sum(case((MLFeatureRecord.label_source == 3, 1), else_=0)).label("p3"),
                func.sum(case((MLFeatureRecord.label_source == 4, 1), else_=0)).label("p4"),
                # Records labeled before label_source tracking (source=0) — treat as unknown
                func.sum(case(
                    ((MLFeatureRecord.label_source == 0) & (MLFeatureRecord.label != -1), 1),
                    else_=0
                )).label("legacy"),
            ).one()

        labeled = report.labeled_records
        report.source_p1 = row.p1 or 0
        report.source_p2 = row.p2 or 0
        report.source_p3 = row.p3 or 0
        report.source_p4 = row.p4 or 0
        legacy           = row.legacy or 0

        high_quality = report.source_p1 + report.source_p2 + report.source_p3
        report.high_quality_pct  = round(high_quality  / max(labeled, 1) * 100.0, 1)
        report.atr_heuristic_pct = round(report.source_p4 / max(labeled, 1) * 100.0, 1)

        if high_quality < MIN_SAMPLES_QUALITY and report.source_p4 == 0 and legacy == 0:
            issues.append(ReadinessIssue(
                "WARNING", "NO_QUALITY_LABELS",
                "No label_source data (all records pre-date source tracking). "
                "Label quality is unknown — treat with caution."
            ))
        elif report.atr_heuristic_pct > MAX_ATR_HEURISTIC_PCT:
            issues.append(ReadinessIssue(
                "WARNING", "HIGH_ATR_HEURISTIC",
                f"{report.atr_heuristic_pct:.0f}% of labels are ATR heuristic (P4) — "
                f"labels are weak proxies for option P&L. "
                f"Let OutcomeTracker accumulate real TradeOutcome rows to improve quality."
            ))
        elif report.high_quality_pct < MIN_HIGH_QUALITY_PCT:
            issues.append(ReadinessIssue(
                "WARNING", "LOW_HIGH_QUALITY_LABELS",
                f"Only {report.high_quality_pct:.1f}% of labels are high-quality (P1/P2/P3). "
                f"Recommend waiting for more TradeOutcome data."
            ))

        if legacy > 0:
            issues.append(ReadinessIssue(
                "INFO", "LEGACY_LABELS",
                f"{legacy} labeled records pre-date source tracking (source=0). "
                f"These have unknown quality — they will be used for training but not quality-gated."
            ))

    def _check_label_balance(self, report: ReadinessReport, issues: list):
        """Check 3: Is the WIN/LOSS split reasonable?"""
        with self._db.get_session() as session:
            from database.models import MLFeatureRecord
            from sqlalchemy import func, case

            row = session.query(
                func.sum(case((MLFeatureRecord.label == 1, 1), else_=0)).label("wins"),
                func.sum(case((MLFeatureRecord.label == 0, 1), else_=0)).label("losses"),
            ).one()

        report.win_count  = row.wins   or 0
        report.loss_count = row.losses or 0
        labeled           = report.win_count + report.loss_count
        report.win_rate_pct = round(report.win_count / max(labeled, 1) * 100.0, 1)

        if report.win_rate_pct < MIN_WIN_RATE:
            issues.append(ReadinessIssue(
                "WARNING", "LOW_WIN_RATE",
                f"Win rate is {report.win_rate_pct:.1f}% — suspiciously low. "
                f"Check if labeling thresholds are too strict or signals are mostly false."
            ))
        elif report.win_rate_pct > MAX_WIN_RATE:
            issues.append(ReadinessIssue(
                "WARNING", "HIGH_WIN_RATE",
                f"Win rate is {report.win_rate_pct:.1f}% — suspiciously high. "
                f"Check if labeling thresholds are too loose (lookahead bias possible)."
            ))

        # Class imbalance check — model may need class_weight='balanced'
        minority = min(report.win_count, report.loss_count)
        majority = max(report.win_count, report.loss_count)
        if majority > 0 and minority / majority < 0.25:
            issues.append(ReadinessIssue(
                "WARNING", "CLASS_IMBALANCE",
                f"Severe class imbalance: {report.win_count} wins vs {report.loss_count} losses "
                f"(ratio {minority/max(majority,1):.2f}). "
                f"Model uses class_weight='balanced' to compensate."
            ))

    def _check_feature_completeness(self, report: ReadinessReport, issues: list):
        """Check 4: What % of feature values are non-zero in the training set?"""
        with self._db.get_session() as session:
            from database.models import MLFeatureRecord
            from sqlalchemy import func, case

            # Sample up to 2000 recent labeled records for speed
            records = session.query(MLFeatureRecord).filter(
                MLFeatureRecord.label != -1
            ).order_by(MLFeatureRecord.id.desc()).limit(2000).all()

        if not records:
            return

        n = len(records)

        def fill_pct(cols):
            if not cols or n == 0:
                return 0.0
            total = 0
            for col in cols:
                non_zero = sum(
                    1 for r in records
                    if getattr(r, col, None) not in (None, 0, 0.0, False)
                )
                total += non_zero
            return round(total / (n * len(cols)) * 100.0, 1)

        report.core_fill_pct    = fill_pct(CORE_FEATURES)
        report.options_fill_pct = fill_pct(OPTIONS_FEATURES)
        report.mtf_fill_pct     = fill_pct(MTF_FEATURES)
        report.futures_fill_pct = fill_pct(FUTURES_FEATURES)

        if report.core_fill_pct < MIN_FEATURE_FILL_PCT:
            issues.append(ReadinessIssue(
                "ERROR", "LOW_CORE_FILL",
                f"Core features only {report.core_fill_pct:.0f}% filled — "
                f"data pipeline issue. Check signal_aggregator feature saving."
            ))
        elif report.core_fill_pct < 75.0:
            issues.append(ReadinessIssue(
                "WARNING", "PARTIAL_CORE_FILL",
                f"Core features {report.core_fill_pct:.0f}% filled — "
                f"some records may have missing engine outputs."
            ))

        if report.options_fill_pct < MIN_OPTIONS_FILL_PCT:
            issues.append(ReadinessIssue(
                "WARNING", "LOW_OPTIONS_FILL",
                f"Options features only {report.options_fill_pct:.0f}% filled "
                f"(PCR, IV rank, Greeks) — option chain data may be missing. "
                f"Check FyersAdapter.get_option_chain() and _persist_oc_snapshot()."
            ))

        if report.mtf_fill_pct < MIN_OPTIONS_FILL_PCT:
            issues.append(ReadinessIssue(
                "INFO", "LOW_MTF_FILL",
                f"MTF (multi-timeframe) features only {report.mtf_fill_pct:.0f}% filled. "
                f"5m/15m ADX may not be populated for all records."
            ))

    def _recommend_gate(self, report: ReadinessReport, issues: list,
                        model_metrics: Optional[Dict]):
        """Check 5: Recommend gate threshold based on model accuracy."""
        if not model_metrics:
            report.recommended_gate_threshold = 0.50
            issues.append(ReadinessIssue(
                "INFO", "NO_MODEL_METRICS",
                "No model metrics available yet. Default gate=0.50 will be used."
            ))
            return

        accuracy = model_metrics.get("accuracy", 0.0)
        auc      = model_metrics.get("auc", 0.0)

        # Gate recommendation: only useful if model is better than random
        if accuracy < 0.50 or auc < 0.50:
            report.recommended_gate_threshold = 0.50
            issues.append(ReadinessIssue(
                "WARNING", "MODEL_BELOW_RANDOM",
                f"Model accuracy={accuracy:.2f} AUC={auc:.2f} — at or below random baseline. "
                f"Gate at 0.50 will barely filter anything. "
                f"Fix label quality before relying on ML gate."
            ))
        elif accuracy >= 0.65:
            # Strong model — can gate more aggressively
            report.recommended_gate_threshold = 0.60
            issues.append(ReadinessIssue(
                "INFO", "STRONG_MODEL",
                f"Model accuracy={accuracy:.2f} AUC={auc:.2f} — strong predictive power. "
                f"Recommend raising gate to 0.60 for higher precision."
            ))
        elif accuracy >= 0.55:
            report.recommended_gate_threshold = 0.55
            issues.append(ReadinessIssue(
                "INFO", "MODERATE_MODEL",
                f"Model accuracy={accuracy:.2f} AUC={auc:.2f} — moderate performance. "
                f"Gate at 0.55 is appropriate."
            ))
        else:
            report.recommended_gate_threshold = 0.50
            issues.append(ReadinessIssue(
                "INFO", "WEAK_MODEL",
                f"Model accuracy={accuracy:.2f} AUC={auc:.2f} — above random but weak. "
                f"Gate at 0.50 is safe. Focus on improving label quality first."
            ))
