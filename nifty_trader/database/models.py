"""
database/models.py
SQLAlchemy ORM models — full ML-ready schema.
Tables: market_candles, option_chain_snapshots, engine_signals, alerts, trade_outcomes
"""

from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, Float, String, Boolean,
    DateTime, Text, JSON, ForeignKey, Index, create_engine
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


# ──────────────────────────────────────────────────────────────────
# 1. MARKET CANDLES
# Raw OHLCV data — foundation for all engine calculations
# ──────────────────────────────────────────────────────────────────
class MarketCandle(Base):
    __tablename__ = "market_candles"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    index_name = Column(String(20), nullable=False)          # NIFTY / BANKNIFTY / MIDCPNIFTY
    timestamp  = Column(DateTime, nullable=False)
    interval   = Column(Integer, nullable=False, default=3)  # minutes
    open       = Column(Float, nullable=False)
    high       = Column(Float, nullable=False)
    low        = Column(Float, nullable=False)
    close      = Column(Float, nullable=False)
    volume     = Column(Float, nullable=False, default=0)
    oi         = Column(Float, default=0)       # Open Interest (futures candles)
    is_futures = Column(Boolean, default=False) # True = futures contract candle

    # Computed derivatives (stored for ML features)
    candle_range     = Column(Float)    # high - low
    body_size        = Column(Float)    # abs(close - open)
    upper_wick       = Column(Float)
    lower_wick       = Column(Float)
    is_bullish       = Column(Boolean)

    # Indicator values at this candle
    atr              = Column(Float)
    plus_di          = Column(Float)
    minus_di         = Column(Float)
    adx              = Column(Float)
    volume_sma       = Column(Float)
    volume_ratio     = Column(Float)    # volume / volume_sma

    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("idx_candle_index_ts",  "index_name", "timestamp"),
        Index("idx_candle_is_futures", "is_futures"),
    )

    def to_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


# ──────────────────────────────────────────────────────────────────
# 2. OPTION CHAIN SNAPSHOTS
# Full options chain state — PCR, OI, IV, volume
# ──────────────────────────────────────────────────────────────────
class OptionChainSnapshot(Base):
    __tablename__ = "option_chain_snapshots"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    index_name     = Column(String(20), nullable=False)
    timestamp      = Column(DateTime, nullable=False)
    expiry_date    = Column(String(15), nullable=False)
    spot_price     = Column(Float, nullable=False)
    atm_strike     = Column(Float, nullable=False)

    # Aggregated metrics
    total_call_oi  = Column(Float)
    total_put_oi   = Column(Float)
    pcr            = Column(Float)           # Put-Call Ratio by OI
    pcr_volume     = Column(Float)           # PCR by volume
    max_pain       = Column(Float)
    avg_atm_iv     = Column(Float)           # mean IV of ATM±2 strikes (for IV Rank history)
    iv_rank        = Column(Float)           # 0-100 percentile (rolling 20-day)

    # OI changes vs previous snapshot
    call_oi_change = Column(Float)
    put_oi_change  = Column(Float)
    pcr_change     = Column(Float)

    # Positioning signal
    oi_signal      = Column(String(10))      # BULLISH / BEARISH / NEUTRAL

    # Full chain data as JSON (strike-level detail)
    chain_data     = Column(JSON)            # [{strike, call_oi, put_oi, call_iv, put_iv, ...}]

    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("idx_oc_index_ts", "index_name", "timestamp"),
    )


# ──────────────────────────────────────────────────────────────────
# 3. ENGINE SIGNALS
# Individual engine outputs — stored for every evaluation cycle
# ──────────────────────────────────────────────────────────────────
class EngineSignal(Base):
    __tablename__ = "engine_signals"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    index_name     = Column(String(20), nullable=False)
    timestamp      = Column(DateTime, nullable=False)
    engine_name    = Column(String(30), nullable=False)   # compression / di_momentum / option_chain / volume_pressure

    # Signal output
    is_triggered   = Column(Boolean, nullable=False)
    direction      = Column(String(10))                   # BULLISH / BEARISH / NEUTRAL
    strength       = Column(Float)                        # 0.0 → 1.0
    score          = Column(Float)                        # Weighted contribution

    # Feature snapshot (ML input)
    features       = Column(JSON)                         # All raw values used for this decision

    # Reasoning
    reason         = Column(Text)

    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("idx_engine_index_ts", "index_name", "timestamp", "engine_name"),
        Index("idx_engine_ts",       "timestamp"),
    )


