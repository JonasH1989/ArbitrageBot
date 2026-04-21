"""
Trade Logger - Portfolio Tracking & Trade History
"""
import csv
import os
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

LOG_DIR = Path(__file__).parent / "logs"
PORTFOLIO_FILE = LOG_DIR / "portfolio_history.csv"
TRADES_FILE = LOG_DIR / "trade_history.csv"
LAST_STATE_FILE = LOG_DIR / ".last_state.json"

# Store last known balances to detect changes
_last_balances = None

def ensure_log_dir():
    """Create logs directory if it doesn't exist"""
    LOG_DIR.mkdir(exist_ok=True)
    
    # Create CSV files with headers if they don't exist
    if not PORTFOLIO_FILE.exists():
        with open(PORTFOLIO_FILE, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['timestamp', 'mpc_total', 'usdt_total', 'mpc_on_kucoin', 'usdt_on_kucoin', 
                           'mpc_on_mexc', 'usdt_on_mexc', 'strategy', 'threshold', 'notes'])
    
    if not TRADES_FILE.exists():
        with open(TRADES_FILE, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['timestamp', 'direction', 'exchange_buy', 'exchange_sell', 
                           'buy_price', 'sell_price', 'volume_mpc', 'cost_usdt', 'revenue_usdt',
                           'gross_profit', 'fee_total', 'net_profit_usdt', 'net_profit_mpc',
                           'spread_pct', 'threshold_pct', 'fee_buy', 'fee_sell',
                           'win_loss', 'fee_warning', 'status', 'notes'])


def check_and_log_portfolio(kucoin_balances: Dict, mexc_balances: Dict, strategy: str = "usdt", 
                            threshold: float = 0.0, notes: str = "") -> bool:
    """
    Check if balances changed and log only if something changed.
    Returns True if something was logged, False otherwise.
    """
    global _last_balances
    
    mpc_k = kucoin_balances.get('MPC', 0)
    usdt_k = kucoin_balances.get('USDT', 0)
    mpc_m = mexc_balances.get('MPC', 0)
    usdt_m = mexc_balances.get('USDT', 0)
    
    current = {
        'mpc_kucoin': mpc_k,
        'usdt_kucoin': usdt_k,
        'mpc_mexc': mpc_m,
        'usdt_mexc': usdt_m
    }
    
    # Check if anything changed
    if _last_balances is not None:
        changed = False
        for key, val in current.items():
            if abs(val - _last_balances.get(key, 0)) > 0.0001:  # Ignore tiny float differences
                changed = True
                break
        
        if not changed:
            return False  # No change, don't log
    
    # Something changed - log it
    _last_balances = current
    log_portfolio(kucoin_balances, mexc_balances, strategy, threshold, notes)
    return True


def log_portfolio(kucoin_balances: Dict, mexc_balances: Dict, strategy: str = "usdt", 
                  threshold: float = 0.0, notes: str = "") -> None:
    """Log current portfolio state"""
    ensure_log_dir()
    
    mpc_k = kucoin_balances.get('MPC', 0)
    usdt_k = kucoin_balances.get('USDT', 0)
    mpc_m = mexc_balances.get('MPC', 0)
    usdt_m = mexc_balances.get('USDT', 0)
    
    mpc_total = mpc_k + mpc_m
    usdt_total = usdt_k + usdt_m
    
    with open(PORTFOLIO_FILE, 'a', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            datetime.now().isoformat(),
            f"{mpc_total:.4f}",
            f"{usdt_total:.4f}",
            f"{mpc_k:.4f}",
            f"{usdt_k:.4f}",
            f"{mpc_m:.4f}",
            f"{usdt_m:.4f}",
            strategy,
            f"{threshold:.3f}",
            notes
        ])


