"""
config_validator.py
Validates all config settings on startup. Logs errors but does NOT crash the app
(trading systems must be resilient to config edge cases).
"""
import logging
logger = logging.getLogger(__name__)


def validate_config() -> bool:
    """Validate config settings. Returns True if all checks pass."""
    import config
    errors = []
    warnings = []

    # Broker validation
    valid_brokers = {"fyers", "dhan", "kite", "upstox", "mock"}
    if config.BROKER not in valid_brokers:
        errors.append(f"BROKER='{config.BROKER}' not in {valid_brokers}")

    # Signal engine thresholds
    if not (1 <= config.MIN_ENGINES_FOR_SIGNAL <= 8):
        errors.append(f"MIN_ENGINES_FOR_SIGNAL={config.MIN_ENGINES_FOR_SIGNAL} out of range [1,8]")

    # VIX thresholds
    if hasattr(config, "MAX_VIX_FOR_BULLISH_SIGNAL"):
        if not (10 <= config.MAX_VIX_FOR_BULLISH_SIGNAL <= 50):
            warnings.append(f"MAX_VIX_FOR_BULLISH_SIGNAL={config.MAX_VIX_FOR_BULLISH_SIGNAL} seems extreme")
    if hasattr(config, "MAX_VIX_FOR_BEARISH_SIGNAL"):
        if not (10 <= config.MAX_VIX_FOR_BEARISH_SIGNAL <= 50):
            warnings.append(f"MAX_VIX_FOR_BEARISH_SIGNAL={config.MAX_VIX_FOR_BEARISH_SIGNAL} seems extreme")

    # ML thresholds
    if hasattr(config, "ML_SIGNAL_GATE_THRESHOLD"):
        if not (0.4 <= config.ML_SIGNAL_GATE_THRESHOLD <= 0.9):
            warnings.append(f"ML_SIGNAL_GATE_THRESHOLD={config.ML_SIGNAL_GATE_THRESHOLD} outside typical [0.4, 0.9]")

    if not (50 <= config.ML_MIN_SAMPLES_TO_ACTIVATE <= 10000):
        warnings.append(f"ML_MIN_SAMPLES_TO_ACTIVATE={config.ML_MIN_SAMPLES_TO_ACTIVATE} unusual")

    # Candle interval
    if config.CANDLE_INTERVAL_MINUTES not in {1, 3, 5, 10, 15, 30}:
        warnings.append(f"CANDLE_INTERVAL_MINUTES={config.CANDLE_INTERVAL_MINUTES} is unusual (not a standard interval)")

    for e in errors:
        logger.error(f"Config ERROR: {e}")
    for w in warnings:
        logger.warning(f"Config WARNING: {w}")

    if errors:
        logger.error(f"Config validation FAILED ({len(errors)} errors, {len(warnings)} warnings)")
        return False
    elif warnings:
        logger.warning(f"Config validation passed with {len(warnings)} warnings")
    else:
        logger.info("Config validation: all checks passed")
    return True