# ──────────────────────────────────────────────────────────────────
# 4. ALERTS
# All generated Early Move Alerts and Confirmed Trade Signals
# ──────────────────────────────────────────────────────────────────
class Alert(Base):
    __tablename__ = "alerts"

    id                 = Column(Integer, primary_key=True, autoincrement=True)
    index_name         = Column(String(20), nullable=False)
    timestamp          = Column(DateTime, nullable=False)
    alert_type         = Column(String(20), nullable=False)   # EARLY_MOVE / TRADE_SIGNAL
    direction          = Column(String(10), nullable=False)   # BULLISH / BEARISH
    confidence_score   = Column(Float, nullable=False)        # 0-100
    engines_triggered  = Column(JSON)                         # ["compression", "di_momentum", ...]
    engines_count      = Column(Integer)

    # Market state at alert
    spot_price         = Column(Float)
    atm_strike         = Column(Float)
    pcr                = Column(Float)
    atr                = Column(Float)

    # Trade suggestion (only for TRADE_SIGNAL)
    suggested_instrument = Column(String(50))    # e.g. NIFTY25MAR22500CE
    entry_reference      = Column(Float)
    stop_loss_reference  = Column(Float)
    target_reference     = Column(Float)
    target1              = Column(Float)         # T1 option premium level
    target2              = Column(Float)         # T2 option premium level
    target3              = Column(Float)         # T3 option premium level

    # Outcome tracking (filled after trade)
    outcome            = Column(String(10))      # WIN / LOSS / NEUTRAL / NULL
    outcome_pnl        = Column(Float)
    outcome_notes      = Column(Text)
    outcome_timestamp  = Column(DateTime)

    # ML prediction at signal time
    ml_score           = Column(Float)           # 0-100: model confidence this is a real move
    ml_phase           = Column(Integer)         # 1=collecting, 2=active model

    # Was this a valid signal (for ML labeling)
    is_valid           = Column(Boolean)         # Human-labeled

    raw_features       = Column(JSON)            # Full feature vector at signal time

    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("idx_alert_index_ts",   "index_name", "timestamp"),
        Index("idx_alert_type_ts",    "alert_type",  "timestamp"),   # fast filter by TRADE_SIGNAL
    )