def log_trade(direction: str, exchange_buy: str, exchange_sell: str,
              buy_price: float, sell_price: float, volume_mpc: float,
              cost_usdt: float, revenue_usdt: float,
              fee_buy: float = 0.0, fee_sell: float = 0.0,
              threshold_pct: float = 0.0, status: str = "completed",
              notes: str = "") -> None:
    """Log a completed trade"""
    ensure_log_dir()
    
    profit_usdt = revenue_usdt - cost_usdt
    spread_pct = ((sell_price - buy_price) / buy_price) * 100 if buy_price > 0 else 0
    
    # Net after fees
    fee_total = fee_buy + fee_sell
    net_profit_usdt = profit_usdt - fee_total
    # Approximate MPC profit
    net_profit_mpc = net_profit_usdt / sell_price if sell_price > 0 else 0
    
    # Determine WIN/LOSS
    win_loss = "WIN" if net_profit_usdt > 0 else "LOSS"
    
    # Calculate gross profit before fees
    gross_profit = profit_usdt
    
    # Fee warning: if fees > 50% of gross profit, flag it
    fee_warning = "FEE_WARNING" if gross_profit > 0 and fee_total > gross_profit * 0.5 else ""
    
    with open(TRADES_FILE, 'a', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            datetime.now().isoformat(),
            direction,
            exchange_buy,
            exchange_sell,
            f"{buy_price:.6f}",
            f"{sell_price:.6f}",
            f"{volume_mpc:.4f}",
            f"{cost_usdt:.4f}",
            f"{revenue_usdt:.4f}",
            f"{gross_profit:.4f}",
            f"{fee_total:.4f}",
            f"{net_profit_usdt:.4f}",
            f"{net_profit_mpc:.4f}",
            f"{spread_pct:.3f}",
            f"{threshold_pct:.3f}",
            f"{fee_buy:.4f}",
            f"{fee_sell:.4f}",
            win_loss,
            fee_warning,
            status,
            notes
        ])


def get_portfolio_history(limit: int = 100) -> list:
    """Get recent portfolio history"""
    ensure_log_dir()
    
    if not PORTFOLIO_FILE.exists():
        return []
    
    with open(PORTFOLIO_FILE, 'r') as f:
        reader = csv.reader(f)
        next(reader)  # Skip header
        rows = list(reader)
    
    return rows[-limit:]


def get_trade_history(limit: int = 100) -> list:
    """Get recent trade history"""
    ensure_log_dir()
    
    if not TRADES_FILE.exists():
        return []
    
    with open(TRADES_FILE, 'r') as f:
        reader = csv.reader(f)
        next(reader)  # Skip header
        rows = list(reader)
    
    return rows[-limit:]


def get_trade_summary() -> Dict:
    """Calculate trade summary statistics"""
    trades = get_trade_history()
    
    if not trades:
        return {
            'total_trades': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'win_rate': '0%',
            'total_profit_usdt': 0,
            'total_profit_mpc': 0,
            'avg_profit_usdt': 0,
            'avg_profit_mpc': 0,
            'best_trade_usdt': 0,
            'best_trade_mpc': 0,
            'worst_trade_usdt': 0
        }
    
    total_profit_usdt = 0
    total_profit_mpc = 0
    winning = 0
    losing = 0
    best_usdt = 0
    best_mpc = 0
    worst_usdt = 0
    
    for t in trades:
        try:
            profit_usdt = float(t[11])  # net_profit_usdt (index 11)
            profit_mpc = float(t[12])   # net_profit_mpc (index 12)
            
            total_profit_usdt += profit_usdt
            total_profit_mpc += profit_mpc
            
            if profit_usdt > 0:
                winning += 1
                if profit_usdt > best_usdt:
                    best_usdt = profit_usdt
                    best_mpc = profit_mpc
            else:
                losing += 1
                if profit_usdt < worst_usdt:
                    worst_usdt = profit_usdt
        except (ValueError, IndexError):
            continue
    
    count = len(trades)
    return {
        'total_trades': count,
        'winning_trades': winning,
        'losing_trades': losing,
        'win_rate': f"{winning/count*100:.1f}%" if count > 0 else "0%",
        'total_profit_usdt': f"{total_profit_usdt:.4f}",
        'total_profit_mpc': f"{total_profit_mpc:.4f}",
        'avg_profit_usdt': f"{total_profit_usdt/count:.4f}" if count > 0 else "0",
        'avg_profit_mpc': f"{total_profit_mpc/count:.4f}" if count > 0 else "0",
        'best_trade_usdt': f"{best_usdt:.4f}",
        'best_trade_mpc': f"{best_mpc:.4f}",
        'worst_trade_usdt': f"{worst_usdt:.4f}"
    }


