"""
NiftyTrader — Central Configuration
Modify broker credentials and thresholds here.
"""

from typing import Dict, List, Optional
from datetime import timezone, timedelta
import os

# ─────────────────────────────────────────────────────────────────
# TIMEZONE
# Centralised IST timezone object — import this instead of defining
# a local _IST in each module.
# ─────────────────────────────────────────────────────────────────
IST = timezone(timedelta(hours=5, minutes=30))

# ─────────────────────────────────────────────────────────────────
# BROKER SELECTION
# Choose one: "fyers" | "dhan" | "kite" | "upstox" | "mock"
# Set via env var or changed at runtime from the Credentials UI tab
# ─────────────────────────────────────────────────────────────────
BROKER = os.getenv("BROKER", "fyers")

# ─────────────────────────────────────────────────────────────────
# BROKER CREDENTIALS
# The Credentials UI tab writes into this dict when user saves creds.
# ─────────────────────────────────────────────────────────────────
BROKER_CREDENTIALS: dict = {
    "fyers": {
        "client_id":    os.getenv("FYERS_CLIENT_ID",    ""),   # e.g. "XB12345"
        "app_id":       os.getenv("FYERS_APP_ID",       ""),   # e.g. "XB12345-100"  (client_id + "-100")
        "secret_key":   os.getenv("FYERS_SECRET_KEY",   ""),
        "redirect_uri": os.getenv("FYERS_REDIRECT_URI",
                        "https://trade.fyers.in/api-login/redirect-uri/index.html"),
        "access_token": os.getenv("FYERS_ACCESS_TOKEN", ""),   # filled after OAuth
        "token_expiry": os.getenv("FYERS_TOKEN_EXPIRY", ""),   # ISO datetime of expiry
    },
    "dhan": {
        "client_id":    os.getenv("DHAN_CLIENT_ID",    ""),
        "access_token": os.getenv("DHAN_ACCESS_TOKEN", ""),
    },
    "kite": {
        "api_key":      os.getenv("KITE_API_KEY",      ""),
        "api_secret":   os.getenv("KITE_API_SECRET",   ""),
        "access_token": os.getenv("KITE_ACCESS_TOKEN", ""),
    },
    "upstox": {
        "api_key":      os.getenv("UPSTOX_API_KEY",    ""),
        "api_secret":   os.getenv("UPSTOX_API_SECRET", ""),
        "redirect_uri": os.getenv("UPSTOX_REDIRECT_URI", "http://localhost:8888/callback"),
        "access_token": os.getenv("UPSTOX_ACCESS_TOKEN", ""),
    },
}
BROKER_CONFIG = BROKER_CREDENTIALS   # backwards compat alias

# Credentials save file
CREDENTIALS_FILE = os.getenv("CREDENTIALS_FILE", "auth/credentials.json")

# Trading halt flag — presence of this file blocks all order placement (survives restarts)
TRADING_HALT_FILE = os.path.join(os.path.dirname(__file__), "auth", "trading.halt")

# ─────────────────────────────────────────────────────────────────
# DEVELOPER MODE
# Set False when distributing to clients — hides internal tools
# like the ML Report tab.
# ─────────────────────────────────────────────────────────────────
DEVELOPER_MODE = True

# ─────────────────────────────────────────────────────────────────
# INDICES
# ─────────────────────────────────────────────────────────────────
INDICES = ["NIFTY", "BANKNIFTY", "MIDCPNIFTY", "SENSEX"]

SYMBOL_MAP = {
    "NIFTY": {
        "spot_symbol":   "NSE:NIFTY50-INDEX",
        "lot_size":      65,    # SEBI revised — updated Mar 2026
        "strike_gap":    50,
        "dhan_security_id": "13",
        "kite_symbol":   "NIFTY 50",
        "upstox_symbol": "NSE_INDEX|Nifty 50",
    },
    "BANKNIFTY": {
        "spot_symbol":   "NSE:NIFTYBANK-INDEX",
        "lot_size":      30,    # SEBI revised — updated Mar 2026
        "strike_gap":    100,
        "dhan_security_id": "25",
        "kite_symbol":   "NIFTY BANK",
        "upstox_symbol": "NSE_INDEX|Nifty Bank",
    },
    "MIDCPNIFTY": {
        "spot_symbol":   "NSE:NIFTYMIDCPSEL-INDEX",
        "lot_size":      120,   # SEBI revised — updated Mar 2026
        "strike_gap":    25,
        "dhan_security_id": "27",
        "kite_symbol":   "NIFTY MIDCAP SELECT",
        "upstox_symbol": "NSE_INDEX|NIFTY MIDCAP SELECT",
    },
    "SENSEX": {
        "spot_symbol":   "BSE:SENSEX-INDEX",
        "lot_size":      20,    # SEBI revised — updated Mar 2026
        "strike_gap":    100,
        "dhan_security_id": "",
        "kite_symbol":   "SENSEX",
        "upstox_symbol": "BSE_INDEX|SENSEX",
    },
}

