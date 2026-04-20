#!/usr/bin/env python3
"""
MPC Arbitrage Bot - Single File Version
Monitors spreads between KuCoin and MEXC for arbitrage opportunities
"""

import asyncio
import aiohttp
import sys
import os
import signal
import yaml
import time
import hmac
import hashlib
import base64
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Dict, Any
from collections import deque
from loguru import logger

# Configure logging
os.makedirs('logs', exist_ok=True)
logger.add('logs/arbitrage.log', rotation='100 MB', retention='30 days', level='INFO')

# ============================================================================
# Configuration Manager
# ============================================================================

class ConfigManager:
    """Manages configuration and authentication"""
    
    def __init__(self):
        self.config_path = Path(__file__).parent / 'config' / 'config.yaml'
        self._config = self._load()
    
    def _load(self) -> Dict:
        if self.config_path.exists():
            with open(self.config_path, 'r') as f:
                return yaml.safe_load(f) or {}
        return self._default_config()
    
    def _default_config(self) -> Dict:
        return {
            'auth': {
                'admin_username': None,
                'admin_password_hash': None,
                'admin_2fa_secret': None,
                'registration_locked': False,
                'backup_codes': []
            },
            'trading': {
                'pair': 'MPC-USDT',
                'thresholds': {'start': 2.0, 'stop': 1.0},
                'mode': 'test'
            },
            'kucoin': {'api_key': '', 'api_secret': '', 'api_passphrase': ''},
            'mexc': {'api_key': '', 'api_secret': ''}
        }
    
    def save(self):
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, 'w') as f:
            yaml.dump(self._config, f, default_flow_style=False)
    
    def get(self, key: str, default=None):
        keys = key.split('.')
        value = self._config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default
            if value is None:
                return default
        return value
    
    def set(self, key: str, value):
        keys = key.split('.')
        config = self._config
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
        config[keys[-1]] = value
        self.save()
    
    @property
    def is_registered(self) -> bool:
        return (
            self.get('auth.admin_username') is not None and
            self.get('auth.admin_password_hash') is not None and
            self.get('auth.admin_2fa_secret') is not None
        )
    
    def register_admin(self, username: str, password: str) -> Dict:
        """Register admin with 2FA"""
        if len(password) < 8:
            return {'success': False, 'message': 'Password must be at least 8 characters'}
        
        totp_secret = pyotp.random_base32()
        backup_codes = [hashlib.sha256(f"{username}{i}".encode()).hexdigest()[:16] for i in range(10)]
        
        password_hash = hashlib.sha256(f"{username}:{password}".encode()).hexdigest()
        
        self.set('auth.admin_username', username)
        self.set('auth.admin_password_hash', password_hash)
        self.set('auth.admin_2fa_secret', totp_secret)
        self.set('auth.backup_codes', backup_codes)
        self.set('auth.registration_locked', True)
        
        return {
            'success': True,
            'totp_secret': totp_secret,
            'backup_codes': backup_codes
        }
    
    def verify_password(self, password: str) -> bool:
        stored = self.get('auth.admin_password_hash')
        username = self.get('auth.admin_username')
        if not stored or not username:
            return False
        return stored == hashlib.sha256(f"{username}:{password}".encode()).hexdigest()
    
    def verify_2fa(self, token: str) -> bool:
        secret = self.get('auth.admin_2fa_secret')
        if not secret:
            return False
        totp = pyotp.TOTP(secret)
        return totp.verify(token, valid_window=1)
    
    def authenticate(self, username: str, password: str, token: str) -> Dict:
        if username != self.get('auth.admin_username'):
            return {'success': False, 'message': 'Invalid credentials'}
        if not self.verify_password(password):
            return {'success': False, 'message': 'Invalid credentials'}
        if not self.verify_2fa(token):
            return {'success': False, 'message': 'Invalid 2FA token'}
        return {'success': True, 'message': 'Login successful'}
    
    def get_thresholds(self) -> Dict[str, float]:
        return {
            'start': self.get('trading.thresholds.start', 2.0),
            'stop': self.get('trading.thresholds.stop', 1.0)
        }
    
    def set_thresholds(self, start: float, stop: float) -> Dict:
        if not (0 <= start <= 50) or not (0 <= stop <= 50):
            return {'success': False, 'message': 'Thresholds must be 0-50%'}
        if start < stop:
            return {'success': False, 'message': 'Start must be >= stop'}
        self.set('trading.thresholds.start', start)
        self.set('trading.thresholds.stop', stop)
        return {'success': True, 'message': 'Thresholds updated'}


# ============================================================================
# Exchange Connectors
# ============================================================================

class OrderbookEntry:
    def __init__(self, price: float, quantity: float):
        self.price = price
        self.quantity = quantity

class Orderbook:
    def __init__(self, exchange: str, bids: List, asks: List):
        self.exchange = exchange
        self.bids = [OrderbookEntry(float(b[0]), float(b[1])) for b in bids[:20]]
        self.asks = [OrderbookEntry(float(a[0]), float(a[1])) for a in asks[:20]]
    
    @property
    def best_bid(self) -> float:
        return self.bids[0].price if self.bids else 0.0
    
    @property
    def best_ask(self) -> float:
        return self.asks[0].price if self.asks else 0.0
    
    @property
    def mid_price(self) -> float:
        return (self.best_bid + self.best_ask) / 2 if self.best_bid and self.best_ask else 0.0


