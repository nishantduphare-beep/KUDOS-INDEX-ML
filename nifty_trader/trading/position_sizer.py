"""
Position Sizing Calculator — Calculate safe position size based on account equity and risk.

Uses Kelly Criterion-inspired approach:
  max_loss = equity × risk_percent
  contracts = max_loss / (SL_distance_points × lot_size)
"""

import logging

try:
    import config
except ImportError:
    import nifty_trader.config as config
from typing import Optional

logger = logging.getLogger(__name__)


class PositionSizer:
    """Calculate safe position size given account risk parameters"""
    
    @staticmethod
    def calculate_position_size(
        account_equity: float,
        risk_percent: float = 1.0,
        stop_loss_points: float = 50.0,
        index_name: str = "NIFTY",
    ) -> int:
        """
        Calculate how many contracts to buy given account size & risk.
        
        Args:
            account_equity: Total account value in rupees
            risk_percent: % of equity to risk per trade (default 1%)
            stop_loss_points: Distance to stop-loss in index points
            index_name: NIFTY | BANKNIFTY | etc
        
        Returns:
            Number of contracts (lots) to trade
        
        Example:
            Equity: ₹5,00,000
            Risk: 1% = ₹5,000
            SL distance: 50 points
            NIFTY lot size: 65 (1 point = ₹65 after Mar 2026 revision)
            Position: ₹5,000 / (50 × 65) = ₹5,000 / 3,250 = 1.54 lots → 1 lot
        """
        
        # Validate inputs
        if account_equity <= 0:
            logger.warning(f"Invalid account equity: {account_equity}")
            return 0
        
        if stop_loss_points <= 0:
            logger.warning(f"Invalid SL distance: {stop_loss_points}")
            return 0
        
        # Max loss allowed
        max_loss_rupees = account_equity * (risk_percent / 100)
        logger.debug(f"Max loss: {risk_percent}% × ₹{account_equity:,.0f} = ₹{max_loss_rupees:,.0f}")
        
        # Get lot size from config
        symbol_info = config.SYMBOL_MAP.get(index_name, {})
        lot_size = symbol_info.get('lot_size', 65)  # Default to NIFTY post-Mar-2026
        
        # Per-point value
        per_point_value = lot_size  # 1 point = lot_size rupees
        max_sl_impact = stop_loss_points * per_point_value
        
        logger.debug(
            f"Index: {index_name}, Lot size: {lot_size}, "
            f"SL points: {stop_loss_points}, Max SL impact: ₹{max_sl_impact:,.0f}"
        )
        
        # Calculate contracts
        contracts = int(max_loss_rupees / max_sl_impact)
        
        # Cap to config maximum
        contracts = min(contracts, config.POSITION_SIZE_CONTRACTS)
        contracts = max(1, contracts)  # At least 1 lot
        
        logger.info(
            f"Position size: {contracts} lot(s) "
            f"(equity=₹{account_equity:,.0f}, risk={risk_percent}%, sl={stop_loss_points}pt)"
        )
        
        return contracts
    
    @staticmethod
    def calculate_risk_rupees(
        contracts: int,
        stop_loss_points: float,
        index_name: str = "NIFTY",
    ) -> float:
        """Calculate rupee risk for a given position"""
        
        symbol_info = config.SYMBOL_MAP.get(index_name, {})
        lot_size = symbol_info.get('lot_size', 65)
        
        risk_rupees = contracts * stop_loss_points * lot_size
        return risk_rupees
    
    @staticmethod
    def calculate_reward_rupees(
        contracts: int,
        target_points: float,
        index_name: str = "NIFTY",
    ) -> float:
        """Calculate rupee reward for a given position"""
        
        symbol_info = config.SYMBOL_MAP.get(index_name, {})
        lot_size = symbol_info.get('lot_size', 65)
        
        reward_rupees = contracts * target_points * lot_size
        return reward_rupees
    
    @staticmethod
    def calculate_risk_reward_ratio(
        risk_rupees: float,
        reward_rupees: float,
    ) -> float:
        """Calculate risk:reward ratio"""
        if risk_rupees == 0:
            return 0
        return reward_rupees / risk_rupees


def get_position_size(
    account_equity: float,
    risk_percent: float = 1.0,
    stop_loss_points: float = 50.0,
    index_name: str = "NIFTY",
) -> dict:
    """
    Get complete position sizing information.
    
    Returns dict with:
        - contracts: number of lots
        - risk_rupees: money at risk
        - reward_rupees (if targets provided)
        - ratio
    """
    contracts = PositionSizer.calculate_position_size(
        account_equity, risk_percent, stop_loss_points, index_name
    )
    
    risk_rupees = PositionSizer.calculate_risk_rupees(
        contracts, stop_loss_points, index_name
    )
    
    return {
        'contracts': contracts,
        'risk_rupees': risk_rupees,
        'risk_percent_actual': (risk_rupees / account_equity) * 100 if account_equity > 0 else 0,
    }