# ─────────────────────────────────────────────────────────────────
# TIMEFRAME
# ─────────────────────────────────────────────────────────────────
CANDLE_INTERVAL_MINUTES      = 3
DATA_FETCH_INTERVAL_SECONDS  = 5
CANDLE_HISTORY_COUNT         = 125  # full trading day (9:15–15:30 at 3-min = 125 bars)

# ─────────────────────────────────────────────────────────────────
# MULTI-TIMEFRAME (MTF)
# 5-min and 15-min candles fetched separately for trend alignment.
# MTF scores the signal — does NOT block it.
# ─────────────────────────────────────────────────────────────────
MTF_5M_HISTORY_COUNT         = 80   # 5-min candles  (~6.5 hrs)
MTF_15M_HISTORY_COUNT        = 30   # 15-min candles (~7.5 hrs)
MTF_SCORE_BONUS              = 15.0 # confidence boost when both TFs agree
MTF_SCORE_PARTIAL_BONUS      =  7.0 # boost when one TF agrees
MTF_SCORE_WEAK_PENALTY       =  7.0 # reduction when one TF opposes
MTF_SCORE_OPPOSING_PENALTY   = 12.0 # reduction when both TFs oppose
MTF_MIN_ADX                  = 15.0 # min ADX on higher TF to call it directional

# How often to refresh option chain data (seconds).
# Must be >= DATA_FETCH_INTERVAL_SECONDS.
# Lower = more accurate OI signals, higher = fewer API calls.
OC_REFRESH_INTERVAL_SECONDS  = 15

# Option chain data older than this (seconds) is treated as stale
# by the OptionChainDetector and returns a neutral result.
OC_STALENESS_THRESHOLD_SEC   = 60
OC_MIN_ATM_OI                = 50_000  # min ATM OI to treat OI-change signals as valid

# ─────────────────────────────────────────────────────────────────
# DATA RETENTION
# How many trading days of historical snapshots to keep in the DB.
# Older rows are purged on startup and once per day.
# ─────────────────────────────────────────────────────────────────
OC_RETENTION_DAYS            = 5   # option chain snapshots
CANDLE_RETENTION_DAYS        = 10  # market candle rows (longer — used by ML)
ENGINE_SIGNAL_RETENTION_DAYS = 5   # engine_signals rows
OPTION_EOD_RETENTION_DAYS    = 30  # option_eod_prices — 1 month of strike-level data
OPTION_PRICE_HISTORY_RETENTION_DAYS = 30  # option_price_history — per-tick LTP paths
ALERT_RETENTION_DAYS         = 180  # alerts — 6 months; ML training label source
ML_FEATURE_RETENTION_DAYS    = 180  # ml_feature_store — 6 months of feature rows
TRADE_OUTCOME_RETENTION_DAYS = 365  # trade_outcomes — 1 year of outcome history

# ─────────────────────────────────────────────────────────────────
# EXPIRY / PRE-EXPIRY
# On expiry day signals become noisy after 13:30 (position squaring).
# PRE_EXPIRY_COLLECTION_DAYS — how many days before expiry to ensure
# intraday OC snapshots are captured (data is always collected, but
# this drives any pre-expiry-specific logic).
# ─────────────────────────────────────────────────────────────────
EXPIRY_DAY_SIGNAL_END_TIME   = "14:45"   # earlier cutoff on expiry day
PRE_EXPIRY_COLLECTION_DAYS   = 5         # start heightened retention N days before

# ─────────────────────────────────────────────────────────────────
# ENGINE THRESHOLDS — Engine 1: Compression
# ─────────────────────────────────────────────────────────────────
COMPRESSION_CANDLE_LOOKBACK  = 5    # 5 × 3-min = 15 min lookback — enough to detect coiling
                                    # without being fooled by single wide candles
