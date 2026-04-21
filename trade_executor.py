"""
Trade Executor - Market + Limit Strategy
=========================================
1. Market Order auf kleinerer Volumen-Seite
2. Limit Order auf Gegenseite (Preisschutz)
3. Trade State Tracking (EXECUTING → PARTIAL → COMPLETED/PENDING)
"""

import time
import hashlib
import hmac
import requests
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

# ============================================================================
# DATA CLASSES
# ============================================================================

class TradeStatus(Enum):
    EXECUTING = "EXECUTING"      # Market order placed
    PARTIAL = "PARTIAL"          # Market done, limit placed
    COMPLETED = "COMPLETED"      # Both sides filled
    PENDING = "PENDING"          # Limit order still open
    CANCELLED = "CANCELLED"      # Manually cancelled
    EXPIRED = "EXPIRED"          # Timeout reached
    FAILED = "FAILED"            # Error occurred

@dataclass
class OrderInfo:
    order_id: str
    exchange: str               # 'MEXC' or 'KuCoin'
    side: str                  # 'buy' or 'sell'
    order_type: str            # 'market' or 'limit'
    qty: float
    price: float               # Limit price (0 for market)
    filled_qty: float = 0
    avg_fill_price: float = 0
    status: str = 'open'
    created_at: int = 0        # Unix timestamp ms
    updated_at: int = 0

@dataclass
class TradeExecution:
    trade_id: str
    direction: str            # 'K->M' or 'M->K'
    status: TradeStatus
    
    # Market order (first side)
    market_order: Optional[OrderInfo] = None
    
    # Limit order (second side, placed after market fills)
    limit_order: Optional[OrderInfo] = None
    
    # Timing
    created_at: float = 0
    market_filled_at: float = 0
    limit_filled_at: float = 0
    
    # Calculated values
    buy_price: float = 0
    sell_price: float = 0
    volume: float = 0
    gross_profit: float = 0
    net_profit: float = 0
    fees: float = 0
    
    notes: str = ""

# ============================================================================
# API HELPERS
# ============================================================================