def export_trades_csv(filename: str = None) -> str:
    """Export trade history to CSV file and return path"""
    if filename is None:
        filename = f"trades_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    
    trades = get_trade_history(limit=10000)
    
    if not trades:
        return None
    
    export_path = LOG_DIR / filename
    
    with open(export_path, 'w', newline='') as f:
        writer = csv.writer(f)
        # Header
        writer.writerow(['timestamp', 'direction', 'exchange_buy', 'exchange_sell',
                       'buy_price', 'sell_price', 'volume_mpc', 'cost_usdt', 'revenue_usdt',
                       'profit_usdt', 'profit_mpc', 'spread_pct', 'threshold_pct',
                       'fee_buy', 'fee_sell', 'net_profit_usdt', 'net_profit_mpc',
                       'status', 'notes'])
        writer.writerows(trades)
    
    return str(export_path)


def export_portfolio_csv(filename: str = None) -> str:
    """Export portfolio history to CSV file and return path"""
    if filename is None:
        filename = f"portfolio_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    
    portfolio = get_portfolio_history(limit=10000)
    
    if not portfolio:
        return None
    
    export_path = LOG_DIR / filename
    
    with open(export_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['timestamp', 'mpc_total', 'usdt_total', 'mpc_on_kucoin', 'usdt_on_kucoin',
                        'mpc_on_mexc', 'usdt_on_mexc', 'strategy', 'threshold', 'notes'])
        writer.writerows(portfolio)
    
    return str(export_path)


# Track last logged trade IDs to detect new trades
_logged_kucoin_trades = set()
_logged_mexc_trades = set()

