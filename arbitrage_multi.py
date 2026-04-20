#!/usr/bin/env python3
"""
MPC Arbitrage Bot - Working Multi-Pair Version
Uses working endpoints: KuCoin Level1 + MEXC bookTicker
"""

import asyncio
import aiohttp
import sys
import os
import signal
import yaml
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, List
from collections import deque
from loguru import logger

# Configure logging
os.makedirs('logs', exist_ok=True)
logger.add('logs/arbitrage.log', rotation='100 MB', retention='30 days', level='INFO')

# ============================================================================
# Configuration
# ============================================================================

CONFIG_FILE = 'config/config.yaml'

def load_config():
    config_path = Path(__file__).parent / CONFIG_FILE
    if config_path.exists():
        with open(config_path, 'r') as f:
            return yaml.safe_load(f) or {}
    return {
        'kucoin': {'api_key': '', 'api_secret': '', 'api_passphrase': ''},
        'mexc': {'api_key': '', 'api_secret': ''},
        'trading': {
            'thresholds': {'start': 0.5, 'stop': 0.2},
            'min_volume': 10,
            'pairs': ['MPC-USDT']
        }
    }

def save_config(config):
    config_path = Path(__file__).parent / CONFIG_FILE
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False)

# ============================================================================
# Exchange Clients with WORKING Endpoints
# ============================================================================

class KuCoinClient:
    """KuCoin using Level1 endpoint - works without API key"""
    
    def __init__(self):
        self.name = "KuCoin"
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def connect(self):
        self._session = aiohttp.ClientSession()
        logger.info("[KuCoin] Connected")
    
    async def disconnect(self):
        if self._session:
            await self._session.close()
    
    async def get_orderbook(self, pair: str) -> Optional[Dict]:
        """Get orderbook using Level1 endpoint"""
        if not self._session:
            await self.connect()
        
        try:
            url = f"https://api.kucoin.com/api/v1/market/orderbook/level1"
            params = {"symbol": pair}
            
            async with self._session.get(url, params=params) as resp:
                if resp.status != 200:
                    return None
                
                data = await resp.json()
                if data.get('code') != '200000':
                    return None
                
                d = data.get('data', {})
                
                return {
                    'bid': float(d.get('bestBid', 0)),
                    'bid_size': float(d.get('bestBidSize', 0)),
                    'ask': float(d.get('bestAsk', 0)),
                    'ask_size': float(d.get('bestAskSize', 0)),
                    'price': float(d.get('price', 0)),
                }
        except Exception as e:
            logger.debug(f"[KuCoin] Error: {e}")
            return None


class MexcClient:
    """MEXC using bookTicker endpoint - works without API key"""
    
    def __init__(self):
        self.name = "MEXC"
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def connect(self):
        self._session = aiohttp.ClientSession()
        logger.info("[MEXC] Connected")
    
    async def disconnect(self):
        if self._session:
            await self._session.close()
    
    async def get_orderbook(self, pair: str) -> Optional[Dict]:
        """Get orderbook using bookTicker endpoint"""
        if not self._session:
            await self.connect()
        
        try:
            # Convert MPC-USDT to MPCUSDT
            symbol = pair.replace('-', '')
            url = f"https://api.mexc.com/api/v3/ticker/bookTicker"
            params = {"symbol": symbol}
            
            async with self._session.get(url, params=params) as resp:
                if resp.status != 200:
                    return None
                
                data = await resp.json()
                
                return {
                    'bid': float(data.get('bidPrice', 0)),
                    'bid_size': float(data.get('bidQty', 0)),
                    'ask': float(data.get('askPrice', 0)),
                    'ask_size': float(data.get('askQty', 0)),
                    'price': (float(data.get('bidPrice', 0)) + float(data.get('askPrice', 0))) / 2,
                }
        except Exception as e:
            logger.debug(f"[MEXC] Error: {e}")
            return None


class BinanceClient:
    """Binance using bookTicker endpoint"""
    
    def __init__(self):
        self.name = "Binance"
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def connect(self):
        self._session = aiohttp.ClientSession()
        logger.info("[Binance] Connected")
    
    async def disconnect(self):
        if self._session:
            await self._session.close()
    
    async def get_orderbook(self, pair: str) -> Optional[Dict]:
        if not self._session:
            await self.connect()
        
        try:
            symbol = pair.replace('-', '')
            url = f"https://api.binance.com/api/v3/ticker/bookTicker"
            params = {"symbol": symbol}
            
            async with self._session.get(url, params=params) as resp:
                if resp.status != 200:
                    return None
                
                data = await resp.json()
                
                return {
                    'bid': float(data.get('bidPrice', 0)),
                    'bid_size': float(data.get('bidQty', 0)),
                    'ask': float(data.get('askPrice', 0)),
                    'ask_size': float(data.get('askQty', 0)),
                    'price': (float(data.get('bidPrice', 0)) + float(data.get('askPrice', 0))) / 2,
                }
        except Exception as e:
            logger.debug(f"[Binance] Error: {e}")
            return None


# ============================================================================
# Arbitrage Engine
# ============================================================================