COMPRESSION_RANGE_RATIO      = 0.70 # Each candle's high-low range must be ≤70% of the
                                    # prior candle's range → progressive narrowing pattern.
                                    # 0.70 tuned on NIFTY 3-min data: tighter (0.60) misses
                                    # valid compressions; looser (0.80) fires on random drift.
ATR_PERIOD                   = 14   # Wilder's original ATR period — industry standard;
                                    # matches ADX_PERIOD so both use the same smoothing window
ATR_DECLINING_LOOKBACK       = 3    # ATR must decline for 3 consecutive bars = confirmed energy
                                    # compression, not a one-bar fluke

# ─────────────────────────────────────────────────────────────────
# ENGINE THRESHOLDS — Engine 2: DI Momentum
# ─────────────────────────────────────────────────────────────────
ADX_PERIOD                       = 14   # Wilder's original smoothing period — widely accepted
                                        # for Indian index futures; shorter periods are too noisy
DI_RISING_LOOKBACK               = 3    # +DI must be rising for 3 bars = confirmed momentum build,
                                        # not a single-candle spike from news reaction
DI_SPREAD_WIDENING_THRESHOLD     = 2.0  # Absolute: |+DI − -DI| must widen by ≥2 points per bar.
                                        # On NIFTY 3-min, a spread change < 2 pts is within noise.
DI_SPREAD_PCT_THRESHOLD          = 0.15 # Relative: spread must widen by ≥15% of itself each bar.
                                        # Used when spread is already large (e.g. +DI=35, -DI=10)
                                        # — absolute threshold too easy to meet at high spreads.

# ─────────────────────────────────────────────────────────────────
# ENGINE THRESHOLDS — Engine 3: Option Chain
# ─────────────────────────────────────────────────────────────────
ATM_STRIKE_RANGE              = 15    # Strikes within ±15 points of spot treated as ATM.
                                      # NIFTY strike_gap=50, so this captures the nearest strike only.
                                      # BANKNIFTY strike_gap=100 — ±15 still catches the correct ATM.
PCR_BULLISH_THRESHOLD         = 1.2   # PCR > 1.2 = excess put writing → market makers are bullish.
                                      # NSE historical: PCR > 1.2 precedes up-moves ~62% of time.
PCR_BEARISH_THRESHOLD         = 0.8   # PCR < 0.8 = excess call writing → market makers are bearish.
                                      # Symmetric to bullish threshold; 0.8 chosen to avoid neutral zone.
OI_CHANGE_SIGNIFICANCE        = 0.03  # OI must change by ≥3% intraday to be considered meaningful.
                                      # Recalibrated from 10% (day-over-day) to 3% (intraday) — intraday
                                      # OI builds in smaller increments than EOD comparison.
OI_BUILDUP_LOOKBACK           = 3     # OI buildup tracked over 3 OC refreshes (~45s) to confirm
                                      # sustained institutional positioning, not a one-tick anomaly.

# ─────────────────────────────────────────────────────────────────
# ENGINE THRESHOLDS — Engine 4: Volume Pressure
# ─────────────────────────────────────────────────────────────────
VOLUME_AVERAGE_PERIOD         = 20   # 20-bar SMA of futures volume ≈ 1 full trading hour at 3-min.
                                     # Long enough to smooth session-start volume spike; short enough
                                     # to adapt to afternoon session volume profile shift.
VOLUME_SPIKE_MULTIPLIER       = 1.5  # Current bar volume must be ≥1.5× the 20-bar average.
                                     # 1.5 = validated in live testing: +10% WR boost over trending alone.
                                     # Lower (1.2) fires on normal fluctuation; higher (2.0) too rare.
SMALL_CANDLE_THRESHOLD        = 0.5  # Candle body < 0.5× ATR = indecision / doji — not a clean signal.
                                     # Used to reject volume spikes on pin bars and spinning tops.

# ─────────────────────────────────────────────────────────────────
# ENGINE THRESHOLDS — Engine 5: Liquidity Sweep / Trap
# ─────────────────────────────────────────────────────────────────
LIQUIDITY_SWEEP_LOOKBACK      = 10    # Look back 10 candles (30 min) to identify swing high/low.
                                      # Retail stop clusters form at obvious recent highs/lows.
                                      # 10 bars captures the current session micro-structure without
                                      # extending into the previous session's levels (which need different
                                      # context — prior session highs are handled by S11 setup instead).