# ──────────────────────────────────────────────────────────────────
# 5. TRADE OUTCOMES
# Full post-trade tracking: SL / T1 / T2 / T3 / EOD / MFE / MAE
# ──────────────────────────────────────────────────────────────────
class TradeOutcome(Base):
    __tablename__ = "trade_outcomes"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    alert_id         = Column(Integer, ForeignKey("alerts.id"), nullable=False)
    index_name       = Column(String(20))
    instrument       = Column(String(50))

    # Signal state at entry
    direction        = Column(String(10))   # BULLISH / BEARISH
    entry_time       = Column(DateTime)
    entry_spot       = Column(Float)        # spot price at signal
    atr_at_signal    = Column(Float)        # ATR used to compute levels

    # Spot-based tracking levels (computed from entry_spot + ATR multipliers)
    spot_sl          = Column(Float)        # Stop Loss spot level
    spot_t1          = Column(Float)        # Target 1 spot level
    spot_t2          = Column(Float)        # Target 2 spot level
    spot_t3          = Column(Float)        # Target 3 spot level

    # Option price references (from signal)
    entry_price      = Column(Float)        # option LTP at signal
    exit_price       = Column(Float)        # option LTP at close
    stop_loss_opt    = Column(Float)        # SL option price reference
    t1_opt           = Column(Float)        # T1 option price reference
    t2_opt           = Column(Float)        # T2 option price reference
    t3_opt           = Column(Float)        # T3 option price reference

    # Level hit tracking
    sl_hit           = Column(Boolean, default=False)
    sl_hit_time      = Column(DateTime)
    sl_hit_spot      = Column(Float)

    t1_hit           = Column(Boolean, default=False)
    t1_hit_time      = Column(DateTime)

    t2_hit           = Column(Boolean, default=False)
    t2_hit_time      = Column(DateTime)

    t3_hit           = Column(Boolean, default=False)
    t3_hit_time      = Column(DateTime)

    # Excursion analysis (in ATR units)
    mfe_atr          = Column(Float, default=0.0)  # Max Favorable Excursion
    mae_atr          = Column(Float, default=0.0)  # Max Adverse Excursion

    # EOD close
    eod_spot         = Column(Float)
    exit_time        = Column(DateTime)
    exit_reason      = Column(String(20))   # SL_HIT / T1_HIT / T2_HIT / T3_HIT / EOD

    # Overall result
    outcome          = Column(String(10))   # WIN / LOSS / NEUTRAL
    pnl              = Column(Float)
    pnl_percent      = Column(Float)

    # Rupee P&L tracking
    lot_size         = Column(Integer, default=0)
    investment_amt   = Column(Float,   default=0.0)  # entry_price × lot_size
    pnl_sl           = Column(Float,   default=0.0)  # expected loss at SL in ₹
    pnl_t1           = Column(Float,   default=0.0)  # expected profit at T1 in ₹
    pnl_t2           = Column(Float,   default=0.0)  # expected profit at T2 in ₹
    pnl_t3           = Column(Float,   default=0.0)  # expected profit at T3 in ₹
    realized_pnl     = Column(Float,   default=0.0)  # actual P&L at close in ₹

    # Alert type — distinguishes raw vs candle-close-confirmed entries for stats
    alert_type       = Column(String(20), default="TRADE_SIGNAL")  # TRADE_SIGNAL / CONFIRMED_SIGNAL

    # Status
    status           = Column(String(10), default="OPEN")  # OPEN / CLOSED

    # ── Post-close tracking ───────────────────────────────────────
    # After SL or T3 closes the trade, we keep monitoring price until 15:30
    # to answer: "what would have happened with a wider SL / longer hold?"
    post_close_t1_hit          = Column(Boolean, default=False)
    post_close_t1_hit_time     = Column(DateTime)
    post_close_t2_hit          = Column(Boolean, default=False)
    post_close_t2_hit_time     = Column(DateTime)
    post_close_t3_hit          = Column(Boolean, default=False)
    post_close_t3_hit_time     = Column(DateTime)
    post_close_max_fav_atr     = Column(Float, default=0.0)  # best move after close (ATR units)
    post_close_max_adv_atr     = Column(Float, default=0.0)  # worst move after close (ATR units)
    post_close_eod_spot        = Column(Float)               # spot at 15:30 for every closed trade
    # Shorthand flags for ML
    post_sl_reversal           = Column(Boolean, default=False)  # SL hit → price later hit T1+
    post_sl_full_recovery      = Column(Boolean, default=False)  # SL hit → price later hit T3

    alert = relationship("Alert", backref="trade_outcomes")
    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("idx_outcome_alert",       "alert_id"),
        Index("idx_outcome_status",      "status"),
        Index("idx_outcome_index_entry", "index_name", "entry_time"),
    )


# ──────────────────────────────────────────────────────────────────
# 6. OPTION PRICE HISTORY
# Full option LTP path after each trade signal — used to compute
# real MFE/MAE/RR for regression model training.
# ──────────────────────────────────────────────────────────────────
class OptionPriceHistory(Base):
    __tablename__ = "option_price_history"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    alert_id       = Column(Integer, ForeignKey("alerts.id"), nullable=False)
    instrument     = Column(String(50), nullable=False)   # e.g. NIFTY24-03-23200PE
    timestamp      = Column(DateTime, nullable=False)
    ltp            = Column(Float, nullable=False)        # option LTP at this time
    entry_price    = Column(Float)                        # option entry at signal time
    pct_from_entry = Column(Float)                        # (ltp - entry) / entry * 100
    candle_num     = Column(Integer, default=0)           # 0=entry, 1=first candle, etc.

    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("idx_oph_alert", "alert_id"),
        Index("idx_oph_instrument_ts", "instrument", "timestamp"),
    )