def detect_and_log_trades(kucoin_trades: list, mexc_trades: list, threshold_pct: float = 0.0, time_window_minutes: int = 5, volume_tolerance: float = 0.1) -> list:
    """
    Detect and match arbitrage trades from exchange trade histories.
    
    Matching logic:
    - One trade must be a BUY, one must be a SELL
    - Volumes must be within tolerance (default 10%)
    - Trades must be within time window (default 5 minutes)
    
    Returns list of matched trade pairs.
    """
    global _logged_kucoin_trades, _logged_mexc_trades
    
    # Normalize and combine all trades with timestamps
    all_trades = []
    
    # Process KuCoin trades
    for trade in kucoin_trades:
        trade_id = f"kucoin_{trade.get('trade_id', '')}"
        if trade_id in _logged_kucoin_trades:
            continue
        
        side = trade.get('side', '')
        if side not in ['buy', 'sell']:
            continue
            
        _logged_kucoin_trades.add(trade_id)
        
        # Parse timestamp (KuCoin: created_at in milliseconds)
        from datetime import datetime
        ts_val = trade.get('created_at')
        try:
            if ts_val:
                ts = datetime.fromtimestamp(int(ts_val) / 1000)
            else:
                ts = datetime.now()
        except:
            ts = datetime.now()
        
        all_trades.append({
            'id': trade_id,
            'exchange': 'KuCoin',
            'side': side,  # 'buy' or 'sell'
            'price': float(trade.get('price', 0)),
            'volume': float(trade.get('size', trade.get('funds', 0) / (float(trade.get('price', 1)) or 1))),
            'quote': float(trade.get('funds', 0)),
            'fee': float(trade.get('fee', 0)),
            'timestamp': ts,
            'raw': trade
        })
    
    # Process MEXC trades
    for trade in mexc_trades:
        trade_id = f"mexc_{trade.get('trade_id', '')}"
        if trade_id in _logged_mexc_trades:
            continue
            
        side = trade.get('side', '')
        if side not in ['buy', 'sell']:
            continue
            
        _logged_mexc_trades.add(trade_id)
        
        # Parse timestamp (MEXC format)
        ts_str = trade.get('time', trade.get('timestamp', ''))
        try:
            from datetime import datetime
            if isinstance(ts_str, (int, float)):
                ts = datetime.fromtimestamp(ts_str / 1000)  # MEXC uses milliseconds
            else:
                ts = datetime.fromisoformat(str(ts_str).replace('Z', '+00:00'))
        except:
            ts = datetime.now()
        
        all_trades.append({
            'id': trade_id,
            'exchange': 'MEXC',
            'side': side,
            'price': float(trade.get('price', 0)),
            'volume': float(trade.get('qty', trade.get('vol', 0))),
            'quote': float(trade.get('quote', 0)),
            'fee': float(trade.get('fee', 0)),
            'timestamp': ts,
            'raw': trade
        })
    
    # Try to match trades
    matched_pairs = []
    # Try to match trades
    matched_pairs = []
    
    # For MEXC: trades without IDs get synthetic IDs based on position
    # This prevents us from skipping them as "already logged"
    for i, trade in enumerate(all_trades):
        if not trade['id'] or trade['id'].endswith('_None'):
            trade['id'] = f"{trade['exchange']}_{trade['timestamp'].strftime('%Y%m%d%H%M%S')}_{i}"
    
    unmatched = list(all_trades)
    
    for i, trade1 in enumerate(unmatched):
        for j, trade2 in enumerate(unmatched[i+1:], start=i+1):
            # Check if opposite sides
            if trade1['side'] == trade2['side']:
                continue
            
            # Check if same exchange (can't be arbitrage with same exchange)
            if trade1['exchange'] == trade2['exchange']:
                continue
            
            # Check time window
            time_diff = abs((trade1['timestamp'] - trade2['timestamp']).total_seconds())
            if time_diff > time_window_minutes * 60:
                continue
            
            # Check volume tolerance
            vol1 = trade1['volume']
            vol2 = trade2['volume']
            if vol1 <= 0 or vol2 <= 0:
                continue
                
            vol_diff = abs(vol1 - vol2) / max(vol1, vol2)
            if vol_diff > volume_tolerance:
                continue
            
            # MATCH FOUND!
            # Determine direction: K→M means bought on KuCoin, sold on MEXC
            if trade1['exchange'] == 'KuCoin' and trade1['side'] == 'buy':
                buy_trade = trade1
                sell_trade = trade2
                direction = 'K→M'
            elif trade2['exchange'] == 'KuCoin' and trade2['side'] == 'buy':
                buy_trade = trade2
                sell_trade = trade1
                direction = 'K→M'
            elif trade1['exchange'] == 'MEXC' and trade1['side'] == 'buy':
                buy_trade = trade1
                sell_trade = trade2
                direction = 'M→K'
            else:
                buy_trade = trade2
                sell_trade = trade1
                direction = 'M→K'
            
            matched_pairs.append({
                'direction': direction,
                'buy_exchange': buy_trade['exchange'],
                'sell_exchange': sell_trade['exchange'],
                'buy_price': buy_trade['price'],
                'sell_price': sell_trade['price'],
                'volume': min(buy_trade['volume'], sell_trade['volume']),  # Use smaller vol
                'buy_fee': buy_trade['fee'],
                'sell_fee': sell_trade['fee'],
                'time_diff_seconds': time_diff,
                'buy_trade_id': buy_trade['id'],
                'sell_trade_id': sell_trade['id']
            })
            
            # Remove matched trades from unmatched list
            break
    
    # Log matched pairs as arbitrage trades
    logged_count = 0
    for pair in matched_pairs:
        cost = pair['volume'] * pair['buy_price']
        revenue = pair['volume'] * pair['sell_price']
        profit_usdt = revenue - cost
        spread_pct = (pair['sell_price'] - pair['buy_price']) / pair['buy_price'] * 100 if pair['buy_price'] > 0 else 0
        
        log_trade(
            direction=pair['direction'],
            exchange_buy=pair['buy_exchange'],
            exchange_sell=pair['sell_exchange'],
            buy_price=pair['buy_price'],
            sell_price=pair['sell_price'],
            volume_mpc=pair['volume'],
            cost_usdt=cost,
            revenue_usdt=revenue,
            fee_buy=pair['buy_fee'],
            fee_sell=pair['sell_fee'],
            threshold_pct=threshold_pct,
            status='matched_arbitrage',
            notes=f"Auto-matched | Time-diff: {pair['time_diff_seconds']:.0f}s | IDs: {pair['buy_trade_id']}/{pair['sell_trade_id']}"
        )
        logged_count += 1
    
    # Also log any unmatched trades as single-sided (for record)
    # But don't log them as arbitrage trades
    
    return matched_pairs