LIQUIDITY_WICK_RATIO          = 0.50  # Wick must be ≥50% of candle's total range to qualify as a sweep.
                                      # A 50% wick = candle spent at least half its range above/below
                                      # the swing level before reversing — clear stop-hunt signature.
                                      # Below 50%: normal candle rejection, not a confirmed sweep.

# ─────────────────────────────────────────────────────────────────
# ENGINE THRESHOLDS — Engine 6: Gamma Levels
# ─────────────────────────────────────────────────────────────────
GAMMA_WALL_PROXIMITY_PCT      = 0.002  # Spot must be within 0.2% of the gamma wall strike to trigger.
                                       # NIFTY at 22,500 → ±45 points proximity zone.
                                       # Tightened from 0.5% (too wide — fired 10+ bars early before
                                       # price actually reached the wall and MM delta hedging kicked in).
GAMMA_FLIP_PROXIMITY_PCT      = 0.002  # Same 0.2% zone for gamma flip detection (net gamma sign change).
                                       # Gamma flip = MMs switch from stabilising to amplifying moves —
                                       # a directional catalyst. 0.2% ensures we catch the transition,
                                       # not noise 100 points away from the flip level.

# ─────────────────────────────────────────────────────────────────
# ENGINE THRESHOLDS — Engine 7: IV Expansion
# ─────────────────────────────────────────────────────────────────
IV_EXPANSION_THRESHOLD        = 0.10  # ATM IV must rise by ≥10% (relative) within the OC refresh window.
                                      # Example: IV moves from 12% → 13.2% = 10% rise → triggers.
                                      # Below 10%: normal bid-ask spread fluctuation, not real IV expansion.
                                      # Engine is data-only (ML feature); does not block/trigger signals alone.
IV_SKEW_THRESHOLD             = 1.15  # put_iv / call_iv ≥ 1.15 = put skew → bearish smart-money positioning.
                                      # put_iv / call_iv ≤ 0.87 (1/1.15) = call skew → bullish positioning.
                                      # 1.15 chosen so normal vol surface noise (±10%) doesn't create false skew.
                                      # Source: NIFTY options vol surface analysis — typical put premium ~8-12%.

# ─────────────────────────────────────────────────────────────────
# ENGINE THRESHOLDS — Engine 8: Market Regime
# ─────────────────────────────────────────────────────────────────
REGIME_ADX_TRENDING           = 25.0  # Wilder's original "strong trend" level for ADX.
                                      # ADX ≥ 25 = directional conviction; 20–25 = developing trend.
                                      # Used as primary trending gate: only strong confirmed trends fire.
REGIME_ADX_RANGING            = 20.0  # Secondary check: ADX < 20 = trend too weak → market ranging.
                                      # Wilder's convention: below 20 is "no trend" territory.
                                      # Kept separate from TRADE_SIGNAL_MIN_ADX (which is a signal gate,
                                      # not a regime classification).
REGIME_ATR_VOLATILE_MULT      = 1.5   # current ATR ÷ 20-bar avg ATR ≥ 1.5 = volatile regime.
                                      # 1.5× = 50% above normal volatility — significant enough to
                                      # indicate market stress (news, event, spike), not random widening.

# Choppiness Index (replaces ADX for ranging detection — 1-2 candle response vs. ADX 5-10 lag)
# Formula: 100 × log10(Σ TR(1,n) / (HH_n − LL_n)) / log10(n)
# Scale is always 0–100; independent of price level.
CHOP_PERIOD                   = 14    # Matches ATR_PERIOD and ADX_PERIOD for consistent smoothing window
CHOP_RANGING_THRESHOLD        = 61.8  # CHOP > 61.8 → choppy/ranging market.
                                      # 61.8 = Fibonacci ratio (1 − 0.382). Widely used in CHOP literature
                                      # as the "random walk" boundary above which trend is absent.
CHOP_TRENDING_THRESHOLD       = 38.2  # CHOP < 38.2 → strongly trending market.
                                      # 38.2 = Fibonacci ratio (complementary to 61.8).
                                      # Below this, directional energy is highly concentrated.