# ──────────────────────────────────────────────────────────────────
# 7. ML FEATURE STORE
# Denormalized feature vectors ready for model training
# ──────────────────────────────────────────────────────────────────
class MLFeatureRecord(Base):
    __tablename__ = "ml_feature_store"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    alert_id       = Column(Integer, ForeignKey("alerts.id"), nullable=True)
    index_name     = Column(String(20))
    timestamp      = Column(DateTime)

    # Candle features
    atr            = Column(Float)
    atr_pct_change = Column(Float)
    compression_ratio = Column(Float)
    candle_range_5  = Column(Float)   # Mean range last 5
    candle_range_20 = Column(Float)   # Mean range last 20

    # DI features
    plus_di        = Column(Float)
    minus_di       = Column(Float)
    adx            = Column(Float)
    di_spread      = Column(Float)
    plus_di_slope  = Column(Float)
    minus_di_slope = Column(Float)

    # Option chain features
    pcr            = Column(Float)
    pcr_change     = Column(Float)
    call_oi_change = Column(Float)
    put_oi_change  = Column(Float)
    iv_rank        = Column(Float)
    max_pain_distance = Column(Float)  # Spot distance from max pain

    # Volume features
    volume_ratio   = Column(Float)
    volume_ratio_5 = Column(Float)   # Avg volume ratio over 5 candles
    is_small_candle = Column(Boolean)

    # Engine 5: Liquidity Trap features
    sweep_up          = Column(Boolean)
    sweep_down        = Column(Boolean)
    liq_wick_ratio    = Column(Float)
    liq_volume_ratio  = Column(Float)

    # Engine 6: Gamma Levels features
    gamma_flip          = Column(Boolean)
    near_gamma_wall     = Column(Boolean)
    dist_to_gamma_wall  = Column(Float)
    dist_to_call_wall   = Column(Float)
    dist_to_put_wall    = Column(Float)

    # Engine 7: IV Expansion features
    iv_expanding     = Column(Boolean)
    iv_skew_ratio    = Column(Float)
    avg_atm_iv       = Column(Float)
    iv_change_pct    = Column(Float)

    # Engine 8: Market Regime features
    market_regime    = Column(String(15))   # TRENDING / RANGING / VOLATILE
    regime_adx       = Column(Float)
    regime_atr_ratio = Column(Float)

    # Engine outputs (binary)
    compression_triggered       = Column(Boolean)
    di_triggered                = Column(Boolean)
    option_chain_triggered      = Column(Boolean)
    volume_triggered            = Column(Boolean)
    liquidity_trap_triggered    = Column(Boolean)
    gamma_triggered             = Column(Boolean)
    iv_triggered                = Column(Boolean)
    regime_triggered            = Column(Boolean)
    vwap_triggered              = Column(Boolean)
    engines_count               = Column(Integer)

    # Engine 7-new: VWAP Pressure features
    vwap             = Column(Float)
    dist_to_vwap_pct = Column(Float)
    vwap_cross_up    = Column(Boolean)
    vwap_cross_down  = Column(Boolean)
    vwap_bounce      = Column(Boolean)
    vwap_rejection   = Column(Boolean)
    vwap_vol_ratio   = Column(Float)

    # Label (for supervised learning)
    label          = Column(Integer)    # 1 = valid move, 0 = false signal, -1 = unlabeled
    label_direction = Column(Integer)   # 1 = bullish, -1 = bearish, 0 = no move
    label_quality  = Column(Integer)    # -1=unlabeled, 0=SL_hit, 1=T1_hit, 2=T2_hit, 3=T3_hit
    # Which priority was used when labeling (for data quality reporting)
    # 1=TradeOutcome (real P&L), 2=CrossLink (nearby outcome), 3=OptionChain LTP, 4=ATR Heuristic
    label_source   = Column(Integer, default=0)  # 0=unlabeled

    # Signal timing (for forming-candle and theta-decay features)
    candle_completion_pct = Column(Float)    # 0.0-1.0: how far into candle at signal time

    # Group A: Time context
    mins_since_open = Column(Float)
    session         = Column(Integer)   # 0=pre, 1=opening, 2=morning, 3=midday, 4=closing
    is_expiry       = Column(Integer)   # 0/1
    day_of_week     = Column(Integer)   # 0=Mon … 4=Fri
    dte             = Column(Integer)   # days to expiry

    # Group B: Price context
    spot_vs_prev_pct = Column(Float)
    atr_pct_spot     = Column(Float)
    chop             = Column(Float)
    efficiency_ratio = Column(Float)
    gap_pct          = Column(Float)
    preopen_gap_pct  = Column(Float)   # futures gap captured 9:00–9:14, frozen at 9:15

    # Group C: Candle patterns
    prev_body_ratio  = Column(Float)
    prev_bullish     = Column(Integer)
    consec_bull      = Column(Integer)
    consec_bear      = Column(Integer)
    range_expansion  = Column(Float)

    # Group D: Index correlation
    aligned_indices  = Column(Integer)
    market_breadth   = Column(Float)

    # Group E: OI & Futures
    futures_oi_m       = Column(Float)
    futures_oi_chg_pct = Column(Float)
    atm_oi_ratio       = Column(Float)
    # Extended futures — institutional footprint (data-only, no gate)
    excess_basis_pct    = Column(Float)    # raw_basis - fair_value; +ve = long bias, -ve = short/hedge bias
    futures_basis_slope = Column(Float)    # 5-candle basis slope; positive = widening (longs added)
    oi_regime           = Column(Integer)  # 0=long_buildup 1=short_buildup 2=short_covering 3=long_unwinding
    oi_regime_bullish   = Column(Integer)  # 1 if price rising (long_buildup or short_covering)
    oi_regime_bearish   = Column(Integer)  # 1 if price falling (short_buildup or long_unwinding)

    # Group F: MTF ADX + DI slopes (reversal learning)
    adx_5m            = Column(Float)
    plus_di_5m        = Column(Float)
    minus_di_5m       = Column(Float)
    adx_15m           = Column(Float)
    plus_di_slope_5m  = Column(Float)
    minus_di_slope_5m = Column(Float)
    plus_di_slope_15m = Column(Float)
    minus_di_slope_15m = Column(Float)
    di_reversal_5m    = Column(Integer)  # 1 = opposing DI fading on 5m
    di_reversal_15m   = Column(Integer)  # 1 = opposing DI fading on 15m
    di_reversal_both  = Column(Integer)  # 1 = both TFs show fading opposing DI

    # Group G: VIX
    vix              = Column(Float)
    vix_high         = Column(Integer)

    # Group G (extended): Price Structure (5m + 15m HH/HL/LH/LL)
    struct_5m           = Column(Integer)  # 1=BULLISH, 0=NEUTRAL, -1=BEARISH
    struct_15m          = Column(Integer)
    struct_5m_aligned   = Column(Integer)  # 1 if 5m structure matches signal direction
    struct_15m_aligned  = Column(Integer)
    struct_both_aligned = Column(Integer)  # 1 if both 5m+15m match signal direction

    # Group H: Signal identity (critical for model to learn direction/index bias)
    direction_encoded = Column(Integer)   # 1=BULLISH, -1=BEARISH
    index_encoded     = Column(Integer)   # 0=NIFTY,1=BANKNIFTY,2=MIDCPNIFTY,3=SENSEX,4=other
    is_trade_signal   = Column(Integer)   # 0=EARLY_MOVE, 1=TRADE_SIGNAL

    # Group I: Historical performance context (added for richer ML learning)
    # Rolling 20-trade win rate for the best-matched named setup at signal time (0-100).
    # 0.0 means no setup matched or no history yet. Model learns to discount
    # setups that fire often but rarely result in wins.
    setup_win_rate     = Column(Float, default=0.0)
    # Minutes since the last TRADE_SIGNAL on the same index (any direction).
    # Short gaps (< 5 min) = potential over-signaling / low conviction.
    # Long gaps (> 60 min) = fresh opportunity after consolidation.
    mins_since_last_signal = Column(Float, default=0.0)

    # Outcome feedback (populated by OutcomeTracker when trade closes)
    sl_hit             = Column(Boolean)
    t1_hit             = Column(Boolean)
    t2_hit             = Column(Boolean)
    t3_hit             = Column(Boolean)
    max_favorable_atr  = Column(Float)   # MFE in ATR units
    max_adverse_atr    = Column(Float)   # MAE in ATR units
    candles_to_close   = Column(Float)   # BUG-3: how many 3-min candles until trade closed
    # Post-close feedback (populated at EOD — key ML signals)
    post_sl_reversal      = Column(Boolean)  # SL hit but price later recovered to T1+
    post_sl_full_recovery = Column(Boolean)  # SL hit but price later hit T3
    post_close_max_fav_atr= Column(Float)    # best move AFTER close (ATR units)

    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("idx_ml_index_label_ts", "index_name", "label", "timestamp"),
    )


