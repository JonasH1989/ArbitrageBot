"""
Trade Logger - Harmonized Multi-Exchange Trade Capture
One CSV per trading pair, all trades appended sequentially.

Harmonization: Exchange-specific API responses are normalized into
a unified schema so data is comparable across exchanges.
"""
import csv
import os
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, List, Tuple

LOG_DIR = Path("/home/openclaw/.openclaw/logs")

# Unified CSV columns for ALL trades (harmonized format)
UNIFIED_COLUMNS = [
    # Trade identity
    "trade_id",
    "internal_ts",           # When BOT fired the trade (our timestamp)
    "direction",              # "K->M" or "M->K"  
    "pair",                  # Trading pair e.g. "MPC-USDT"
    
    # Exchange 1 (Market Order - first leg)
    "ex1_exchange",          # "KUCOIN" or "MEXC"
    "ex1_order_id",          # Exchange order ID
    "ex1_type",              # "market" or "limit"
    "ex1_side",              # "buy" or "sell"
    "ex1_qty_ordered",       # Quantity ordered
    "ex1_qty_filled",        # Quantity filled
    "ex1_price_avg",         # Average fill price
    "ex1_value_usdt",        # Total value in USDT
    "ex1_fees",              # Fees paid
    "ex1_create_ts",         # Exchange timestamp (ms)
    "ex1_status",            # Exchange status
    
    # Exchange 2 (Limit Order - second leg)
    "ex2_exchange",          # "KUCOIN" or "MEXC"
    "ex2_order_id",          # Exchange order ID
    "ex2_type",              # "market" or "limit"
    "ex2_side",              # "buy" or "sell"
    "ex2_qty_ordered",       # Quantity ordered
    "ex2_qty_filled",        # Quantity filled
    "ex2_price_avg",         # Average fill price (0 if not filled)
    "ex2_value_usdt",        # Total value in USDT (0 if not filled)
    "ex2_fees",              # Fees paid
    "ex2_create_ts",         # Exchange timestamp (ms)
    "ex2_status",            # Exchange status
    
    # Limit Order Watch State
    "limit_watch_status",    # "WATCHING", "FILLED", "PARTIAL", "CANCELLED", "EXPIRED"
    "limit_last_check",      # Last time we checked fill status
    
    # Metadata
    "raw_ex1_response",      # Full JSON response from exchange 1
    "raw_ex2_response",      # Full JSON response from exchange 2
    "updated_at",            # Last update timestamp
]