# ─────────────────────────────────────────────────────────────────
# SIGNAL LOGIC
# ─────────────────────────────────────────────────────────────────
MIN_ENGINES_FOR_ALERT         = 3   # lowered from 4 — captures more pre-signal ML data
                                    # without lowering the trading bar (signal gate stays at 4)
MIN_ENGINES_FOR_SIGNAL        = 4   # data shows 4 engines outperform 5 (59.8% vs 38.6%)

# Index-level signal filters (based on 1794-sample win rate analysis)
SIGNAL_BLOCKED_INDICES        = []  # collecting data for all indices before deciding
SIGNAL_STRICT_INDICES         = ["SENSEX"]     # 38.4% win — require higher confidence
SIGNAL_STRICT_MIN_CONFIDENCE  = 60.0           # min confidence% for strict indices

# Quality gates for trade signal confirmation (data-driven thresholds)
SIGNAL_MIN_PCR                = 0.7   # PCR < 0.7 = 11% win rate, block

# Forming-candle guard: block Trade Signal if we are still in the first
# fraction of the current candle — volume/range are too incomplete to trust.
# 0.33 = first 1 minute of a 3-min candle is excluded.
SIGNAL_MIN_CANDLE_COMPLETION  = 0.33

# Early Alert expiry: an alert older than this many candles cannot escalate to
# a Trade Signal — prevents stale alerts firing on a new unrelated breakout.
ALERT_MAX_AGE_CANDLES         = 3   # 3 × 3-min = 9 minutes

# MTF blocking: when both 5-min and 15-min timeframes oppose the signal
# direction (alignment = "OPPOSING"), block Trade Signal escalation.
# Early Alerts still pass — only Trade Signals (higher commitment) are blocked.
MTF_BLOCK_ON_OPPOSING         = True

# ── Trade Signal Quality Gates ────────────────────────────────────
# Data-driven thresholds derived from 32-trade outcome analysis:
#   - ADX < 20 on MIDCP 10:23 trade (15.89) = weak trend, SL hit immediately
#   - DI spread was -3.4 on a BULLISH signal = -DI actually > +DI (bearish conviction)
#   - MTF PARTIAL (only 1 TF agreed) vs STRONG (both agreed) = clear quality split
TRADE_SIGNAL_MIN_ADX          = 20.0   # Min ADX on 3m candle — below this trend is too weak
TRADE_SIGNAL_MIN_DI_SPREAD    = 5.0    # Min |DI spread| in signal direction (+DI>-DI for BULLISH)
TRADE_SIGNAL_REQUIRE_MTF_STRONG = True  # Require STRONG MTF (both 5m+15m agree); PARTIAL/NEUTRAL blocked

# ── Trending Regime Gate (tested: 55.8% WR vs 12.8% base = 4.37x lift) ────
# When True, Trade Signals only fire when market_regime = TRENDING.
# AMBIGUOUS / RANGING / VOLATILE regimes are blocked.
# Set False to collect more ML data; set True for live trading quality.
REQUIRE_TRENDING_REGIME       = True

# ── Volume Confirmation Gate (tested: +10% WR boost over trending alone) ──
# Minimum volume_ratio for a Trade Signal when trending regime is active.
# 1.5 = volume must be 50% above 20-bar average (NIFTY 83% WR at this level).
# 0.8 = collect all signals for ML learning (current setting pre-test).
SIGNAL_MIN_VOLUME_RATIO       = 1.5    # raised from 0.8 after 6-day live testing

# ── Index Direction Filter (data-driven, per-index) ────────────────────────
# Restrict certain indices to one direction only based on win-rate analysis.
# BANKNIFTY: bull WR=21-32%, bear WR=71% → bear-only until bull data improves.
# SENSEX:    bull WR=41%,    bear WR=59% → both allowed (no hard block yet).
# Empty string "" = both directions allowed.
INDEX_DIRECTION_FILTER        = {
    "BANKNIFTY": "BEARISH",   # 71% WR bear vs 21-32% bull — block bull signals
}
CONFIDENCE_WEIGHTS = {
    "compression":    15,
    "di_momentum":    20,
    "volume_pressure":15,
    "liquidity_trap": 10,
    "gamma_levels":   10,
    "vwap_pressure":  15,
    "market_regime":  10,
    # data-only — excluded from denominator in signal_aggregator confidence calc:
    "option_chain":   15,
    "iv_expansion":   10,
}
BREAKOUT_ATR_MULTIPLIER       = 1.0   # raised from 0.5 — ATR×0.5 fired on normal candles