# ──────────────────────────────────────────────────────────────────
# 8. SETUP ALERTS
# One row per named setup that fires per candle.
# Links to alerts table via alert_id.
# Auto-labeler will fill label/label_quality/t1_hit/t2_hit/t3_hit.
# ──────────────────────────────────────────────────────────────────
class SetupAlert(Base):
    __tablename__ = "setup_alerts"

    id            = Column(Integer, primary_key=True, autoincrement=True)

    # Link to the alert that triggered this setup evaluation
    alert_id      = Column(Integer, ForeignKey("alerts.id"), nullable=True)

    # Signal identity
    index_name    = Column(String(20), nullable=False)
    timestamp     = Column(DateTime,   nullable=False)
    direction     = Column(String(10), nullable=False)  # BULLISH / BEARISH

    # Setup identity
    setup_name    = Column(String(40), nullable=False)
    setup_grade   = Column(String(4),  nullable=False)  # A++ / A+ / A / B / C- / D
    expected_wr   = Column(Float,      nullable=False)  # Tested WR% at definition time
    description   = Column(String(120))

    # Market state at signal time
    spot_price    = Column(Float, default=0.0)
    atr           = Column(Float, default=0.0)
    engines_count = Column(Integer, default=0)
    regime        = Column(String(15))           # TRENDING / RANGING / AMBIGUOUS
    volume_ratio  = Column(Float, default=0.0)
    pcr           = Column(Float, default=0.0)

    # Labels — filled by auto_labeler as outcomes become known
    label         = Column(Integer, default=-1)  # -1=unlabeled, 0=loss, 1=win
    label_quality = Column(Integer, default=-1)  # -1=unlabeled, 0=SL, 1=T1, 2=T2, 3=T3
    t1_hit        = Column(Boolean, default=False)
    t2_hit        = Column(Boolean, default=False)
    t3_hit        = Column(Boolean, default=False)
    sl_hit        = Column(Boolean, default=False)
    realized_pnl  = Column(Float,   default=0.0)  # actual P&L at close in ₹

    created_at    = Column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("idx_setup_alerts_index_ts",   "index_name", "timestamp"),
        Index("idx_setup_alerts_name_label",  "setup_name", "label"),
    )


