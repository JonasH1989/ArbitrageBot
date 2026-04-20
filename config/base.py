"""Base classes for exchange connectors"""

from dataclasses import dataclass
from typing import List
from datetime import datetime


@dataclass
class OrderbookEntry:
    """Single orderbook entry"""
    price: float
    quantity: float
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()


@dataclass
class Orderbook:
    """Combined orderbook for both sides"""
    exchange: str
    pair: str
    bids: List[OrderbookEntry]  # Buy orders (what we can sell at)
    asks: List[OrderbookEntry]  # Sell orders (what we can buy at)
    timestamp: datetime = None
    raw: dict = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()
    
    @property
    def best_bid(self) -> float:
        """Highest buy price"""
        return self.bids[0].price if self.bids else 0.0
    
    @property
    def best_ask(self) -> float:
        """Lowest sell price"""
        return self.asks[0].price if self.asks else 0.0
    
    @property
    def mid_price(self) -> float:
        """Mid price between best bid and ask"""
        if self.best_bid and self.best_ask:
            return (self.best_bid + self.best_ask) / 2
        return 0.0
    
    @property
    def spread(self) -> float:
        """Spread between best bid and ask"""
        if self.best_bid and self.best_ask:
            return self.best_ask - self.best_bid
        return 0.0
    
    @property
    def spread_pct(self) -> float:
        """Spread as percentage of mid price"""
        if self.mid_price > 0:
            return (self.spread / self.mid_price) * 100
        return 0.0
    
    def get_volume_at_price(self, side: str, price: float) -> float:
        """Get total volume available at or better than given price"""
        entries = self.bids if side == 'bid' else self.asks
        volume = 0.0
        
        for entry in entries:
            if side == 'bid' and entry.price >= price:
                volume += entry.quantity
            elif side == 'ask' and entry.price <= price:
                volume += entry.quantity
        
        return volume


class BaseConnector:
    """Base class for exchange connectors"""
    
    def __init__(self, pair: str = "MPC-USDT"):
        self.pair = pair
        self._connected = False
    
    async def connect(self):
        """Establish connection to exchange"""
        raise NotImplementedError
    
    async def disconnect(self):
        """Close connection to exchange"""
        raise NotImplementedError
    
    async def get_orderbook(self) -> Orderbook:
        """Get current orderbook"""
        raise NotImplementedError
    
    @property
    def name(self) -> str:
        """Exchange name"""
        raise NotImplementedError
    
    @property
    def is_connected(self) -> bool:
        return self._connected
