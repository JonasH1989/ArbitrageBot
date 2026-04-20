"""
MEXC Exchange Connector
Fetches orderbook data from MEXC
"""

import asyncio
import aiohttp
import hashlib
import time
from typing import List, Optional
from loguru import logger
from .base import BaseConnector, Orderbook, OrderbookEntry
from .config_manager import get_config


class MexcConnector(BaseConnector):
    """MEXC exchange connector"""
    
    def __init__(self, pair: str = "MPC-USDT"):
        super().__init__(pair)
        self.name = "mexc"
        self.api_key: Optional[str] = None
        self.api_secret: Optional[str] = None
        self._session: Optional[aiohttp.ClientSession] = None
        
        # API endpoints
        self._base_url = "https://api.mexc.com"
    
    async def connect(self):
        """Connect to MEXC API"""
        config = get_config()
        self.api_key = config.get('mexc.api_key')
        self.api_secret = config.get('mexc.api_secret')
        
        self._session = aiohttp.ClientSession()
        self._connected = True
        logger.info(f"[MEXC] Connected to {self._base_url}")
    
    async def disconnect(self):
        """Disconnect from MEXC API"""
        if self._session:
            await self._session.close()
        self._connected = False
        logger.info("[MEXC] Disconnected")
    
    def _format_pair(self, pair: str) -> str:
        """Convert pair format (e.g., MPC-USDT -> MPC_USDT)"""
        return pair.replace('-', '_')
    
    async def get_orderbook(self, limit: int = 100) -> Optional[Orderbook]:
        """
        Get orderbook from MEXC
        
        Args:
            limit: Number of orderbook levels to fetch
            
        Returns:
            Orderbook object with bids and asks
        """
        if not self._connected:
            await self.connect()
        
        formatted_pair = self._format_pair(self.pair)
        url = f"{self._base_url}/api/v3/market/bookTicker"
        params = {"symbol": formatted_pair}
        
        try:
            async with self._session.get(url, params=params) as resp:
                if resp.status != 200:
                    logger.error(f"[MEXC] HTTP {resp.status}")
                    return None
                
                data = await resp.json()
                
                if not data or 'bidQty' not in data:
                    logger.error(f"[MEXC] Invalid response: {data}")
                    return None
                
                # MEXC bookTicker gives us best bid/ask only, not full orderbook
                # We need to use a different endpoint for full orderbook
                return await self._get_orderbook_full(limit)
                
        except Exception as e:
            logger.error(f"[MEXC] Error fetching orderbook: {e}")
            return None
    
    async def _get_orderbook_full(self, limit: int = 100) -> Optional[Orderbook]:
        """Get full orderbook from MEXC using depth endpoint"""
        formatted_pair = self._format_pair(self.pair)
        url = f"{self._base_url}/api/v3/market/orderbook"
        params = {"symbol": formatted_pair, "limit": limit}
        
        try:
            async with self._session.get(url, params=params) as resp:
                if resp.status != 200:
                    logger.error(f"[MEXC] HTTP {resp.status}")
                    return None
                
                data = await resp.json()
                
                if data.get('code') or not data.get('data'):
                    logger.error(f"[MEXC] API Error: {data}")
                    return None
                
                raw_data = data.get('data', {})
                
                # Parse bids (buy orders) - format: [price, quantity]
                bids_raw = raw_data.get('bids', [])
                bids = [
                    OrderbookEntry(
                        price=float(b[0]) if isinstance(b, list) else float(b.get('p', 0)),
                        quantity=float(b[1]) if isinstance(b, list) else float(b.get('q', 0))
                    )
                    for b in bids_raw[:limit]
                ]
                
                # Parse asks (sell orders) - format: [price, quantity]
                asks_raw = raw_data.get('asks', [])
                asks = [
                    OrderbookEntry(
                        price=float(a[0]) if isinstance(a, list) else float(a.get('p', 0)),
                        quantity=float(a[1]) if isinstance(a, list) else float(a.get('q', 0))
                    )
                    for a in asks_raw[:limit]
                ]
                
                return Orderbook(
                    exchange=self.name,
                    pair=self.pair,
                    bids=bids,
                    asks=asks,
                    raw=raw_data
                )
                
        except Exception as e:
            logger.error(f"[MEXC] Error fetching full orderbook: {e}")
            return None
    
    async def get_ticker(self) -> dict:
        """Get current ticker (price info)"""
        if not self._connected:
            await self.connect()
        
        formatted_pair = self._format_pair(self.pair)
        url = f"{self._base_url}/api/v3/market/ticker"
        params = {"symbol": formatted_pair}
        
        try:
            async with self._session.get(url, params=params) as resp:
                if resp.status != 200:
                    return None
                
                data = await resp.json()
                if not data:
                    return None
                
                last_price = float(data.get('lastPrice', 0))
                bid_price = float(data.get('bidPrice', 0))
                ask_price = float(data.get('askPrice', 0))
                
                return {
                    'exchange': self.name,
                    'pair': self.pair,
                    'last_price': last_price,
                    'best_bid': bid_price,
                    'best_ask': ask_price,
                    'mid_price': (bid_price + ask_price) / 2 if bid_price and ask_price else last_price,
                    'spread': ask_price - bid_price if bid_price and ask_price else 0,
                    'spread_pct': ((ask_price - bid_price) / ((bid_price + ask_price) / 2) * 100) if bid_price and ask_price else 0
                }
        except Exception as e:
            logger.error(f"[MEXC] Error fetching ticker: {e}")
            return None


# Singleton instance
_connector: Optional[MexcConnector] = None

async def get_mexc_connector(pair: str = "MPC-USDT") -> MexcConnector:
    """Get MEXC connector instance"""
    global _connector
    if _connector is None:
        _connector = MexcConnector(pair)
        await _connector.connect()
    return _connector
