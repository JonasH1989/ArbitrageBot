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
                           'profit_usdt', 'profit_mpc', 'spread_pct', 'threshold_pct',
                           'fee_buy', 'fee_sell', 'net_profit_usdt', 'net_profit_mpc',
                           'status', 'notes'])


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
    net_profit_usdt = profit_usdt - fee_buy - fee_sell
    # Approximate MPC profit
    net_profit_mpc = net_profit_usdt / sell_price if sell_price > 0 else 0
    
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
            f"{profit_usdt:.4f}",
            f"{profit_usdt / sell_price:.4f}" if sell_price > 0 else "0",
            f"{spread_pct:.3f}",
            f"{threshold_pct:.3f}",
            f"{fee_buy:.4f}",
            f"{fee_sell:.4f}",
            f"{net_profit_usdt:.4f}",
            f"{net_profit_mpc:.4f}",
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
            profit_usdt = float(t[15])  # net_profit_usdt (index 15)
            profit_mpc = float(t[16])   # net_profit_mpc (index 16)
            
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

def detect_and_log_trades(kucoin_trades: list, mexc_trades: list, threshold_pct: float = 0.0) -> list:
    """
    Detect new trades from exchange trade histories and log them.
    Returns list of newly logged trades.
    """
    global _logged_kucoin_trades, _logged_mexc_trades
    
    new_trades = []
    
    # Process KuCoin trades
    for trade in kucoin_trades:
        trade_id = f"kucoin_{trade.get('trade_id', '')}"
        if trade_id not in _logged_kucoin_trades:
            _logged_kucoin_trades.add(trade_id)
            
            side = trade.get('side', '')
            price = trade.get('price', 0)
            size = trade.get('size', 0)
            funds = trade.get('funds', 0)
            fee = trade.get('fee', 0)
            
            if side == 'sell':
                direction = 'M→K'
                buy_ex = 'MEXC'
                sell_ex = 'KuCoin'
                buy_price = 0
                sell_price = price
            else:
                direction = 'K→M'
                buy_ex = 'KuCoin'
                sell_ex = 'MEXC'
                buy_price = price
                sell_price = 0
            
            log_trade(
                direction=direction,
                exchange_buy=buy_ex,
                exchange_sell=sell_ex,
                buy_price=buy_price,
                sell_price=sell_price,
                volume_mpc=size,
                cost_usdt=funds,
                revenue_usdt=funds - fee,
                fee_buy=0,
                fee_sell=fee,
                threshold_pct=threshold_pct,
                status='auto_detected',
                notes=f'KuCoin trade ID: {trade_id}'
            )
            new_trades.append({'exchange': 'KuCoin', 'trade': trade})
    
    # Process MEXC trades
    for trade in mexc_trades:
        trade_id = f"mexc_{trade.get('trade_id', '')}"
        if trade_id not in _logged_mexc_trades:
            _logged_mexc_trades.add(trade_id)
            
            side = trade.get('side', '')
            price = trade.get('price', 0)
            qty = trade.get('qty', 0)
            quote = trade.get('quote', 0)
            
            if side == 'buy':
                direction = 'M→K'
                buy_ex = 'MEXC'
                sell_ex = 'KuCoin'
            else:
                direction = 'K→M'
                buy_ex = 'KuCoin'
                sell_ex = 'MEXC'
            
            log_trade(
                direction=direction,
                exchange_buy=buy_ex,
                exchange_sell=sell_ex,
                buy_price=price,
                sell_price=price,
                volume_mpc=qty,
                cost_usdt=quote,
                revenue_usdt=quote,
                fee_buy=0,
                fee_sell=0,
                threshold_pct=threshold_pct,
                status='auto_detected',
                notes=f'MEXC trade ID: {trade_id}'
            )
            new_trades.append({'exchange': 'MEXC', 'trade': trade})
    
    return new_trades