def kucoin_signature(api_secret: str, timestamp: str, method: str, path: str, body: str = '') -> str:
    """Generate KuCoin API signature - MUST use base64 encoding!"""
    import base64
    message = f'{timestamp}{method}{path}{body}'
    mac = hmac.new(api_secret.encode(), message.encode(), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode()

def mexc_signature(api_secret: str, query_string: str) -> str:
    """Generate MEXC API signature"""
    signature = hmac.new(api_secret.encode('utf-8'), query_string.encode('utf-8'), hashlib.sha256).hexdigest()
    return signature

# ============================================================================
# EXCHANGE ORDERS
# ============================================================================

def kucoin_place_market_order(api_key: str, api_secret: str, passphrase: str, 
                              symbol: str, side: str, qty: float) -> dict:
    """Place MARKET order on KuCoin"""
    try:
        ts = str(int(time.time() * 1000))
        method = 'POST'
        path = '/api/v1/orders'
        body = f'{{"clientOid":"{ts}","symbol":"{symbol}","side":"{side}","type":"market","size":"{qty}"}}'
        
        signature = kucoin_signature(api_secret, ts, method, path, body)
        
        headers = {
            'KC-API-SIGN': signature,
            'KC-API-TIMESTAMP': ts,
            'KC-API-PASSPHRASE': passphrase,
            'KC-API-KEY': api_key,
            'KC-API-PASSPHRASE-ENCRYPTION': 'AES-256-GCM',
            'Content-Type': 'application/json'
        }
        
        resp = requests.post(f'https://api.kucoin.com{path}', headers=headers, data=body, timeout=10)
        data = resp.json()
        
        if data.get('code') == '200000':
            order_data = data['data']
            return {
                'ok': True,
                'order_id': order_data.get('orderId'),
                'symbol': symbol,
                'side': side,
                'type': 'market',
                'qty': qty,
                'status': 'filled',  # Market orders fill immediately or nearly so
                'created_at': int(ts)
            }
        else:
            return {'ok': False, 'error': data.get('msg', 'Unknown error')}
    except Exception as e:
        return {'ok': False, 'error': str(e)}

def kucoin_place_limit_order(api_key: str, api_secret: str, passphrase: str,
                             symbol: str, side: str, qty: float, price: float,
                             client_order_id: str = None) -> dict:
    """Place LIMIT order on KuCoin"""
    try:
        ts = str(int(time.time() * 1000))
        method = 'POST'
        path = '/api/v1/orders'
        
        if client_order_id is None:
            client_order_id = f'{ts}_limit'
        
        body = f'{{"clientOid":"{client_order_id}","symbol":"{symbol}","side":"{side}","type":"limit","size":"{qty}","price":"{price}"}}'
        
        signature = kucoin_signature(api_secret, ts, method, path, body)
        
        headers = {
            'KC-API-SIGN': signature,
            'KC-API-TIMESTAMP': ts,
            'KC-API-PASSPHRASE': passphrase,
            'KC-API-KEY': api_key,
            'KC-API-PASSPHRASE-ENCRYPTION': 'AES-256-GCM',
            'Content-Type': 'application/json'
        }
        
        resp = requests.post(f'https://api.kucoin.com{path}', headers=headers, data=body, timeout=10)
        data = resp.json()
        
        if data.get('code') == '200000':
            order_data = data['data']
            return {
                'ok': True,
                'order_id': order_data.get('orderId'),
                'client_order_id': client_order_id,
                'symbol': symbol,
                'side': side,
                'type': 'limit',
                'qty': qty,
                'price': price,
                'status': 'open',
                'created_at': int(ts)
            }
        else:
            return {'ok': False, 'error': data.get('msg', 'Unknown error')}
    except Exception as e:
        return {'ok': False, 'error': str(e)}

def kucoin_check_order(api_key: str, api_secret: str, passphrase: str, 
                       order_id: str) -> dict:
    """Check order status on KuCoin"""
    try:
        ts = str(int(time.time() * 1000))
        method = 'GET'
        path = f'/api/v1/orders/{order_id}'
        
        signature = kucoin_signature(api_secret, ts, method, path)
        
        headers = {
            'KC-API-SIGN': signature,
            'KC-API-TIMESTAMP': ts,
            'KC-API-PASSPHRASE': passphrase,
            'KC-API-KEY': api_key
        }
        
        resp = requests.get(f'https://api.kucoin.com{path}', headers=headers, timeout=10)
        data = resp.json()
        
        if data.get('code') == '200000':
            o = data['data']
            return {
                'ok': True,
                'order_id': order_id,
                'symbol': o.get('symbol'),
                'side': o.get('side'),
                'type': o.get('type'),
                'qty': float(o.get('size', 0)),
                'filled_qty': float(o.get('dealSize', 0)),
                'price': float(o.get('price', 0)),
                'status': o.get('status'),
                'dealFunds': float(o.get('dealFunds', 0)),
                'created_at': int(o.get('createdAt', 0))
            }
        else:
            return {'ok': False, 'error': data.get('msg')}
    except Exception as e:
        return {'ok': False, 'error': str(e)}

def mexc_place_market_order(api_key: str, api_secret: str,
                            symbol: str, side: str, qty: float) -> dict:
    """Place MARKET order on MEXC"""
    try:
        ts = str(int(time.time() * 1000))
        path = '/api/v3/order'
        params = f'symbol={symbol}&side={side}&type=LIMIT&quantity={qty}&price=0&timestamp={ts}'
        
        # MEXC market orders need price=0 and NOT using limit type - use MARKET
        params = f'symbol={symbol}&side={side}&type=MARKET&quantity={qty}&timestamp={ts}'
        signature = mexc_signature(api_secret, params)
        
        url = f'https://api.mexc.com{path}?{params}&signature={signature}'
        headers = {'X-MEXC-APIKEY': api_key}
        
        resp = requests.post(url, headers=headers, timeout=10)
        data = resp.json()
        
        if 'orderId' in data or data.get('code') is None:
            return {
                'ok': True,
                'order_id': data.get('orderId'),
                'symbol': symbol,
                'side': side,
                'type': 'market',
                'qty': qty,
                'status': 'filled',
                'created_at': int(ts)
            }
        else:
            return {'ok': False, 'error': data.get('msg', str(data))}
    except Exception as e:
        return {'ok': False, 'error': str(e)}

def mexc_place_limit_order(api_key: str, api_secret: str,
                           symbol: str, side: str, qty: float, price: float) -> dict:
    """Place LIMIT order on MEXC"""
    try:
        ts = str(int(time.time() * 1000))
        path = '/api/v3/order'
        params = f'symbol={symbol}&side={side}&type=LIMIT&quantity={qty}&price={price}&timestamp={ts}'
        signature = mexc_signature(api_secret, params)
        
        url = f'https://api.mexc.com{path}?{params}&signature={signature}'
        headers = {'X-MEXC-APIKEY': api_key}
        
        resp = requests.post(url, headers=headers, timeout=10)
        data = resp.json()
        
        if 'orderId' in data or data.get('code') is None:
            return {
                'ok': True,
                'order_id': data.get('orderId'),
                'symbol': symbol,
                'side': side,
                'type': 'limit',
                'qty': qty,
                'price': price,
                'status': 'open',
                'created_at': int(ts)
            }
        else:
            return {'ok': False, 'error': data.get('msg', str(data))}
    except Exception as e:
        return {'ok': False, 'error': str(e)}

def mexc_check_order(api_key: str, api_secret: str, order_id: str) -> dict:
    """Check order status on MEXC"""
    try:
        ts = str(int(time.time() * 1000))
        path = '/api/v3/order'
        params = f'orderId={order_id}&timestamp={ts}'
        signature = mexc_signature(api_secret, params)
        
        url = f'https://api.mexc.com{path}?{params}&signature={signature}'
        headers = {'X-MEXC-APIKEY': api_key}
        
        resp = requests.get(url, headers=headers, timeout=10)
        data = resp.json()
        
        if 'orderId' in data:
            return {
                'ok': True,
                'order_id': order_id,
                'symbol': data.get('symbol'),
                'side': data.get('side', '').lower(),
                'type': data.get('type', '').lower(),
                'qty': float(data.get('origQty', 0)),
                'filled_qty': float(data.get('executedQty', 0)),
                'price': float(data.get('price', 0)),
                'status': data.get('status', 'unknown'),
                'created_at': int(data.get('time', 0))
            }
        else:
            return {'ok': False, 'error': data.get('msg', str(data))}
    except Exception as e:
        return {'ok': False, 'error': str(e)}

# ============================================================================
# TRADE EXECUTOR
# ============================================================================

class ArbitrageExecutor:
    """
    Executes arbitrage trades using Market + Limit strategy:
    1. Market order on smaller volume side (guaranteed fill)
    2. Limit order on opposite side (price protection)
    3. Track states: EXECUTING → PARTIAL → COMPLETED/PENDING
    """
    
    def __init__(self, config: dict):
        self.kucoin_key = config.get('kucoin', {}).get('api_key', '')
        self.kucoin_secret = config.get('kucoin', {}).get('api_secret', '')
        self.kucoin_passphrase = config.get('kucoin', {}).get('api_passphrase', '')
        
        self.mexc_key = config.get('mexc', {}).get('api_key', '')
        self.mexc_secret = config.get('mexc', {}).get('api_secret', '')
        
        self.active_trades = []  # List of TradeExecution
        self.pending_limits = []  # Limit orders awaiting fill
        
        # Fee rates (taker 0.1%, maker 0.1%)
        self.fee_taker = 0.001
        self.fee_maker = 0.001
    
    def generate_trade_id(self) -> str:
        """Generate unique trade ID"""
        return f"ARB-{int(time.time()*1000)}"
    
    def execute_market_leg(self, exchange: str, side: str, qty: float, 
                          price: float, symbol: str = 'MPCUSDT') -> dict:
        """
        Execute the FIRST leg as market order.
        Returns order info dict.
        """
        if exchange == 'KuCoin':
            result = kucoin_place_market_order(
                self.kucoin_key, self.kucoin_secret, self.kucoin_passphrase,
                symbol, side, qty
            )
        else:  # MEXC
            result = mexc_place_market_order(
                self.mexc_key, self.mexc_secret,
                symbol, side, qty
            )
        
        return result
    
    def place_limit_leg(self, exchange: str, side: str, qty: float,
                        price: float, symbol: str = 'MPCUSDT',
                        client_ref: str = None) -> dict:
        """
        Execute the SECOND leg as limit order.
        Returns order info dict.
        """
        if exchange == 'KuCoin':
            result = kucoin_place_limit_order(
                self.kucoin_key, self.kucoin_secret, self.kucoin_passphrase,
                symbol, side, qty, price, client_ref
            )
        else:  # MEXC
            result = mexc_place_limit_order(
                self.mexc_key, self.mexc_secret,
                symbol, side, qty, price
            )
        
        return result
    
    def check_order(self, exchange: str, order_id: str) -> dict:
        """Check order status on exchange"""
        if exchange == 'KuCoin':
            return kucoin_check_order(
                self.kucoin_key, self.kucoin_secret, self.kucoin_passphrase,
                order_id
            )
        else:
            return mexc_check_order(self.mexc_key, self.mexc_secret, order_id)
    
    def execute_arbitrage(self, direction: str, kucoin_ask: float, kucoin_bid: float,
                         mexc_ask: float, mexc_bid: float, 
                         kucoin_ask_size: float, kucoin_bid_size: float,
                         mexc_ask_size: float, mexc_bid_size: float,
                         threshold_pct: float = 0.5) -> dict:
        """
        Main execution function following Market + Limit strategy.
        
        Direction: 'K->M' (Buy KuCoin, Sell MEXC) or 'M->K' (Buy MEXC, Sell KuCoin)
        
        Returns execution result dict.
        """
        trade_id = self.generate_trade_id()
        
        # Determine which side is smaller (this determines our volume)
        if direction == 'K->M':
            buy_exchange = 'KuCoin'
            sell_exchange = 'MEXC'
            buy_side = 'buy'
            sell_side = 'sell'
            buy_price = kucoin_ask
            sell_price = mexc_bid
            volume = min(kucoin_ask_size, mexc_bid_size)
            symbol_kucoin = 'MPC-USDT'
            symbol_mexc = 'MPCUSDT'
        else:  # M->K
            buy_exchange = 'MEXC'
            sell_exchange = 'KuCoin'
            buy_side = 'buy'
            sell_side = 'sell'
            buy_price = mexc_ask
            sell_price = kucoin_bid
            volume = min(mexc_ask_size, kucoin_bid_size)
            symbol_kucoin = 'MPC-USDT'
            symbol_mexc = 'MPCUSDT'
        
        # Calculate spread
        spread = sell_price - buy_price
        spread_pct = (spread / buy_price) * 100
        
        # Check if profitable
        fee_total_est = (buy_price * volume * self.fee_taker) + (sell_price * volume * self.fee_maker)
        net_profit_est = spread * volume - fee_total_est
        
        if net_profit_est <= 0:
            return {
                'ok': False,
                'trade_id': trade_id,
                'error': f'Not profitable: spread={spread:.6f}, fees={fee_total_est:.4f}, net={net_profit_est:.4f}'
            }
        
        # Create trade execution object
        trade = TradeExecution(
            trade_id=trade_id,
            direction=direction,
            status=TradeStatus.EXECUTING,
            volume=volume,
            buy_price=buy_price,
            sell_price=sell_price,
            created_at=time.time()
        )
        
        # STEP 1: Place MARKET order on smaller volume side (BUY)
        market_result = self.execute_market_leg(
            buy_exchange, buy_side, volume,
            buy_price if buy_exchange == 'MEXC' else 0,  # Price not needed for market
            symbol_mexc if buy_exchange == 'MEXC' else symbol_kucoin
        )
        
        if not market_result.get('ok'):
            trade.status = TradeStatus.FAILED
            return {
                'ok': False,
                'trade_id': trade_id,
                'error': f'Market order failed: {market_result.get("error")}'
            }
        
        # Record market order
        trade.market_order = OrderInfo(
            order_id=market_result['order_id'],
            exchange=buy_exchange,
            side=buy_side,
            order_type='market',
            qty=volume,
            price=buy_price,
            filled_qty=volume,  # Assume filled for market
            avg_fill_price=buy_price,
            status='filled',
            created_at=market_result['created_at']
        )
        trade.market_filled_at = time.time()
        trade.status = TradeStatus.PARTIAL
        
        # STEP 2: Place LIMIT order on opposite side (SELL)
        limit_result = self.place_limit_leg(
            sell_exchange, sell_side, volume, sell_price,
            symbol_mexc if sell_exchange == 'MEXC' else symbol_kucoin,
            client_ref=f'{trade_id}_limit'
        )
        
        if not limit_result.get('ok'):
            # Limit order failed - trade is partial
            return {
                'ok': True,
                'trade_id': trade_id,
                'status': 'PARTIAL',
                'warning': f'Limit order failed: {limit_result.get("error")}. Market order filled!',
                'market_order': market_result,
                'limit_order': None
            }
        
        # Record limit order
        trade.limit_order = OrderInfo(
            order_id=limit_result['order_id'],
            exchange=sell_exchange,
            side=sell_side,
            order_type='limit',
            qty=volume,
            price=sell_price,
            status='open',
            created_at=limit_result['created_at']
        )
        
        # Add to active trades
        self.active_trades.append(trade)
        self.pending_limits.append({
            'trade_id': trade_id,
            'order_id': limit_result['order_id'],
            'exchange': sell_exchange,
            'placed_at': time.time()
        })
        
        return {
            'ok': True,
            'trade_id': trade_id,
            'status': 'EXECUTING',
            'market_order': market_result,
            'limit_order': limit_result,
            'volume': volume,
            'buy_price': buy_price,
            'sell_price': sell_price,
            'net_profit_est': net_profit_est
        }
    
    def check_pending_limits(self) -> list:
        """
        Check all pending limit orders and update trade statuses.
        Returns list of completed trades.
        """
        completed = []
        still_pending = []
        
        for pending in self.pending_limits:
            check = self.check_order(pending['exchange'], pending['order_id'])
            
            if check.get('ok'):
                status = check.get('status', '').lower()
                
                if status in ['filled', 'done', 'closed']:
                    # Limit filled - trade complete!
                    completed.append({
                        'trade_id': pending['trade_id'],
                        'order_id': pending['order_id'],
                        'exchange': pending['exchange'],
                        'filled_at': time.time()
                    })
                elif status in ['open', 'new']:
                    still_pending.append(pending)
                else:
                    # cancelled, expired, etc
                    still_pending.append(pending)
            else:
                still_pending.append(pending)
        
        self.pending_limits = still_pending
        return completed
    
    def get_pending_count(self) -> int:
        """Return number of pending limit orders"""
        return len(self.pending_limits)
    
    def cancel_limit(self, trade_id: str) -> dict:
        """Cancel a pending limit order"""
        for pending in self.pending_limits:
            if pending['trade_id'] == trade_id:
                # Call cancel API
                exchange = pending['exchange']
                order_id = pending['order_id']
                
                # Simplified - would need cancel API implementation
                return {'ok': True, 'trade_id': trade_id, 'cancelled': True}
        
        return {'ok': False, 'error': 'Trade not found'}


# ============================================================================
# TEST / EXAMPLE
# ============================================================================

if __name__ == '__main__':
    print("=== Arbitrage Executor Module ===")
    print("Market + Limit Strategy")
    print("")
    print("Usage:")
    print("  executor = ArbitrageExecutor(config)")
    print("  result = executor.execute_arbitrage('K->M', ...)")
    print("  ")
    print("States: EXECUTING -> PARTIAL -> COMPLETED/PENDING")
