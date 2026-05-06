"""
KuCoin Exchange Connector
Fetches orderbook data from KuCoin
"""

import asyncio
import time
import aiohttp
from typing import List, Optional
from loguru import logger
from .base import BaseConnector, Orderbook, OrderbookEntry
from .config_manager import get_config


class KuCoinConnector(BaseConnector):
    """KuCoin exchange connector"""
    
    def __init__(self, pair: str = "MPC-USDT"):
        super().__init__(pair)
        self.name = "kucoin"
        self.api_key: Optional[str] = None
        self.api_secret: Optional[str] = None
        self.api_passphrase: Optional[str] = None
        self.sandbox: bool = False
        self._session: Optional[aiohttp.ClientSession] = None
        
        # API endpoints
        self._base_url = "https://api.kucoin.com"  # Production
        # self._base_url = "https://api-sandbox.kucoin.com"  # Sandbox
    
    async def connect(self):
        """Connect to KuCoin API"""
        config = get_config()
        self.api_key = config.get('kucoin.api_key')
        self.api_secret = config.get('kucoin.api_secret')
        self.api_passphrase = config.get('kucoin.api_passphrase')
        self.sandbox = config.get('kucoin.sandbox', False)
        
        if self.sandbox:
            self._base_url = "https://api-sandbox.kucoin.com"
        
        self._session = aiohttp.ClientSession()
        self._connected = True
        logger.info(f"[KuCoin] Connected to {self._base_url}")
    
    async def disconnect(self):
        """Disconnect from KuCoin API"""
        if self._session:
            await self._session.close()
        self._connected = False
        logger.info("[KuCoin] Disconnected")
    
    def _format_pair(self, pair: str) -> str:
        """Convert pair format (e.g., MPC-USDT -> MPC-USDT)"""
        return pair.replace('/', '-')
    
    async def get_orderbook(self, limit: int = 100) -> Orderbook:
        """
        Get orderbook from KuCoin
        
        Args:
            limit: Number of orderbook levels to fetch
            
        Returns:
            Orderbook object with bids and asks
        """
        if not self._connected:
            await self.connect()
        
        formatted_pair = self._format_pair(self.pair)
        url = f"{self._base_url}/api/v1/market/orderbook/level2"
        params = {"symbol": formatted_pair, "size": limit}
        
        try:
            async with self._session.get(url, params=params) as resp:
                if resp.status != 200:
                    logger.error(f"[KuCoin] HTTP {resp.status}")
                    return None
                
                data = await resp.json()
                
                if data.get('code') != '200000':
                    logger.error(f"[KuCoin] API Error: {data}")
                    return None
                
                raw_data = data.get('data', {})
                
                # Parse bids (buy orders) - format: [price, quantity]
                bids = [
                    OrderbookEntry(
                        price=float(b[0]),
                        quantity=float(b[1])
                    )
                    for b in raw_data.get('bids', [])[:limit]
                ]
                
                # Parse asks (sell orders) - format: [price, quantity]
                asks = [
                    OrderbookEntry(
                        price=float(a[0]),
                        quantity=float(a[1])
                    )
                    for a in raw_data.get('asks', [])[:limit]
                ]
                
                return Orderbook(
                    exchange=self.name,
                    pair=self.pair,
                    bids=bids,
                    asks=asks,
                    raw=raw_data
                )
                
        except Exception as e:
            logger.error(f"[KuCoin] Error fetching orderbook: {e}")
            return None
    
    async def get_ticker(self) -> dict:
        """Get current ticker (price info)"""
        if not self._connected:
            await self.connect()
        
        formatted_pair = self._format_pair(self.pair)
        url = f"{self._base_url}/api/v1/market/orderbook/level2"
        params = {"symbol": formatted_pair}
        
        try:
            async with self._session.get(url, params=params) as resp:
                if resp.status != 200:
                    return None
                
                data = await resp.json()
                if data.get('code') != '200000':
                    return None
                
                raw_data = data.get('data', {})
                best_bid = float(raw_data['bids'][0][0]) if raw_data.get('bids') else 0
                best_ask = float(raw_data['asks'][0][0]) if raw_data.get('asks') else 0
                
                return {
                    'exchange': self.name,
                    'pair': self.pair,
                    'best_bid': best_bid,
                    'best_ask': best_ask,
                    'mid_price': (best_bid + best_ask) / 2 if best_bid and best_ask else 0,
                    'spread': best_ask - best_bid if best_bid and best_ask else 0,
                    'spread_pct': ((best_ask - best_bid) / ((best_bid + best_ask) / 2) * 100) if best_bid and best_ask else 0
                }
        except Exception as e:
            logger.error(f"[KuCoin] Error fetching ticker: {e}")
            return None


    async def get_order_details(self, order_id: str) -> dict:
        """
        Get order details from KuCoin (public endpoint, no auth needed for read)
        
        Args:
            order_id: KuCoin order ID
            
        Returns:
            dict with order details including dealSize, dealFunds, fees
        """
        if not self._connected:
            await self.connect()
        
        path = f'/api/v1/orders/{order_id}'
        ts = str(int(time.time() * 1000))
        sig = self._sign(ts, 'GET', path)
        
        headers = {
            'KC-API-KEY': self.api_key,
            'KC-API-SIGN': sig,
            'KC-API-TIMESTAMP': ts,
            'KC-API-PASSPHRASE': self._encrypt_passphrase(self.api_passphrase),
            'KC-API-KEY-VERSION': '2'
        }
        
        try:
            async with self._session.get(f'{self._base_url}{path}', headers=headers, timeout=10) as resp:
                if resp.status != 200:
                    logger.error(f"[KuCoin] HTTP {resp.status}")
                    return {}
                
                data = await resp.json()
                if data.get('code') != '200000':
                    logger.error(f"[KuCoin] API Error: {data}")
                    return {}
                
                return data.get('data', {})
        except Exception as e:
            logger.error(f"[KuCoin] Error fetching order {order_id}: {e}")
            return {}
    
    async def get_order_fills(self, order_id: str) -> dict:
        """
        Get all fills for a KuCoin order - aggregates partial fills
        
        KuCoin can split a single order into multiple partial fills.
        This method sums all fills to get the correct total quantity and fees.
        
        Args:
            order_id: KuCoin order ID
            
        Returns:
            dict with aggregated: {
                'total_qty': float,      # Total quantity filled
                'total_cost': float,    # Total cost (qty * price)
                'fees': float,           # Total fees paid
                'avg_price': float,     # Average fill price
                'fill_count': int,      # Number of partial fills
                'fills': []             # List of individual fills
            }
        """
        if not self._connected:
            await self.connect()
        
        path = f'/api/v1/fills?orderId={order_id}'
        ts = str(int(time.time() * 1000))
        sig = self._sign(ts, 'GET', path)
        
        headers = {
            'KC-API-KEY': self.api_key,
            'KC-API-SIGN': sig,
            'KC-API-TIMESTAMP': ts,
            'KC-API-PASSPHRASE': self._encrypt_passphrase(self.api_passphrase),
            'KC-API-KEY-VERSION': '2'
        }
        
        try:
            async with self._session.get(f'{self._base_url}{path}', headers=headers, timeout=10) as resp:
                if resp.status != 200:
                    logger.error(f"[KuCoin] HTTP {resp.status}")
                    return {'total_qty': 0, 'fills': []}
                
                data = await resp.json()
                if data.get('code') != '200000':
                    logger.error(f"[KuCoin] Fills API Error: {data}")
                    return {'total_qty': 0, 'fills': []}
                
                raw_fills = data.get('data', [])
                
                # Aggregate all fills
                total_qty = 0.0
                total_cost = 0.0
                total_fees = 0.0
                fills = []
                
                for fill in raw_fills:
                    qty = float(fill.get('size', 0) or 0)
                    price = float(fill.get('price', 0) or 0)
                    fee = float(fill.get('fee', 0) or 0)
                    fee_currency = fill.get('feeCurrency', '')
                    
                    total_qty += qty
                    total_cost += qty * price
                    total_fees += fee
                    
                    fills.append({
                        'qty': qty,
                        'price': price,
                        'fee': fee,
                        'fee_currency': fee_currency,
                        'timestamp': fill.get('createdAt', '')
                    })
                
                avg_price = total_cost / total_qty if total_qty > 0 else 0
                
                return {
                    'total_qty': total_qty,
                    'total_cost': total_cost,
                    'fees': total_fees,
                    'avg_price': avg_price,
                    'fill_count': len(fills),
                    'fills': fills
                }
                
        except Exception as e:
            logger.error(f"[KuCoin] Error fetching fills for {order_id}: {e}")
            return {'total_qty': 0, 'fills': []}
    
    def _sign(self, ts: str, method: str, path: str, body: str = '') -> str:
        """Generate KuCoin API signature"""
        import hashlib
        import base64
        import hmac
        message = f'{ts}{method}{path}{body}'
        mac = hmac.new(self.api_secret.encode(), message.encode(), hashlib.sha256)
        return base64.b64encode(mac.digest()).decode()
    
    def _encrypt_passphrase(self, passphrase: str) -> str:
        """Encrypt passphrase for KuCoin API v2"""
        import hashlib
        import base64
        import hmac
        mac = hmac.new(self.api_secret.encode(), passphrase.encode(), hashlib.sha256)
        return base64.b64encode(mac.digest()).decode()


# Singleton instance
_connector: Optional[KuCoinConnector] = None

async def get_kucoin_connector(pair: str = "MPC-USDT") -> KuCoinConnector:
    """Get KuCoin connector instance"""
    global _connector
    if _connector is None:
        _connector = KuCoinConnector(pair)
        await _connector.connect()
    return _connector