class KuCoinConnector:
    """KuCoin connector using API keys for real orderbook data"""
    def __init__(self, pair: str = "MPC-USDT"):
        self.pair = pair
        self.name = "kucoin"
        self._session: Optional[aiohttp.ClientSession] = None
        self.config = None
    
    def load_config(self):
        """Load API keys from config"""
        import yaml
        from pathlib import Path
        config_path = Path(__file__).parent / 'config' / 'config.yaml'
        if config_path.exists():
            with open(config_path, 'r') as f:
                self.config = yaml.safe_load(f) or {}
        else:
            self.config = {}
        return self.config.get('kucoin', {})
    
    async def connect(self):
        self._session = aiohttp.ClientSession()
        self.load_config()
        logger.info("[KuCoin] Connected with API")
    
    async def disconnect(self):
        if self._session:
            await self._session.close()
        logger.info("[KuCoin] Disconnected")
    
    def _sign_request(self, params: dict) -> tuple:
        """Sign KuCoin request with API credentials"""
        import time
        now = int(time.time() * 1000)
        method = 'GET'
        path = '/api/v1/market/orderbook/level2'
        body = ''
        message = f'{now}{method}{path}{body}'
        
        api_secret = self.config.get('api_secret', '')
        import hmac
        import base64
        signature = base64.b64encode(hmac.new(
            api_secret.encode(),
            message.encode(),
            hashlib.sha256
        ).digest()).decode()
        
        return now, signature
    
    async def get_orderbook(self) -> Optional[Orderbook]:
        if not self._session:
            await self.connect()
        
        if not self.config.get('api_key'):
            logger.warning("[KuCoin] No API key configured")
            return None
        
        now = int(time.time() * 1000)
        method = 'GET'
        path = '/api/v1/market/orderbook/level2'
        query = f'symbol={self.pair}&size=20'
        full_path = f'{path}?{query}'
        
        message = f'{now}{method}{full_path}'
        
        import hmac
        import hashlib
        import base64
        
        api_secret = self.config.get('api_secret', '').encode()
        signature = base64.b64encode(hmac.new(
            api_secret,
            message.encode(),
            hashlib.sha256
        ).digest()).decode()
        
        api_passphrase = self.config.get('api_passphrase', '')
        passphrase_enc = base64.b64encode(hmac.new(
            api_secret,
            api_passphrase.encode(),
            hashlib.sha256
        ).digest()).decode()
        
        headers = {
            'KC-API-KEY': self.config.get('api_key', ''),
            'KC-API-SIGN': signature,
            'KC-API-TIMESTAMP': str(now),
            'KC-API-PASSPHRASE': passphrase_enc,
            'KC-API-KEY-VERSION': '2'
        }
        
        url = f'https://api.kucoin.com{full_path}'
        
        try:
            async with self._session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.error(f"[KuCoin] HTTP {resp.status}: {text[:100]}")
                    return None
                
                data = await resp.json()
                if data.get('code') != '200000':
                    logger.error(f"[KuCoin] API error: {data}")
                    return None
                
                d = data['data']
                return Orderbook(self.name, d.get('bids', []), d.get('asks', []))
        except Exception as e:
            logger.error(f"[KuCoin] Error: {e}")
            return None


class MexcConnector:
    """MEXC connector using API keys for real orderbook data"""
    def __init__(self, pair: str = "MPC-USDT"):
        self.pair = pair.replace('-', '')
        self.name = "mexc"
        self._session: Optional[aiohttp.ClientSession] = None
        self.config = None
    
    def load_config(self):
        """Load API keys from config"""
        import yaml
        from pathlib import Path
        config_path = Path(__file__).parent / 'config' / 'config.yaml'
        if config_path.exists():
            with open(config_path, 'r') as f:
                self.config = yaml.safe_load(f) or {}
        else:
            self.config = {}
        return self.config.get('mexc', {})
    
    async def connect(self):
        self._session = aiohttp.ClientSession()
        self.load_config()
        logger.info("[MEXC] Connected with API")
    
    async def disconnect(self):
        if self._session:
            await self._session.close()
        logger.info("[MEXC] Disconnected")
    
    async def get_orderbook(self) -> Optional[Orderbook]:
        if not self._session:
            await self.connect()
        
        if not self.config.get('api_key'):
            logger.warning("[MEXC] No API key configured")
            return None
        
        # MEXC orderbook endpoint (requires signature for private endpoints,
        # but orderbook is public - we use it directly)
        url = f"https://api.mexc.com/api/v3/market/orderbook"
        params = {"symbol": self.pair, "limit": 20}
        
        try:
            async with self._session.get(url, params=params) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.error(f"[MEXC] HTTP {resp.status}: {text[:100]}")
                    return None
                
                data = await resp.json()
                if data.get('code'):
                    logger.error(f"[MEXC] API error: {data}")
                    return None
                
                d = data.get('data', {})
                bids = d.get('bids', [])
                asks = d.get('asks', [])
                
                return Orderbook(self.name, bids, asks)
        except Exception as e:
            logger.error(f"[MEXC] Error: {e}")
            return None