def ensure_log_dir():
    """Ensure log directory exists"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def get_trade_csv_path(pair: str) -> Path:
    """Get CSV file path for a trading pair"""
    # Normalize pair format: MPCUSDT -> MPC-USDT
    normalized_pair = pair.replace("USDT", "-USDT").replace("-USDT", "USDT").upper()
    if not normalized_pair.endswith("-USDT") and not normalized_pair.endswith("USDT"):
        normalized_pair += "-USDT"
    # Fix double hyphen
    normalized_pair = normalized_pair.replace("--", "-")
    return LOG_DIR / f"{normalized_pair}_trades.csv"


def init_pair_csv(pair: str) -> Path:
    """Initialize CSV file for a trading pair if it doesn't exist"""
    ensure_log_dir()
    csv_path = get_trade_csv_path(pair)
    
    if not csv_path.exists():
        with open(csv_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(UNIFIED_COLUMNS)
    
    return csv_path


def generate_trade_id() -> str:
    """Generate unique trade ID"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return f"TRADE_{ts}"


# =============================================================================
# HARMONIZATION FUNCTIONS
# Convert exchange-specific responses to unified format
# =============================================================================

def harmonize_kucoin_order(response: dict, side: str, order_type: str, pair: str) -> Dict:
    """
    Harmonize KuCoin order response to unified format.
    
    KuCoin Market Order Response fields:
    - orderId: order ID
    - symbol: pair symbol
    - type: "market" 
    - side: "buy" or "sell"
    - size: quantity ordered
    - dealSize: quantity filled
    - dealFunds: total value
    - fee: fee amount
    - feeCurrency: currency of fee
    - createTime: timestamp in ms
    - status: "Done", "Active"
    """
    # Calculate average price
    deal_size = float(response.get('dealSize', 0) or 0)
    deal_funds = float(response.get('dealFunds', 0) or 0)
    price_avg = deal_funds / deal_size if deal_size > 0 else 0
    
    # Determine status
    status_map = {
        "Done": "FILLED",
        "Active": "OPEN",
        "cancelled": "CANCELLED",
    }
    raw_status = response.get('status', '')
    unified_status = status_map.get(raw_status, raw_status)
    
    return {
        "exchange": "KUCOIN",
        "order_id": response.get('orderId', ''),
        "type": order_type,
        "side": side.lower(),
        "qty_ordered": float(response.get('size', 0) or 0),
        "qty_filled": deal_size,
        "price_avg": price_avg,
        "value_usdt": deal_funds,
        "fees": float(response.get('fee', 0) or 0),
        "create_ts": int(response.get('createTime', 0) or 0),
        "status": unified_status,
        "raw_response": response,  # Keep full response for debugging
    }


def harmonize_mexc_order(response: dict, side: str, order_type: str, pair: str) -> Dict:
    """
    Harmonize MEXC order response to unified format.
    
    MEXC Market Order Response fields:
    - orderId: order ID
    - symbol: pair symbol (e.g. "MPCUSDT")
    - side: "BUY" or "SELL"
    - type: "MARKET"
    - orderQuantity: quantity ordered
    - orderAmount: amount ordered (for market buys in USDT)
    - quantity: quantity filled
    - amount: amount filled (in USDT value)
    - fees: fee amount
    - createTime: timestamp in ms
    - status: "Filled", "New"
    
    MEXC Limit Order Response:
    - orderId: order ID
    - symbol: pair symbol
    - side: "BUY" or "SELL"
    - type: "LIMIT"
    - price: limit price
    - quantity: quantity ordered
    - orderQuantity: same as quantity
    - amount: total value
    - dealQuantity: quantity filled
    - dealAmount: value filled
    - fees: fee amount
    - createTime: timestamp in ms
    - status: "Filled", "PartiallyFilled", "New", "Cancelled"
    """
    # Handle market vs limit order differences
    if order_type == "market":
        qty_filled = float(response.get('quantity', 0) or 0)
        value_usdt = float(response.get('amount', 0) or 0)
        qty_ordered = float(response.get('orderQuantity', 0) or 0)
        price_avg = value_usdt / qty_filled if qty_filled > 0 else 0
    else:  # limit
        qty_filled = float(response.get('dealQuantity', 0) or 0)
        value_usdt = float(response.get('dealAmount', 0) or 0)
        qty_ordered = float(response.get('quantity', 0) or 0)
        price_avg = float(response.get('price', 0) or 0)  # Limit price is the price
    
    # Determine status
    status_map = {
        "Filled": "FILLED",
        "PartiallyFilled": "PARTIAL",
        "New": "OPEN",
        "Cancelled": "CANCELLED",
    }
    raw_status = response.get('status', '')
    unified_status = status_map.get(raw_status, raw_status)
    
    return {
        "exchange": "MEXC",
        "order_id": response.get('orderId', ''),
        "type": order_type,
        "side": side.lower(),
        "qty_ordered": qty_ordered,
        "qty_filled": qty_filled,
        "price_avg": price_avg,
        "value_usdt": value_usdt,
        "fees": float(response.get('fees', 0) or 0),
        "create_ts": int(response.get('createTime', 0) or 0),
        "status": unified_status,
        "raw_response": response,  # Keep full response for debugging
    }


def harmonize_order(response: dict, exchange: str, side: str, order_type: str, pair: str) -> Dict:
    """Route to correct harmonizer based on exchange"""
    if exchange.upper() == "KUCOIN":
        return harmonize_kucoin_order(response, side, order_type, pair)
    elif exchange.upper() == "MEXC":
        return harmonize_mexc_order(response, side, order_type, pair)
    else:
        raise ValueError(f"Unknown exchange: {exchange}")


def log_trade(
    pair: str,
    internal_ts: str,
    direction: str,
    ex1_data: Dict,   # Harmonized data from market exchange
    ex2_data: Dict,   # Harmonized data from limit exchange (may be partial)
    limit_watch_status: str = "WATCHING"
) -> str:
    """
    Log a complete trade to the pair-specific CSV.
    
    Args:
        pair: Trading pair e.g. "MPC-USDT"
        internal_ts: Our internal timestamp when trade was fired
        direction: "K->M" or "M->K"
        ex1_data: Harmonized data from exchange 1 (market order)
        ex2_data: Harmonized data from exchange 2 (limit order)
        limit_watch_status: Initial status of limit order
    
    Returns:
        trade_id: Generated trade ID
    """
    trade_id = generate_trade_id()
    updated_at = datetime.now().isoformat()
    
    # Normalize pair for filename
    csv_path = init_pair_csv(pair)
    
    # Build row in unified format
    row = [
        trade_id,
        internal_ts,
        direction,
        pair,
        
        # Exchange 1 (market order)
        ex1_data.get("exchange", ""),
        ex1_data.get("order_id", ""),
        ex1_data.get("type", ""),
        ex1_data.get("side", ""),
        ex1_data.get("qty_ordered", 0),
        ex1_data.get("qty_filled", 0),
        ex1_data.get("price_avg", 0),
        ex1_data.get("value_usdt", 0),
        ex1_data.get("fees", 0),
        ex1_data.get("create_ts", 0),
        ex1_data.get("status", ""),
        
        # Exchange 2 (limit order)
        ex2_data.get("exchange", ""),
        ex2_data.get("order_id", ""),
        ex2_data.get("type", ""),
        ex2_data.get("side", ""),
        ex2_data.get("qty_ordered", 0),
        ex2_data.get("qty_filled", 0),
        ex2_data.get("price_avg", 0),
        ex2_data.get("value_usdt", 0),
        ex2_data.get("fees", 0),
        ex2_data.get("create_ts", 0),
        ex2_data.get("status", ""),
        
        # Limit watch state
        limit_watch_status,
        "",  # limit_last_check
        
        # Raw responses
        json.dumps(ex1_data.get("raw_response", {})),
        json.dumps(ex2_data.get("raw_response", {})),
        updated_at,
    ]
    
    # Append to CSV
    with open(csv_path, 'a', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(row)
    
    return trade_id


def update_limit_watch(
    trade_id: str,
    pair: str,
    new_status: str,
    qty_filled: float = None,
    price_avg: float = None,
    fees: float = None
):
    """Update limit order watch state for a trade"""
    csv_path = get_trade_csv_path(pair)
    
    if not csv_path.exists():
        return False
    
    # Read all rows
    rows = []
    with open(csv_path, 'r', newline='') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)
    
    # Find and update trade
    updated = False
    for row in rows:
        if row.get("trade_id") == trade_id:
            row["limit_watch_status"] = new_status
            row["limit_last_check"] = datetime.now().isoformat()
            
            # Update fill data if provided
            if qty_filled is not None:
                row["ex2_qty_filled"] = qty_filled
            if price_avg is not None:
                row["ex2_price_avg"] = price_avg
            if fees is not None:
                row["ex2_fees"] = fees
            
            row["updated_at"] = datetime.now().isoformat()
            updated = True
            break
    
    # Write back
    if updated:
        with open(csv_path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    
    return updated


def get_trades(pair: str, limit: int = 100) -> List[Dict]:
    """Get all trades for a trading pair"""
    csv_path = get_trade_csv_path(pair)
    
    if not csv_path.exists():
        return []
    
    trades = []
    with open(csv_path, 'r', newline='') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    
    # Reverse to get newest first
    rows = rows[::-1]
    
    for i, row in enumerate(rows):
        if i >= limit:
            break
        trades.append(row)
    
    return trades


def get_pending_limit_orders(pair: str = None) -> List[Dict]:
    """
    Get all trades with pending limit orders.
    Used by the limit order watcher to poll for fills.
    
    Args:
        pair: Optional pair filter. If None, checks all pair CSVs.
    
    Returns:
        List of trades with WATCHING status
    """
    pending = []
    
    if pair:
        # Check specific pair
        trades = get_trades(pair, limit=1000)
        for trade in trades:
            if trade.get("limit_watch_status") == "WATCHING":
                pending.append(trade)
    else:
        # Check all pair CSVs
        for csv_file in LOG_DIR.glob("*_trades.csv"):
            pair_name = csv_file.stem.replace("_trades", "")
            trades = get_trades(pair_name, limit=1000)
            for trade in trades:
                if trade.get("limit_watch_status") == "WATCHING":
                    pending.append(trade)
    
    return pending


def get_trade_summary(pair: str) -> Dict:
    """Get summary statistics for a trading pair"""
    trades = get_trades(pair, limit=10000)
    
    if not trades:
        return {
            "pair": pair,
            "total_trades": 0,
            "win_rate": "0%",
            "total_profit_usdt": 0,
            "total_profit_mpc": 0,
            "best_trade_usdt": 0,
            "avg_profit_usdt": 0,
            "pending_limit_orders": 0,
        }
    
    wins = 0
    losses = 0
    total_profit_usdt = 0
    total_profit_mpc = 0
    best_trade_usdt = 0
    pending = 0
    
    for trade in trades:
        status = trade.get("limit_watch_status", "")
        
        # Only count completed trades for stats
        if status == "FILLED":
            # Calculate profit from the trade
            ex1_value = float(trade.get("ex1_value_usdt", 0) or 0)
            ex2_value = float(trade.get("ex2_value_usdt", 0) or 0)
            ex1_fees = float(trade.get("ex1_fees", 0) or 0)
            ex2_fees = float(trade.get("ex2_fees", 0) or 0)
            
            # For K->M: Buy on KuCoin (ex1), Sell on MEXC (ex2)
            # Direction tells us which is buy/sell
            direction = trade.get("direction", "")
            
            # Calculate profit based on direction
            if "K->M" in direction:
                cost = ex1_value  # Bought on KuCoin
                revenue = ex2_value  # Sold on MEXC
            else:  # M->K
                cost = ex1_value  # Bought on MEXC
                revenue = ex2_value  # Sold on KuCoin
            
            net_profit = revenue - cost - ex1_fees - ex2_fees
            total_profit_usdt += net_profit
            
            # Calculate MPC gain (reinvested coins)
            ex2_price = float(trade.get("ex2_price_avg", 0) or 0)
            if ex2_price > 0:
                mpc_gain = net_profit / ex2_price
                total_profit_mpc += mpc_gain
            
            if net_profit > 0:
                wins += 1
            else:
                losses += 1
            
            if net_profit > best_trade_usdt:
                best_trade_usdt = net_profit
                
        elif status == "WATCHING":
            pending += 1
    
    total_completed = wins + losses
    win_rate = f"{(wins/total_completed*100):.1f}%" if total_completed > 0 else "0%"
    avg_profit = total_profit_usdt / total_completed if total_completed > 0 else 0
    
    return {
        "pair": pair,
        "total_trades": len(trades),
        "completed_trades": total_completed,
        "win_rate": win_rate,
        "total_profit_usdt": round(total_profit_usdt, 4),
        "total_profit_mpc": round(total_profit_mpc, 4),
        "best_trade_usdt": round(best_trade_usdt, 4),
        "avg_profit_usdt": round(avg_profit, 4),
        "pending_limit_orders": pending,
    }


def export_trades_csv(pair: str) -> Optional[str]:
    """Export all trades for a pair to a standalone CSV"""
    trades = get_trades(pair, limit=100000)
    
    if not trades:
        return None
    
    export_dir = LOG_DIR / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    
    filename = f"{pair}_trades_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    filepath = export_dir / filename
    
    with open(filepath, 'w', newline='') as f:
        if trades:
            writer = csv.DictWriter(f, fieldnames=trades[0].keys())
            writer.writeheader()
            writer.writerows(trades)
    
    return str(filepath)


def get_all_pairs_with_trades() -> List[str]:
    """Get list of all trading pairs that have CSV files"""
    pairs = []
    for csv_file in LOG_DIR.glob("*_trades.csv"):
        pair = csv_file.stem.replace("_trades", "")
        pairs.append(pair)
    return pairs