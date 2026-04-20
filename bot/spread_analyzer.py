"""
Spread Analyzer
Monitors spreads between KuCoin and MEXC for arbitrage opportunities
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict, Any
from collections import deque
from loguru import logger
from config.base import Orderbook
from config.config_manager import get_config


@dataclass
class ArbitrageOpportunity:
    """Detected arbitrage opportunity"""
    timestamp: datetime
    buy_exchange: str
    sell_exchange: str
    buy_price: float
    sell_price: float
    spread_pct: float
    max_volume: float  # Minimum volume from both orderbooks
    raw_profit_pct: float  # Before fees
    
    def __str__(self):
        return (
            f"[{self.timestamp.strftime('%H:%M:%S')}] "
            f"Buy {self.buy_exchange} @ {self.buy_price:.6f} → "
            f"Sell {self.sell_exchange} @ {self.sell_price:.6f} "
            f"(Spread: {self.spread_pct:.3f}%, Vol: {self.max_volume:.0f} MPC)"
        )


@dataclass
class SpreadSnapshot:
    """Snapshot of spread analysis at a point in time"""
    timestamp: datetime
    kucoin_bid: float
    kucoin_ask: float
    kucoin_bid_vol: float
    kucoin_ask_vol: float
    mexc_bid: float
    mexc_ask: float
    mexc_bid_vol: float
    mexc_ask_vol: float
    
    # Calculated spreads
    kucoin_mid: float = field(init=False)
    kucoin_spread_pct: float = field(init=False)
    mexc_mid: float = field(init=False)
    mexc_spread_pct: float = field(init=False)
    
    # Cross-exchange spreads
    kucoin_buy_mexc_sell: float = 0.0  # Buy MPC on KuCoin, sell on MEXC
    mexc_buy_kucoin_sell: float = 0.0  # Buy MPC on MEXC, sell on KuCoin
    
    # Matched volumes
    kucoin_mexc_vol: float = 0.0  # Volume for cross-exchange trade
    
    def __post_init__(self):
        self.kucoin_mid = (self.kucoin_bid + self.kucoin_ask) / 2 if self.kucoin_bid and self.kucoin_ask else 0
        self.kucoin_spread_pct = ((self.kucoin_ask - self.kucoin_bid) / self.kucoin_mid * 100) if self.kucoin_mid else 0
        self.mexc_mid = (self.mexc_bid + self.mexc_ask) / 2 if self.mexc_bid and self.mexc_ask else 0
        self.mexc_spread_pct = ((self.mexc_ask - self.mexc_bid) / self.mexc_mid * 100) if self.mexc_mid else 0
        
        # Cross-exchange arbitrage calculations
        if self.kucoin_bid and self.mexc_ask:
            # Buy on MEXC (ask), sell on KuCoin (bid)
            self.kucoin_buy_mexc_sell = ((self.kucoin_bid - self.mexc_ask) / self.mexc_ask) * 100
            self.kucoin_mexc_vol = min(self.kucoin_bid_vol, self.mexc_ask_vol)
        
        if self.mexc_bid and self.kucoin_ask:
            # Buy on KuCoin (ask), sell on MEXC (bid)
            self.mexc_buy_kucoin_sell = ((self.mexc_bid - self.kucoin_ask) / self.kucoin_ask) * 100
            self.mexc_buy_kucoin_vol = min(self.mexc_bid_vol, self.kucoin_ask_vol)


class SpreadAnalyzer:
    """
    Analyzes spreads between exchanges and detects arbitrage opportunities
    Implements hysteresis for threshold-based detection
    """
    
    def __init__(self, pair: str = "MPC-USDT"):
        self.pair = pair
        self.config = get_config()
        
        # History buffers
        self.snapshots: deque = deque(maxlen=10000)  # Keep last 10000 snapshots
        self.opportunities: deque = deque(maxlen=1000)  # Keep last 1000 opportunities
        
        # Current state
        self.current_snapshot: Optional[SpreadSnapshot] = None
        self.is_opportunity_active: bool = False
        
        # Statistics
        self.stats = {
            'total_checks': 0,
            'opportunities_found': 0,
            'avg_spread_kucoin_mexc': 0.0,
            'max_spread_observed': 0.0,
            'min_spread_observed': 0.0,
            'opportunities_by_hour': {}
        }
        
        # Trading fees (estimated)
        self.fees = {
            'kucoin': {'maker': 0.1, 'taker': 0.1},  # percentages
            'mexc': {'maker': 0.0, 'taker': 0.2}  # MEXC has 0% maker for spot
        }
    
    def get_thresholds(self) -> Dict[str, float]:
        """Get current threshold settings"""
        return self.config.get_thresholds()
    
    def calculate_net_profit(self, spread_pct: float, buy_exchange: str, sell_exchange: str) -> float:
        """
        Calculate net profit after fees
        
        Args:
            spread_pct: Raw spread percentage
            buy_exchange: Where we buy
            sell_exchange: Where we sell
            
        Returns:
            Net profit percentage after fees
        """
        buy_fee = self.fees.get(buy_exchange, {}).get('taker', 0.1)
        sell_fee = self.fees.get(sell_exchange, {}).get('taker', 0.1)
        
        gross_profit = spread_pct
        total_fees = buy_fee + sell_fee
        net_profit = gross_profit - total_fees
        
        return net_profit
    
    def analyze_orderbooks(self, kucoin_ob: Orderbook, mexc_ob: Orderbook) -> SpreadSnapshot:
        """
        Analyze orderbooks from both exchanges and calculate spreads
        
        Returns:
            SpreadSnapshot with all calculations
        """
        snapshot = SpreadSnapshot(
            timestamp=datetime.now(),
            kucoin_bid=kucoin_ob.best_bid,
            kucoin_ask=kucoin_ob.best_ask,
            kucoin_bid_vol=kucoin_ob.bids[0].quantity if kucoin_ob.bids else 0,
            kucoin_ask_vol=kucoin_ob.asks[0].quantity if kucoin_ob.asks else 0,
            mexc_bid=mexc_ob.best_bid,
            mexc_ask=mexc_ob.best_ask,
            mexc_bid_vol=mexc_ob.bids[0].quantity if mexc_ob.bids else 0,
            mexc_ask_vol=mexc_ob.asks[0].quantity if mexc_ob.asks else 0
        )
        
        self.current_snapshot = snapshot
        self.snapshots.append(snapshot)
        self.stats['total_checks'] += 1
        
        # Check for arbitrage opportunities
        self._check_opportunity(snapshot)
        
        # Update statistics
        self._update_stats(snapshot)
        
        return snapshot
    
    def _check_opportunity(self, snapshot: SpreadSnapshot):
        """Check if current snapshot represents an arbitrage opportunity with hysteresis"""
        thresholds = self.get_thresholds()
        start_threshold = thresholds['start']
        stop_threshold = thresholds['stop']
        
        # Check both directions
        opportunities = []
        
        # Direction 1: Buy MEXC, Sell KuCoin
        if snapshot.kucoin_buy_mexc_sell > 0:
            net_profit = self.calculate_net_profit(
                snapshot.kucoin_buy_mexc_sell,
                'mexc', 'kucoin'
            )
            
            if net_profit > 0:
                opp = ArbitrageOpportunity(
                    timestamp=snapshot.timestamp,
                    buy_exchange='mexc',
                    sell_exchange='kucoin',
                    buy_price=snapshot.mexc_ask,
                    sell_price=snapshot.kucoin_bid,
                    spread_pct=net_profit,
                    max_volume=snapshot.kucoin_mexc_vol,
                    raw_profit_pct=snapshot.kucoin_buy_mexc_sell
                )
                opportunities.append(opp)
        
        # Direction 2: Buy KuCoin, Sell MEXC
        if hasattr(snapshot, 'mexc_buy_kucoin_sell') and snapshot.mexc_buy_kucoin_sell > 0:
            net_profit = self.calculate_net_profit(
                snapshot.mexc_buy_kucoin_sell,
                'kucoin', 'mexc'
            )
            
            if net_profit > 0:
                opp = ArbitrageOpportunity(
                    timestamp=snapshot.timestamp,
                    buy_exchange='kucoin',
                    sell_exchange='mexc',
                    buy_price=snapshot.kucoin_ask,
                    sell_price=snapshot.mexc_bid,
                    spread_pct=net_profit,
                    max_volume=getattr(snapshot, 'mexc_buy_kucoin_vol', 0),
                    raw_profit_pct=snapshot.mexc_buy_kucoin_sell
                )
                opportunities.append(opp)
        
        # Apply hysteresis logic
        if opportunities and not self.is_opportunity_active:
            # Check if best opportunity exceeds start threshold
            best_opp = max(opportunities, key=lambda x: x.spread_pct)
            if best_opp.spread_pct >= start_threshold:
                self.is_opportunity_active = True
                self.opportunities.append(best_opp)
                self.stats['opportunities_found'] += 1
                logger.info(f"🚀 ARBITRAGE OPPORTUNITY: {best_opp}")
        
        elif not opportunities and self.is_opportunity_active:
            # Check if spread dropped below stop threshold
            if len(opportunities) == 0:
                # No opportunity means spread is below threshold
                # Check current spread is below stop threshold
                current_spread = max(
                    snapshot.kucoin_buy_mexc_sell if snapshot.kucoin_buy_mexc_sell > 0 else 0,
                    getattr(snapshot, 'mexc_buy_kucoin_sell', 0)
                )
                
                if current_spread < stop_threshold:
                    self.is_opportunity_active = False
                    logger.info(f"📉 Opportunity ended. Spread: {current_spread:.3f}%")
    
    def _update_stats(self, snapshot: SpreadSnapshot):
        """Update running statistics"""
        # Update max/min spread
        current_spread = max(
            snapshot.kucoin_buy_mexc_sell if snapshot.kucoin_buy_mexc_sell > 0 else 0,
            getattr(snapshot, 'mexc_buy_kucoin_sell', 0)
        )
        
        if current_spread > 0:
            if self.stats['max_spread_observed'] == 0 or current_spread > self.stats['max_spread_observed']:
                self.stats['max_spread_observed'] = current_spread
            
            if self.stats['min_spread_observed'] == 0 or current_spread < self.stats['min_spread_observed']:
                self.stats['min_spread_observed'] = current_spread
        
        # Update average
        total = self.stats['total_checks']
        current_avg = self.stats['avg_spread_kucoin_mexc']
        self.stats['avg_spread_kucoin_mexc'] = ((current_avg * (total - 1)) + current_spread) / total
        
        # Hourly distribution
        hour_key = snapshot.timestamp.strftime('%Y-%m-%d %H:00')
        if hour_key not in self.stats['opportunities_by_hour']:
            self.stats['opportunities_by_hour'][hour_key] = 0
        if self.is_opportunity_active:
            self.stats['opportunities_by_hour'][hour_key] += 1
    
    def get_summary(self) -> Dict[str, Any]:
        """Get current analysis summary"""
        return {
            'current_snapshot': self.current_snapshot,
            'is_opportunity_active': self.is_opportunity_active,
            'stats': self.stats,
            'recent_opportunities': list(self.opportunities)[-10:],
            'thresholds': self.get_thresholds()
        }
    
    def get_chart_data(self, last_n: int = 100) -> Dict[str, List]:
        """Get data for charting"""
        snapshots = list(self.snapshots)[-last_n:]
        
        return {
            'timestamps': [s.timestamp.isoformat() for s in snapshots],
            'kucoin_bid': [s.kucoin_bid for s in snapshots],
            'kucoin_ask': [s.kucoin_ask for s in snapshots],
            'mexc_bid': [s.mexc_bid for s in snapshots],
            'mexc_ask': [s.mexc_ask for s in snapshots],
            'kucoin_buy_mexc_sell': [s.kucoin_buy_mexc_sell for s in snapshots],
            'mexc_buy_kucoin_sell': [getattr(s, 'mexc_buy_kucoin_sell', 0) for s in snapshots],
        }