# ============================================================================
# Spread Analyzer
# ============================================================================

class SpreadAnalyzer:
    def __init__(self):
        self.snapshots = deque(maxlen=1000)
        self.opportunities = deque(maxlen=100)
        self.is_opportunity_active = False
        self.current_spread = 0.0
        self.config = ConfigManager()
        self.stats = {
            'total_checks': 0,
            'opportunities_found': 0,
            'max_spread': 0.0,
            'min_spread': float('inf')
        }
    
    def get_thresholds(self):
        return self.config.get_thresholds()
    
    def analyze(self, kucoin_ob: Orderbook, mexc_ob: Orderbook):
        if not kucoin_ob or not mexc_ob:
            return
        
        # Calculate cross-exchange spreads
        # Direction 1: Buy MEXC, Sell KuCoin
        if kucoin_ob.best_bid > 0 and mexc_ob.best_ask > 0:
            spread_kucoin_mexc = ((kucoin_ob.best_bid - mexc_ob.best_ask) / mexc_ob.best_ask) * 100
        else:
            spread_kucoin_mexc = 0.0
        
        # Direction 2: Buy KuCoin, Sell MEXC
        if mexc_ob.best_bid > 0 and kucoin_ob.best_ask > 0:
            spread_mexc_kucoin = ((mexc_ob.best_bid - kucoin_ob.best_ask) / kucoin_ob.best_ask) * 100
        else:
            spread_mexc_kucoin = 0.0
        
        self.current_spread = max(spread_kucoin_mexc, spread_mexc_kucoin)
        
        # Update stats
        self.stats['total_checks'] += 1
        if self.current_spread > 0:
            self.stats['max_spread'] = max(self.stats['max_spread'], self.current_spread)
            self.stats['min_spread'] = min(self.stats['min_spread'], self.current_spread)
        
        # Check for opportunity with hysteresis
        thresholds = self.get_thresholds()
        
        if not self.is_opportunity_active and self.current_spread >= thresholds['start']:
            self.is_opportunity_active = True
            self.stats['opportunities_found'] += 1
            logger.info(f"🚀 OPPORTUNITY: Spread={self.current_spread:.3f}% (threshold: {thresholds['start']}%)")
        
        elif self.is_opportunity_active and self.current_spread < thresholds['stop']:
            self.is_opportunity_active = False
            logger.info(f"📉 Opportunity ended. Spread={self.current_spread:.3f}% (stop: {thresholds['stop']}%)")
        
        # Store snapshot
        self.snapshots.append({
            'time': datetime.now(),
            'kucoin_bid': kucoin_ob.best_bid,
            'kucoin_ask': kucoin_ob.best_ask,
            'mexc_bid': mexc_ob.best_bid,
            'mexc_ask': mexc_ob.best_ask,
            'spread': self.current_spread
        })


# ============================================================================
# Main Bot
# ============================================================================

class ArbitrageBot:
    def __init__(self, pair: str = "MPC-USDT", interval: float = 1.0):
        self.pair = pair
        self.interval = interval
        self.kucoin = KuCoinConnector(pair)
        self.mexc = MexcConnector(pair)
        self.analyzer = SpreadAnalyzer()
        self._running = False
    
    async def start(self):
        logger.info(f"🚀 Starting MPC Arbitrage Bot for {self.pair}")
        
        await self.kucoin.connect()
        await self.mexc.connect()
        
        self._running = True
        logger.info("✅ Bot started!")
        
        while self._running:
            try:
                kucoin_task = self.kucoin.get_orderbook()
                mexc_task = self.mexc.get_orderbook()
                
                kucoin_ob, mexc_ob = await asyncio.gather(kucoin_task, mexc_task)
                
                if kucoin_ob and mexc_ob:
                    self.analyzer.analyze(kucoin_ob, mexc_ob)
                    
                    ts = datetime.now().strftime('%H:%M:%S')
                    logger.debug(f"[{ts}] KuCoin: {kucoin_ob.best_bid:.6f}/{kucoin_ob.best_ask:.6f} | MEXC: {mexc_ob.best_bid:.6f}/{mexc_ob.best_ask:.6f} | Spread: {self.analyzer.current_spread:.3f}%")
                
                await asyncio.sleep(self.interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error: {e}")
                await asyncio.sleep(5)
    
    async def stop(self):
        logger.info("🛑 Stopping bot...")
        self._running = False
        await self.kucoin.disconnect()
        await self.mexc.disconnect()
        logger.info("✅ Bot stopped")


# ============================================================================
# Main Entry Point
# ============================================================================

if __name__ == "__main__":
    bot = ArbitrageBot()
    
    def signal_handler(sig, frame):
        print("\nShutting down...")
        asyncio.create_task(bot.stop())
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        asyncio.run(bot.start())
    except KeyboardInterrupt:
        print("\nInterrupted")