# ──────────────────────────────────────────────────────────────────
# 9. S11 PAPER TRADES
# Paper trade tracking for S11 setup (DI + Trending + HighVol >= 1.5×).
# Completely separate from trade_outcomes — never mixed, independently queryable.
# 2 lots per trade. T2 hit → trail SL to entry. T3 hit → full close.
# ──────────────────────────────────────────────────────────────────
class S11PaperTrade(Base):
    __tablename__ = "s11_paper_trades"

    id              = Column(Integer, primary_key=True, autoincrement=True)

    # Link to source alert (alert_id may be 0 for confirmed signals — set async)
    alert_id        = Column(Integer, default=0)

    # Signal identity
    index_name      = Column(String(20), nullable=False)
    direction       = Column(String(10), nullable=False)   # BULLISH / BEARISH
    confidence_score= Column(Float,  default=0.0)
    date            = Column(String(12), nullable=False)   # "YYYY-MM-DD" for daily grouping

    # Entry state
    entry_time      = Column(DateTime,  nullable=False)
    entry_spot      = Column(Float,     default=0.0)
    entry_price     = Column(Float,     default=0.0)  # option premium at entry
    instrument      = Column(String(50),default="")   # e.g. NIFTY30MAR2024500CE
    strike          = Column(Float,     default=0.0)
    option_type     = Column(String(4), default="")   # CE / PE
    atr_at_signal   = Column(Float,     default=0.0)

    # Sizing — 2 lots
    lot_size        = Column(Integer,   default=0)    # per lot (from config at signal time)
    lots            = Column(Integer,   default=2)    # always 2
    units           = Column(Integer,   default=0)    # lots × lot_size

    # Option premium levels
    sl_price        = Column(Float, default=0.0)
    t1_price        = Column(Float, default=0.0)
    t2_price        = Column(Float, default=0.0)
    t3_price        = Column(Float, default=0.0)

    # Spot reference levels (for display + post-close analysis)
    spot_sl         = Column(Float, default=0.0)
    spot_t1         = Column(Float, default=0.0)
    spot_t2         = Column(Float, default=0.0)
    spot_t3         = Column(Float, default=0.0)

    # Pre-computed P&L in rupees (units × move)
    pnl_at_sl       = Column(Float, default=0.0)   # expected loss at SL
    pnl_at_t1       = Column(Float, default=0.0)
    pnl_at_t2       = Column(Float, default=0.0)   # expected profit at T2
    pnl_at_t3       = Column(Float, default=0.0)

    # Level hit milestones
    t1_hit          = Column(Boolean, default=False)
    t1_hit_time     = Column(DateTime)
    t2_hit          = Column(Boolean, default=False)
    t2_hit_time     = Column(DateTime)
    t3_hit          = Column(Boolean, default=False)
    t3_hit_time     = Column(DateTime)
    sl_hit          = Column(Boolean, default=False)
    sl_hit_time     = Column(DateTime)

    # Excursion (ATR units)
    mfe_atr         = Column(Float, default=0.0)
    mae_atr         = Column(Float, default=0.0)

    # Exit state
    status          = Column(String(10), default="OPEN")   # OPEN / CLOSED
    exit_time       = Column(DateTime)
    exit_price      = Column(Float, default=0.0)           # option LTP at close
    exit_spot       = Column(Float, default=0.0)
    exit_reason     = Column(String(20), default="")       # SL_HIT/T2_HIT/T3_HIT/EOD
    outcome         = Column(String(10), default="")       # WIN / LOSS / NEUTRAL

    # Realized P&L in rupees (2 lots, actual exit price used)
    realized_pnl    = Column(Float, default=0.0)

    created_at      = Column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("idx_s11_index_date",  "index_name", "date"),
        Index("idx_s11_status",      "status"),
    )