# ─────────────────────────────────────────────────────────────────
# TRADE RECOMMENDATION CALIBRATION
# ─────────────────────────────────────────────────────────────────
# Strike selection: above this confidence → suggest 1-strike ITM (delta 0.60-0.65)
# instead of ATM (delta 0.50). ITM has less theta risk for directional trades.
STRONG_TREND_CONFIDENCE       = 65.0

# Expiry day: when DTE (days to expiry) ≤ this, roll suggestion to next expiry.
# Avoids recommending options with heavy theta decay near expiry.
EXPIRY_ROLL_DTE_THRESHOLD     = 1     # Roll when 0 or 1 days to expiry

# Minimum open interest for the suggested option strike.
# If OI is below this, fallback to ATM regardless of confidence.
MIN_OPTION_OI_FOR_TRADE       = 100_000

# Position sizing
# DEFAULT_CAPITAL: total trading capital (INR). Used to size recommended lots.
# RISK_PER_TRADE_PCT: fraction of capital to risk per trade (e.g., 0.01 = 1%).
DEFAULT_CAPITAL               = 500_000   # 5 lakh
RISK_PER_TRADE_PCT            = 0.01      # 1% risk per trade = 5,000 INR
SIGNAL_EXPIRY_CANDLES         = 5

# ─────────────────────────────────────────────────────────────────
# EVENT CALENDAR FILTER
# Blocks TRADE_SIGNAL during high-impact scheduled events (RBI, Fed, Budget).
# Early Move Alerts still fire — ML data collection is unaffected.
# Buffers add extra minutes before/after the event's defined block window.
# ─────────────────────────────────────────────────────────────────
SIGNAL_BLOCK_ON_EVENT     = True  # master switch
EVENT_BLOCK_BEFORE_MINS   = 0     # extra buffer before event block_start
EVENT_BLOCK_AFTER_MINS    = 0     # extra buffer after event block_end
                                  # (windows already include generous coverage)

# ─────────────────────────────────────────────────────────────────
# VIX GATE — DIRECTION-AWARE
#
# WHY direction matters:
#   VIX spikes when the market falls — a BEARISH signal coinciding with
#   high VIX is self-consistent (fear confirms the move direction).
#   A BULLISH signal in high VIX fights the prevailing fear; option
#   premiums (calls) are inflated so the risk/reward is poor.
#
# BULLISH signals (buying calls):
#   Block above 20 — elevated call premiums erode R:R structurally.
#   VIX 12-15: cheap (ideal for buying calls)
#   VIX 15-20: normal (trade with care)
#   VIX > 20 : block — premium too expensive, calls rarely recover SL
#
# BEARISH signals (buying puts):
#   Allow up to 28 — VIX spike IS the bearish move; put premiums are
#   elevated but the market move typically exceeds them on the downside.
#   VIX 20-25: elevated but manageable for puts
#   VIX 25-28: fear-spike zone — puts outperform on sharp falls
#   VIX > 28 : extreme panic; whipsaw risk > directional reward → block
#
# Only TRADE_SIGNAL is blocked — early alerts still fire for ML data.
# ─────────────────────────────────────────────────────────────────
SIGNAL_BLOCK_ON_HIGH_VIX      = True   # master switch
MAX_VIX_FOR_BULLISH_SIGNAL    = 20.0   # calls blocked above this (premium too expensive)
MAX_VIX_FOR_BEARISH_SIGNAL    = 28.0   # puts allowed up to this (VIX spike = fear confirmation)
# ⚠️  DO NOT raise MAX_VIX_FOR_BEARISH_SIGNAL above 30 — above 30 is panic/circuit-breaker
#    territory where even puts gap-down on halt opens and SL becomes unreliable.

# ─────────────────────────────────────────────────────────────────
# MARKET HOURS (IST)
# ─────────────────────────────────────────────────────────────────
ENFORCE_MARKET_HOURS  = True        # Set False for mock/testing
SIGNAL_START_TIME     = "09:20"     # No signals before this (capture early setups)
SIGNAL_END_TIME       = "15:00"     # No new signals after this
MARKET_OPEN_TIME      = "09:15"
MARKET_CLOSE_TIME     = "15:30"