class ArbitrageEngine:
    def __init__(self, pairs: List[str], interval: float = 3.0):
        self.pairs = pairs
        self.interval = interval
        self.config = load_config()
        
        # Initialize clients
        self.clients = {
            'KuCoin': KuCoinClient(),
            'MEXC': MexcClient(),
            'Binance': BinanceClient()
        }
        
        self.thresholds = self.config.get('trading', {}).get('thresholds', {'start': 0.5, 'stop': 0.2})
        self.min_volume = self.config.get('trading', {}).get('min_volume', 10)
        
        # Statistics
        self.stats = {
            'checks': 0,
            'opportunities': [],
            'best_spread': 0.0,
            'best_pair': None
        }
        
        self._running = False
    
    async def start(self):
        logger.info(f"🚀 Starting Arbitrage Engine for {len(self.pairs)} pairs")
        
        for client in self.clients.values():
            await client.connect()
        
        self._running = True
        logger.info("✅ Engine started!")
        
        while self._running:
            try:
                await self.check_all_pairs()
                self.stats['checks'] += 1
                await asyncio.sleep(self.interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Engine error: {e}")
                await asyncio.sleep(10)
    
    async def stop(self):
        logger.info("🛑 Stopping engine...")
        self._running = False
        for client in self.clients.values():
            await client.disconnect()
    
    async def check_all_pairs(self):
        for pair in self.pairs:
            await self.check_pair(pair)
    
    async def check_pair(self, pair: str):
        results = {}
        
        for name, client in self.clients.items():
            ob = await client.get_orderbook(pair)
            if ob and ob.get('bid', 0) > 0:
                results[name] = ob
        
        if len(results) < 2:
            return
        
        exchanges = list(results.keys())
        
        for i, ex1 in enumerate(exchanges):
            for ex2 in exchanges[i+1:]:
                r1, r2 = results[ex1], results[ex2]
                
                # Direction 1: Buy ex1 (ask), Sell ex2 (bid)
                spread1 = ((r2['bid'] - r1['ask']) / r1['ask']) * 100
                vol1 = min(r1['ask_size'], r2['bid_size'])
                
                if spread1 > self.stats['best_spread']:
                    self.stats['best_spread'] = spread1
                    self.stats['best_pair'] = {
                        'pair': pair,
                        'buy': ex1, 'sell': ex2,
                        'buy_price': r1['ask'], 'sell_price': r2['bid'],
                        'spread': spread1, 'volume': vol1
                    }
                
                if spread1 >= self.thresholds['start']:
                    opp = {
                        'time': datetime.now().strftime('%H:%M:%S'),
                        'pair': pair,
                        'buy': ex1, 'sell': ex2,
                        'buy_price': r1['ask'], 'sell_price': r2['bid'],
                        'spread': spread1, 'volume': vol1
                    }
                    logger.info(f"🚀 {pair}: BUY {ex1} @ ${r1['ask']:.6f} → SELL {ex2} @ ${r2['bid']:.6f} | Spread: {spread1:.3f}% | Vol: {vol1:.0f}")
                    self.stats['opportunities'].append(opp)
                
                # Direction 2: Buy ex2 (ask), Sell ex1 (bid)
                spread2 = ((r1['bid'] - r2['ask']) / r2['ask']) * 100
                vol2 = min(r2['ask_size'], r1['bid_size'])
                
                if spread2 > self.stats['best_spread']:
                    self.stats['best_spread'] = spread2
                    self.stats['best_pair'] = {
                        'pair': pair,
                        'buy': ex2, 'sell': ex1,
                        'buy_price': r2['ask'], 'sell_price': r1['bid'],
                        'spread': spread2, 'volume': vol2
                    }
                
                if spread2 >= self.thresholds['start']:
                    opp = {
                        'time': datetime.now().strftime('%H:%M:%S'),
                        'pair': pair,
                        'buy': ex2, 'sell': ex1,
                        'buy_price': r2['ask'], 'sell_price': r1['bid'],
                        'spread': spread2, 'volume': vol2
                    }
                    logger.info(f"🚀 {pair}: BUY {ex2} @ ${r2['ask']:.6f} → SELL {ex1} @ ${r1['bid']:.6f} | Spread: {spread2:.3f}% | Vol: {vol2:.0f}")
                    self.stats['opportunities'].append(opp)
        
        # Log prices
        ts = datetime.now().strftime('%H:%M:%S')
        prices_str = " | ".join([f"{k}: ${v['price']:.6f}" for k, v in results.items()])
        logger.debug(f"[{ts}] {pair}: {prices_str}")
    
    def get_status(self) -> Dict:
        return {
            'running': self._running,
            'pairs': self.pairs,
            'checks': self.stats['checks'],
            'best_spread': self.stats['best_spread'],
            'best_pair': self.stats['best_pair'],
            'recent_opportunities': self.stats['opportunities'][-5:]
        }


# ============================================================================
# Main
# ============================================================================

if __name__ == "__main__":
    config = load_config()
    pairs = config.get('trading', {}).get('pairs', ['MPC-USDT'])
    
    engine = ArbitrageEngine(pairs=pairs, interval=3.0)
    
    def signal_handler(sig, frame):
        print("\nShutting down...")
        asyncio.create_task(engine.stop())
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        asyncio.run(engine.start())
    except KeyboardInterrupt:
        print("\nInterrupted")