# ──────────────────────────────────────────────────────────────────
# 10. OPTION EOD PRICES
# Live option strike prices collected every tick till market close.
# Stores ATM ± N strikes per chain update for research.
# Used for: option premium modelling, IV term structure, greeks research.
# ──────────────────────────────────────────────────────────────────
class OptionEODPrice(Base):
    __tablename__ = "option_eod_prices"

    id            = Column(Integer, primary_key=True, autoincrement=True)

    # When and where
    timestamp     = Column(DateTime,   nullable=False)
    index_name    = Column(String(20), nullable=False)
    expiry        = Column(String(15), nullable=False)   # "27MAR2025"
    spot_price    = Column(Float, default=0.0)
    atm_strike    = Column(Float, default=0.0)

    # Strike-level data (one row per strike)
    strike        = Column(Float, nullable=False)
    strike_offset = Column(Integer, default=0)  # 0=ATM, +1=1 above ATM, -1=1 below, etc.

    # Call option
    call_ltp      = Column(Float, default=0.0)
    call_oi       = Column(Float, default=0.0)
    call_iv       = Column(Float, default=0.0)
    call_volume   = Column(Float, default=0.0)

    # Put option
    put_ltp       = Column(Float, default=0.0)
    put_oi        = Column(Float, default=0.0)
    put_iv        = Column(Float, default=0.0)
    put_volume    = Column(Float, default=0.0)

    # Greeks (Black-Scholes, computed at collection time)
    delta_call    = Column(Float, default=0.0)
    gamma_call    = Column(Float, default=0.0)
    theta_call    = Column(Float, default=0.0)
    vega_call     = Column(Float, default=0.0)
    delta_put     = Column(Float, default=0.0)
    gamma_put     = Column(Float, default=0.0)
    theta_put     = Column(Float, default=0.0)
    vega_put      = Column(Float, default=0.0)

    # Second-expiry flag (True when this row belongs to next weekly/monthly chain)
    is_next_expiry = Column(Boolean, default=False)

    created_at    = Column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("idx_eod_index_ts",     "index_name", "timestamp"),
        Index("idx_eod_strike_ts",    "index_name", "strike", "timestamp"),
    )



class AutoPaperTrade(Base):
    """Persisted record of every paper/live auto-trade order placed by OrderManager."""
    __tablename__ = "auto_paper_trades"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    order_id    = Column(String(30), unique=True, nullable=False)
    alert_id    = Column(Integer, default=0)
    index_name  = Column(String(20))
    direction   = Column(String(10))
    symbol      = Column(String(60))
    qty         = Column(Integer, default=0)
    entry       = Column(Float, default=0.0)
    sl          = Column(Float, default=0.0)
    tp          = Column(Float, default=0.0)
    sl_opt      = Column(Float, default=0.0)
    tp_opt      = Column(Float, default=0.0)
    status      = Column(String(20), default="PAPER-OPEN")
    pnl         = Column(Float, default=0.0)
    mode        = Column(String(10), default="PAPER")
    placed_at   = Column(DateTime)
    closed_at   = Column(DateTime)
    date        = Column(String(10))   # YYYY-MM-DD (IST)
    created_at  = Column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("idx_apt_date",     "date"),
        Index("idx_apt_order_id", "order_id"),
    )