# ─────────────────────────────────────────────────────────────────
# SENSITIVITY LEVELS
# ─────────────────────────────────────────────────────────────────
SENSITIVITY_LEVELS = {
    "HIGH (3+)":      3,
    "BALANCED (4+)":  4,
    "PRECISION (5+)": 5,
    "ULTRA (6+)":     6,
}

# ─────────────────────────────────────────────────────────────────
# FUTURES VOLUME (for volume-based engines)
# Index spot has no real volume in Indian markets.
# Use near-month futures for actual institutional volume.
# ─────────────────────────────────────────────────────────────────
USE_FUTURES_VOLUME    = True        # Replace spot volume with futures volume
FUTURES_SYMBOL_PREFIX = {
    "NIFTY":      "NSE:NIFTY",
    "BANKNIFTY":  "NSE:BANKNIFTY",
    "MIDCPNIFTY": "NSE:MIDCPNIFTY",
    "SENSEX":     "BSE:SENSEX",
}

# ─────────────────────────────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────────────────────────────
DB_PATH  = os.getenv("DB_PATH", os.path.join(os.path.dirname(__file__), "nifty_trader.db"))
DB_ECHO  = False

# ─────────────────────────────────────────────────────────────────
# ML SETTINGS
# ─────────────────────────────────────────────────────────────────
ML_MIN_SAMPLES_TO_ACTIVATE    = 200   # Min labeled samples before training; raised from 100
                                      # (XGBoost 200-tree/depth-4 needs ≥200 to avoid overfit)
ML_RETRAIN_INTERVAL_SAMPLES   = 50    # Retrain every N new labeled samples
ML_LOOKAHEAD_CANDLES          = 5     # Label lookahead window
ML_VALID_MOVE_ATR_MULT        = 0.8   # Min move (×ATR) to label as valid
AUTO_LABEL_INTERVAL_SECONDS   = 900   # AutoLabeler runs every 15 min (was 3600 = 1 hr)
ML_SIGNAL_GATE_THRESHOLD      = 0.50  # Min ML probability to allow trade signal (Phase 2 only)

# Session-specific ML gate thresholds — keyed by session integer (matches signal_aggregator).
# Opening (1) and closing (4) sessions are noisier: raise bar to 0.55.
# Morning (2) and midday (3) are steadier: use base threshold 0.50.
# Pre-market (0) rarely fires — use strict 0.55 as a safe fallback.
# Override ML_SIGNAL_GATE_THRESHOLD per-session; falls back to global if key missing.
ML_SESSION_GATE_THRESHOLDS: dict = {
    0: 0.55,   # pre-open     — rare + unreliable
    1: 0.55,   # opening      — first 15 min whippy, higher noise
    2: 0.50,   # morning      — best quality window
    3: 0.50,   # midday       — steady, base threshold
    4: 0.52,   # closing      — some reversal risk, slight raise
}

# ─────────────────────────────────────────────────────────────────
# OUTCOME TRACKING
# ATR multipliers used to compute spot-level SL/T1/T2/T3 from
# entry spot price — must match _build_trade_signal multipliers.
# ─────────────────────────────────────────────────────────────────
OUTCOME_SL_ATR_MULT  = 0.8    # SL  = entry ∓ ATR × 0.8
OUTCOME_T1_ATR_MULT  = 1.0    # T1  = entry ± ATR × 1.0
OUTCOME_T2_ATR_MULT  = 1.5    # T2  = entry ± ATR × 1.5
OUTCOME_T3_ATR_MULT  = 2.2    # T3  = entry ± ATR × 2.2
OUTCOME_EOD_TIME     = "15:30" # Close all open trades at market close (IST)

# BUG-3 fix: time-adjusted labeling for option trades.
# An option that hits T1 after 15+ minutes (5+ candles) has lost significant
# theta (premium decay) — the label should reflect that it was a marginal win,
# not a clean signal. T3 hits are always WIN regardless of time.
OPTION_WIN_T1_MAX_CANDLES = 5   # T1-only wins beyond this candle count → label = 0
OPTION_WIN_T2_MAX_CANDLES = 8   # T2-only wins beyond this candle count → label = 0

# ─────────────────────────────────────────────────────────────────
# ALERTS
# ─────────────────────────────────────────────────────────────────
SOUND_ALERTS_ENABLED          = True
POPUP_ALERTS_ENABLED          = True
TELEGRAM_ENABLED = os.getenv("TELEGRAM_ENABLED", "false").lower() == "true"
TELEGRAM_BOT_TOKEN            = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID              = os.getenv("TELEGRAM_CHAT_ID",   "")

# ─────────────────────────────────────────────────────────────────
# UI
# ─────────────────────────────────────────────────────────────────
UI_REFRESH_INTERVAL_MS        = 1000
ALERT_FLASH_DURATION_MS       = 3000

# ─────────────────────────────────────────────────────────────────
# MOCK DATA
# ─────────────────────────────────────────────────────────────────
MOCK_BASE_PRICES = {
    "NIFTY":     22500.0,
    "BANKNIFTY": 48000.0,
    "MIDCPNIFTY":11000.0,
    "SENSEX":    75000.0,
}
MOCK_VOLATILITY = {
    "NIFTY":     0.001,
    "BANKNIFTY": 0.0015,
    "MIDCPNIFTY":0.0012,
    "SENSEX":    0.001,
}

# ─────────────────────────────────────────────────────────────────
# AUTO TRADING (Layer 1 — Fyers bracket orders)
# Off by default — user must enable explicitly via dashboard toggle.
# ─────────────────────────────────────────────────────────────────
AUTO_TRADE_ENABLED            = False  # runtime toggle (not persisted across restarts)
AUTO_TRADE_PAPER_MODE         = False  # True = simulate orders without real placement
AUTO_TRADE_CONFIRMED_ONLY     = True   # True = only trade on candle-close CONFIRMED signals
AUTO_TRADE_MAX_DAILY_ORDERS   = 3      # hard cap: stop placing orders after this many per day
AUTO_TRADE_MAX_DAILY_LOSS     = 10000  # ₹ max realized loss per day before auto-halt
                                       # e.g. 10000 = stop if cumulative closed-trade loss ≥ ₹10k
AUTO_TRADE_MIN_CONFIDENCE     = 46.0   # min confidence % to auto-trade
AUTO_TRADE_MIN_ENGINES        = 4      # min engines triggered to auto-trade
AUTO_TRADE_ORDER_TYPE         = 1      # Entry is always LIMIT (SEBI rule for index options)
AUTO_TRADE_LOT_MULTIPLIER     = 1      # multiply recommended_lots by this (1 = as recommended)
AUTO_TRADE_FIXED_LOTS         = 1      # fixed lots per trade (overrides position-sizing when > 0)
# If a LIMIT entry is not filled within this many seconds, cancel and re-enter
# once at the fresh market LTP.  Set high (e.g. 60) if you prefer to wait.
AUTO_TRADE_FILL_TIMEOUT_SECONDS = 30   # 30 s = roughly 2 candle ticks at 15-s poll
# BO (bracket order) settings — SL and TP are offsets from the fill price
# These are only used when ORDER_TYPE=2 (market); for limit orders the
# entry_reference price is used and offset is computed relative to that.
AUTO_TRADE_SL_BUFFER          = 0.0    # extra buffer on SL offset (in points); 0 = exact SL
AUTO_TRADE_TP_BUFFER          = 0.0    # extra buffer on TP offset (in points); 0 = exact T1

# ─────────────────────────────────────────────────────────────────
# ENGINE THRESHOLDS — Engine 9: VWAP Pressure
# ─────────────────────────────────────────────────────────────────
VWAP_TOUCH_ATR_MULT           = 0.5    # within 0.5×ATR counts as a VWAP touch
VWAP_TOUCH_PCT_MIN            = 0.003  # minimum 0.3% band (for low-ATR environments)
VWAP_BODY_MIN_RATIO           = 0.35   # candle body must be ≥35% of range
VWAP_VOL_RATIO_MIN            = 1.2    # volume must be 1.2× average for VWAP signal

# ─────────────────────────────────────────────────────────────────
# S11 SETUP THRESHOLDS
# ─────────────────────────────────────────────────────────────────
S11_VOLUME_RATIO_MIN          = 1.5    # volume_ratio >= 1.5 required for S11 condition

# ─────────────────────────────────────────────────────────────────
# RISK-FREE RATE (India 10Y / RBI repo approximation)
# Used for Black-Scholes IV computation.
# ─────────────────────────────────────────────────────────────────
RISK_FREE_RATE                = 0.065  # 6.5%
