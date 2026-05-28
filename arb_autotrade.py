#!/usr/bin/env python3
"""
Arbitrage Auto-Trade Bot
Executes trades automatically when opportunities arise
Uses harmonized trade_logger for unified multi-exchange logging
"""
import sys
import requests
import yaml
import time
import json
import hashlib
import hmac
import base64
import json as json_lib
import math
from datetime import datetime
import os
import threading
import psutil

# Flask for HTTP logging server (optional)
try:
    from flask import Flask, jsonify, request
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False

# Import settings_sync for config access
sys.path.insert(0, '/app')
try:
    from settings_sync import get_setting, set_setting, get_pair_settings, set_pair_settings, load_config, is_debug_enabled, get_log_level
except ImportError:
    get_setting = None
    set_setting = None
    get_pair_settings = None
    set_pair_settings = None
    load_config = None
    is_debug_enabled = lambda: False

# Helper function for locale-independent float parsing
def to_float(val):
    """Parse float from string, handling comma decimal separator."""
    if isinstance(val, str):
        val = val.replace(',', '.')
    return float(val or 0)



# Import the harmonized trade logger
import csv
from trade_logger import (
    harmonize_kucoin_order,
    harmonize_mexc_order,
    get_exchange_short_id,  # Keep using original harmonize functions
    update_limit_watch,
    get_pending_limit_orders,
    get_trade_summary,
    get_trades,
    get_trade_csv_path,
    LOG_DIR as TRADE_LOG_DIR,
    log_trade,  # Import the trade logging function
    append_limit_row,
    update_limit_row,
    get_highest_ex2p_suffix,
)

from pathlib import Path

LOG_DIR = Path('/app/logs')
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / 'arb_autotrade.log'
CONFIG_FILE = '/app/config/config.yaml'
ACTIVE_FLAG_FILE = LOG_DIR / 'arb_active.flag'

# Exchange API credentials
# Load API keys from config.yaml - use same path as settings_sync (dashboard)
from pathlib import Path
_config_dir = Path('/app/config') if Path('/app/config').exists() else Path(__file__).parent / 'config'
_config_path = _config_dir / 'config.yaml'
with open(_config_path, 'r') as _f:
    _cfg = yaml.safe_load(_f)
KUCOIN_KEY = _cfg.get('kucoin', {}).get('api_key', '')
KUCOIN_SECRET = _cfg.get('kucoin', {}).get('api_secret', '')
KUCOIN_PASSPHRASE = _cfg.get('kucoin', {}).get('api_passphrase', '')
MEXC_KEY = _cfg.get('mexc', {}).get('api_key', '')
MEXC_SECRET = _cfg.get('mexc', {}).get('api_secret', '')

MEXC_MIN_USDT = 1.0

# Fee rates (REAL fees from exchanges, NOT estimates!)
MEXC_FEE_TAKER = 0.0005   # 0.05% taker fee
MEXC_FEE_MAKER = -0.0001   # -0.01% maker rebate (negative = we get paid)
KUCOIN_FEE_TAKER = 0.001   # 0.1% taker fee
KUCOIN_FEE_MAKER = 0.001   # 0.1% maker fee

# ==============================================================================
# Trading Pair Configuration - Change COIN for different coins!
# ==============================================================================
COIN_SYMBOL = "MPC-USDT"      # KuCoin format (e.g., BTC-USDT, ETH-USDT)
COIN_SYMBOL_MEXC = "MPCUSDT"  # MEXC format (e.g., BTCUSDT, ETHUSDT)
# KuCoin symbol info (fetched dynamically from API)
_kucoin_symbol_cache = None

def get_kucoin_symbol_info(symbol=None):
    """Fetch KuCoin symbol info including min order sizes from API.
    
    Returns dict with:
      - baseMinSize: min quantity in base currency (e.g. MPC)
      - quoteMinSize: min quantity in quote currency (e.g. USDT)
      - minFunds: min order value in quote currency
      - baseIncrement: quantity precision
    
    Caches result for 1 hour to avoid excessive API calls.
    """
    global _kucoin_symbol_cache
    import time
    
    # Check cache (valid for 1 hour)
    if _kucoin_symbol_cache and _kucoin_symbol_cache.get('_cached_at', 0) > time.time() - 3600:
        return _kucoin_symbol_cache
    
    symbol = symbol or COIN_SYMBOL
    try:
        ts = str(int(time.time() * 1000))
        path = f'/api/v1/symbols/{symbol}'
        sig = kucoin_sig(KUCOIN_SECRET, ts, 'GET', path)
        headers = {
            'KC-API-KEY': KUCOIN_KEY,
            'KC-API-SIGN': sig,
            'KC-API-TIMESTAMP': ts,
            'KC-API-PASSPHRASE': kucoin_passphrase_enc(KUCOIN_SECRET, KUCOIN_PASSPHRASE),
            'KC-API-KEY-VERSION': '2'
        }
        resp = requests.get(f'https://api.kucoin.com{path}', headers=headers, timeout=10)
        data = resp.json()
        if data.get('code') == '200000':
            info = data.get('data', {})
            info['_cached_at'] = time.time()
            _kucoin_symbol_cache = info
            log(f"KuCoin symbol info: baseMin={info.get('baseMinSize')}, minFunds={info.get('minFunds')}, increment={info.get('baseIncrement')}")
            return info
        else:
            log(f"KuCoin symbol API error: {data.get('msg', 'unknown')}", "WARNING")
            return None
    except Exception as e:
        log(f"Failed to fetch KuCoin symbol info: {e}", "WARNING")
        return None


def get_kucoin_min_qty(price: float) -> int:
    """Calculate minimum KuCoin order quantity based on current price.
    
    Uses KuCoin's minFunds ($0.10 for MPC) or baseMinSize (10 MPC), whichever is higher.
    Also ensures quantity is on proper increment (1 for KuCoin).
    
    Args:
        price: Current MPC-USDT price for USDT value calculation
    
    Returns:
        Minimum quantity as integer
    """
    info = get_kucoin_symbol_info()
    if not info:
        log(f"KuCoin symbol info unavailable, using fallback minQty=10", "WARNING")
        return 10
    
    min_funds = float(info.get('minFunds', 0.1))  # Default $0.10
    base_min = float(info.get('baseMinSize', 10))  # Default 10 MPC
    increment = float(info.get('baseIncrement', 1))  # Default 1 (whole numbers)
    
    # Calculate min qty based on min funds
    min_from_funds = min_funds / price if price > 0 else base_min
    
    # Take the higher of min funds-based qty or baseMinSize
    min_qty = max(min_from_funds, base_min)
    
    # Round to proper increment (KuCoin requires whole numbers for MPC)
    min_qty = max(increment, round(min_qty / increment) * increment)
    
    return int(min_qty)

# Exchange precision (decimal places) - adjust per coin as needed
MEXC_PRICE_PRECISION = 5
KUCOIN_PRICE_PRECISION = 6

TRADING_PAIR = COIN_SYMBOL

# Hourly wallet snapshot tracking
_last_snapshot_hour = None

def take_wallet_snapshot():
    """Take hourly snapshot of ALL wallet balances on both exchanges.
    
    Captures per exchange and combined:
    - MPC: free, locked, total
    - USDT: free, locked, total
    - Current MPC price
    - All other coin holdings
    """
    global _last_snapshot_hour
    now = datetime.now()
    current_hour = now.hour
    
    # Only take snapshot once per hour
    if current_hour == _last_snapshot_hour:
        return
    
    try:
        # Get ALL balances from both exchanges (new detailed format)
        mexc_bal = get_mexc_balances()
        kucoin_bal = get_kucoin_balances()
        
        coin_sym = COIN_SYMBOL.split('-')[0]
        
        # Extract MPC and USDT specifically (now returns dict with free/locked/total)
        mexc_mpc_data = mexc_bal.get(coin_sym, {'free': 0, 'locked': 0, 'total': 0})
        mexc_usdt_data = mexc_bal.get('USDT', {'free': 0, 'locked': 0, 'total': 0})
        kucoin_mpc_data = kucoin_bal.get(coin_sym, {'free': 0, 'locked': 0, 'total': 0})
        kucoin_usdt_data = kucoin_bal.get('USDT', {'free': 0, 'locked': 0, 'total': 0})
        
        mexc_mpc = mexc_mpc_data['total']
        mexc_usdt = mexc_usdt_data['total']
        kucoin_mpc = kucoin_mpc_data['total']
        kucoin_usdt = kucoin_usdt_data['total']
        
        total_mpc = mexc_mpc + kucoin_mpc
        total_usdt = mexc_usdt + kucoin_usdt
        
        # Get current MPC price for valuation
        try:
            resp_m = requests.get(f'https://api.mexc.com/api/v3/depth?symbol={COIN_SYMBOL_MEXC}&limit=1', timeout=5)
            mpc_price = float(resp_m.json().get('asks', [[0]])[0][0]) if 'asks' in resp_m.json() else 0
        except:
            mpc_price = 0
        
        mpc_value_usdt = total_mpc * mpc_price if mpc_price else 0
        total_value_usdt = total_usdt + mpc_value_usdt
        
        # Use LOG_DIR for consistency with docker volume mount
        from pathlib import Path
        LOG_DIR_SNAPSHOT = Path('/app/logs')
        csv_path = LOG_DIR_SNAPSHOT / 'wallet_snapshots.csv'
        json_path = LOG_DIR_SNAPSHOT / 'wallet_snapshots_detail.json'
        
        ts = now.strftime('%Y-%m-%d %H:%M:%S')
        
        # Write header if file doesn't exist (new detailed format)
        if not os.path.exists(csv_path):
            header = "timestamp,mpc_price,mexc_mpc_free,mexc_mpc_locked,mexc_mpc_total,mexc_usdt_free,mexc_usdt_locked,mexc_usdt_total,kucoin_mpc_free,kucoin_mpc_locked,kucoin_mpc_total,kucoin_usdt_free,kucoin_usdt_locked,kucoin_usdt_total,total_mpc,total_usdt,total_value_usdt\n"
            with open(csv_path, 'w') as f:
                f.write(header)
        
        # CSV line with all details
        csv_line = f"{ts},{mpc_price},{mexc_mpc_data['free']},{mexc_mpc_data['locked']},{mexc_mpc_data['total']},{mexc_usdt_data['free']},{mexc_usdt_data['locked']},{mexc_usdt_data['total']},{kucoin_mpc_data['free']},{kucoin_mpc_data['locked']},{kucoin_mpc_data['total']},{kucoin_usdt_data['free']},{kucoin_usdt_data['locked']},{kucoin_usdt_data['total']},{total_mpc},{total_usdt},{total_value_usdt}\n"
        
        # Append CSV
        with open(csv_path, 'a') as f:
            f.write(csv_line)
        
        _last_snapshot_hour = current_hour
        log(f"📸 Wallet Snapshot [{ts}]: {coin_sym}={total_mpc:,.0f} (${mpc_value_usdt:.2f}) | USDT={total_usdt:.2f} | Total=${total_value_usdt:.2f}")
        
        # Also save detailed JSON for complete history (with all coins)
        snapshot = {
            'timestamp': ts,
            'mpc_price': mpc_price,
            'mexc': {
                'MPC': mexc_mpc_data,
                'USDT': mexc_usdt_data,
                'all_coins': {k: v for k, v in mexc_bal.items() if k not in [coin_sym, 'USDT']}
            },
            'kucoin': {
                'MPC': kucoin_mpc_data,
                'USDT': kucoin_usdt_data,
                'all_coins': {k: v for k, v in kucoin_bal.items() if k not in [coin_sym, 'USDT']}
            },
            'totals': {
                'MPC': total_mpc,
                'USDT': total_usdt,
                'MPC_value_usdt': mpc_value_usdt,
                'total_value_usdt': total_value_usdt
            }
        }
        
        try:
            if os.path.exists(json_path):
                with open(json_path, 'r') as f:
                    all_snapshots = json.load(f)
            else:
                all_snapshots = []
            all_snapshots.append(snapshot)
            with open(json_path, 'w') as f:
                json.dump(all_snapshots, f, indent=2)
        except Exception as e:
            log(f"⚠️ Could not save detailed snapshot: {e}")
        
    except Exception as e:
        log(f"❌ Error taking wallet snapshot: {e}")



# ==============================================================================
# HTTP Logging Server (for real-time monitoring)
# ==============================================================================
HTTP_LOGS = []  # In-memory log storage
HTTP_LOGS_MAX = 10000  # Keep last 10000 logs
_http_server = None

def http_log(message: str, level: str = "INFO"):
    """Add a log entry to the HTTP log buffer."""
    global HTTP_LOGS
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
    entry = {
        'timestamp': timestamp,
        'level': level,
        'message': str(message),
        'received_at': time.time()
    }
    HTTP_LOGS.append(entry)
    # Keep only last N logs
    if len(HTTP_LOGS) > HTTP_LOGS_MAX:
        HTTP_LOGS = HTTP_LOGS[-HTTP_LOGS_MAX:]
    return entry

def start_http_log_server(port: int = 8503):
    """Start the Flask HTTP logging server in a background thread."""
    global _http_server

    if not FLASK_AVAILABLE:
        print("Flask not available, HTTP logging disabled")
        return None

    app = Flask(__name__)

    @app.route('/log', methods=['POST'])
    def add_log():
        data = request.get_json() or {}
        message = data.get('message', '')
        level = data.get('level', 'INFO')
        http_log(message, level)
        return jsonify({'status': 'ok', 'logs_count': len(HTTP_LOGS)})

    @app.route('/logs', methods=['GET'])
    def get_logs():
        last_n = request.args.get('last', 100, type=int)
        return jsonify(HTTP_LOGS[-last_n:])

    @app.route('/logs/today', methods=['GET'])
    def get_today_logs():
        today = datetime.now().date().isoformat()
        today_logs = [l for l in HTTP_LOGS if today in l['timestamp'][:10]]
        return jsonify(today_logs)

    @app.route('/logs/level/<level>', methods=['GET'])
    def get_logs_by_level(level):
        level_logs = [l for l in HTTP_LOGS if l['level'].upper() == level.upper()]
        return jsonify(level_logs[-100:])

    @app.route('/logs/file', methods=['GET'])
    def get_log_file():
        """Read the log file from disk (persistent storage)"""
        try:
            offset = request.args.get('offset', 0, type=int)
            limit = request.args.get('limit', 2000, type=int)
            with open(LOG_FILE, 'r') as f:
                lines = f.readlines()
            total = len(lines)
            start = max(0, total - offset - limit)
            end = max(0, total - offset)
            return jsonify({
                'status': 'ok',
                'file': str(LOG_FILE),
                'total_lines': total,
                'offset': offset,
                'limit': limit,
                'logs': [l.strip() for l in lines[start:end]]
            })
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)})

    @app.route('/status', methods=['GET'])
    def get_status():
        proc = psutil.Process()
        mem_info = proc.memory_info()
        try:
            cpu_pct = proc.cpu_percent()
        except:
            cpu_pct = 0.0
        return jsonify({
            'status': 'running',
            'logs_count': len(HTTP_LOGS),
            'uptime_seconds': time.time() - getattr(_http_server, 'start_time', time.time()),
            'memory_mb': mem_info.rss / 1024 / 1024,
            'cpu_percent': cpu_pct,
            'thread_count': threading.active_count(),
            'active_flag': ACTIVE_FLAG_FILE.exists(),
            'config_hash': last_config_hash
        })

    @app.route('/health', methods=['GET'])
    def get_health():
        """Health check with system metrics"""
        proc = psutil.Process()
        mem_info = proc.memory_info()
        
        # Check disk space
        try:
            disk = psutil.disk_usage('/app')
            disk_pct = disk.percent
        except:
            disk_pct = 0
        
        return jsonify({
            'status': 'healthy' if mem_info.rss < 500*1024*1024 else 'warning',
            'memory_mb': round(mem_info.rss / 1024 / 1024, 2),
            'memory_limit_mb': 500,
            'cpu_percent': round(proc.cpu_percent(), 2),
            'threads': threading.active_count(),
            'disk_percent': round(disk_pct, 1),
            'uptime_minutes': round((time.time() - getattr(_http_server, 'start_time', time.time())) / 60, 1)
        })

    @app.route('/balances', methods=['GET'])
    def get_balances():
        """Get current MPC and USDT balances from both exchanges"""
        try:
            coin = COIN_SYMBOL.split('-')[0]
            mexc_bal = get_mexc_balances()
            kucoin_bal = get_kucoin_balances()
            
            mexc_mpc = mexc_bal.get(coin, {'free': 0, 'locked': 0, 'total': 0})
            mexc_usdt = mexc_bal.get('USDT', {'free': 0, 'locked': 0, 'total': 0})
            kucoin_mpc = kucoin_bal.get(coin, {'free': 0, 'locked': 0, 'total': 0})
            kucoin_usdt = kucoin_bal.get('USDT', {'free': 0, 'locked': 0, 'total': 0})
            
            return jsonify({
                'status': 'ok',
                'pair': TRADING_PAIR,
                'mexc': {
                    'MPC': {'free': mexc_mpc['free'], 'locked': mexc_mpc['locked'], 'total': mexc_mpc['total']},
                    'USDT': {'free': mexc_usdt['free'], 'locked': mexc_usdt['locked'], 'total': mexc_usdt['total']}
                },
                'kucoin': {
                    'MPC': {'free': kucoin_mpc['free'], 'locked': kucoin_mpc['locked'], 'total': kucoin_mpc['total']},
                    'USDT': {'free': kucoin_usdt['free'], 'locked': kucoin_usdt['locked'], 'total': kucoin_usdt['total']}
                },
                'total': {
                    'MPC': mexc_mpc['total'] + kucoin_mpc['total'],
                    'USDT': mexc_usdt['total'] + kucoin_usdt['total']
                }
            })
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)}), 500

    @app.route('/api/kucoin/wallets', methods=['GET'])
    def get_kucoin_wallets():
        """Get all KuCoin wallets with balances for wallet configuration."""
        try:
            all_wallets = get_kucoin_all_wallets()
            current_wallet = 'trade'
            if get_setting:
                current_wallet = get_setting('kucoin.trading_wallet', 'trade')
            
            return jsonify({
                'status': 'ok',
                'current_wallet': current_wallet,
                'wallets': all_wallets
            })
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)}), 500

    @app.route('/api/kucoin/wallet', methods=['GET'])
    def get_kucoin_wallet_setting():
        """Get current KuCoin trading wallet setting."""
        try:
            wallet = 'trade'
            if get_setting:
                wallet = get_setting('kucoin.trading_wallet', 'trade')
            return jsonify({'status': 'ok', 'wallet': wallet})
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)}), 500

    @app.route('/api/kucoin/wallet', methods=['POST'])
    def set_kucoin_wallet_setting():
        """Set KuCoin trading wallet type."""
        try:
            data = request.get_json()
            wallet_type = data.get('wallet', 'trade')
            valid_wallets = ['trade', 'main', 'margin', 'otc', 'pool', 'market']
            if wallet_type not in valid_wallets:
                return jsonify({'status': 'error', 'message': f'Invalid wallet type. Valid: {valid_wallets}'}), 400
            
            if set_setting:
                set_setting('kucoin.trading_wallet', wallet_type)
            return jsonify({'status': 'ok', 'wallet': wallet_type})
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)}), 500

    @app.route('/api/kucoin/wallets/<coin>', methods=['GET'])
    def get_kucoin_wallets_for_coin(coin):
        """Get available wallets for a specific coin - for UI dropdown."""
        try:
            all_wallets = get_kucoin_all_wallets()
            coin_wallets = all_wallets.get(coin.upper(), {})
            
            # Format for UI dropdown
            options = []
            for wt, data in coin_wallets.items():
                if data['total'] > 0:
                    options.append({
                        'type': wt,
                        'free': data['free'],
                        'locked': data['locked'],
                        'total': data['total']
                    })
            
            return jsonify({
                'status': 'ok',
                'coin': coin.upper(),
                'options': options,
                'current': get_setting('kucoin.trading_wallet', 'trade') if get_setting else 'trade'
            })
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)}), 500

    @app.route('/clear', methods=['POST'])
    def clear_logs():
        global HTTP_LOGS
        HTTP_LOGS = []
        return jsonify({'status': 'cleared'})

    @app.route('/trades/<pair>', methods=['GET'])
    def get_trades_api(pair):
        """Get trades from CSV for a trading pair"""
        try:
            limit = int(request.args.get('limit', 50))
            
            from pathlib import Path
            normalized_pair = pair.replace('-', '').replace('/', '').upper()
            csv_path = TRADE_LOG_DIR / f"{normalized_pair}_trades.csv"
            
            if not csv_path.exists():
                return jsonify({'status': 'error', 'message': f'CSV not found: {csv_path}'}), 404
            
            # Parse header - this is the source of truth
            # NOTE: CSV uses SEMICOLON as delimiter!
            with open(csv_path, 'r', newline='') as f:
                first_line = f.readline().strip()
            
            # Parse header with SEMICOLON delimiter (not comma!)
            header_fields = [h.strip() for h in first_line.split(';')]
            
            # Read data with DictReader using SEMICOLON delimiter
            with open(csv_path, 'r', newline='') as f:
                reader = csv.DictReader(f, delimiter=';')
                dict_fieldnames = reader.fieldnames
                data_rows = list(reader)
            
            # Get latest rows
            latest_rows = data_rows[::-1][:limit]
            
            # Clean for JSON - CRITICAL: all values must be non-None strings for jsonify
            def clean_for_json(val):
                if val is None:
                    return ''
                if isinstance(val, (int, float)):
                    return val
                return str(val) if val else ''
            
            # Build response with STRIPPED header fields
            cleaned_trades = []
            for row in latest_rows:
                cleaned = {}
                for k, v in row.items():
                    # STRICT: No None values at all, and skip keys that are 'None' or 'null'
                    if k is None or k == 'None' or k == 'null' or k == '':
                        continue  # Skip malformed columns
                    if v is None:
                        cleaned[k] = ''
                    elif isinstance(v, (int, float)):
                        cleaned[k] = v
                    elif isinstance(v, dict):
                        cleaned[k] = v
                    elif isinstance(v, list):
                        cleaned[k] = v
                    else:
                        cleaned[k] = str(v) if v is not None else ''
                cleaned_trades.append(cleaned)
            
            # Build spotcheck with EXPLICIT field extraction
            sc = {}
            if cleaned_trades:
                t0 = cleaned_trades[0]
                sc = {
                    'header_field_18': header_fields[18] if len(header_fields) > 18 else 'MISSING',
                    'header_field_19': header_fields[19] if len(header_fields) > 19 else 'MISSING',
                    'header_field_20': header_fields[20] if len(header_fields) > 20 else 'MISSING',
                    'first_row_ex2_exchange': t0.get('ex2_exchange', 'MISSING'),
                    'first_row_ex2_order_id': t0.get('ex2_order_id', 'MISSING'),
                    'first_row_ex2_type': t0.get('ex2_type', 'MISSING'),
                }
            
            # Use raw json.dumps first to catch any None issues BEFORE jsonify
            import json
            response_data = {
                'status': 'ok',
                'pair': pair,
                'count': len(cleaned_trades),
                'csv_path': str(csv_path),
                'header_num_fields': len(header_fields),
                'dictreader_num_fields': len(dict_fieldnames) if dict_fieldnames else 0,
                'header_fields': header_fields,
                'dict_fieldnames': dict_fieldnames,
                'spotcheck': sc,
                'trades': cleaned_trades
            }
            
            # Pre-validate with json.dumps (more verbose error)
            try:
                json_str = json.dumps(response_data)
            except Exception as json_err:
                return jsonify({'status': 'error', 'message': f'JSON dumps failed: {json_err}', 'type': type(json_err).__name__}), 500
            
            from flask import Response
            return Response(json_str, mimetype='application/json')
        except Exception as e:
            import traceback
            return jsonify({
                'status': 'error', 
                'message': str(e),
                'trace': traceback.format_exc()
            }), 500

    @app.route('/trades/summary/<pair>', methods=['GET'])
    def get_trades_summary_api(pair):
        """Get trade summary for a pair"""
        try:
            summary = get_trade_summary(pair)
            return jsonify({
                'status': 'ok',
                'summary': summary
            })
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)}), 500

    @app.route('/trades/pending', methods=['GET'])
    def get_pending_api():
        """Get pending limit orders across all pairs"""
        try:
            pending = get_pending_limit_orders()
            return jsonify({
                'status': 'ok',
                'count': len(pending),
                'pending': pending
            })
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)}), 500

    def run_server():
        app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
        @app.route('/api/files', methods=['GET'])
        def list_files():
            import os
            log_dir = str(LOG_DIR)
            if os.path.exists(log_dir):
                files = os.listdir(log_dir)
            else:
                files = []
            return jsonify({'log_dir': log_dir, 'files': files})


    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()
    _http_server = thread
    print(f"HTTP Logging server started on port {port}")
    return thread

# Balance check functions
def get_mexc_balances() -> dict:
    """Get ALL MEXC account balances with free and locked amounts."""
    try:
        ts = str(int(time.time() * 1000))
        params = f'timestamp={ts}'
        sig = hmac.new(MEXC_SECRET.encode('utf-8'), params.encode('utf-8'), hashlib.sha256).hexdigest()
        url = f'https://api.mexc.com/api/v3/account?{params}&signature={sig}'
        headers = {'X-MEXC-APIKEY': MEXC_KEY}
        resp = requests.get(url, headers=headers, timeout=10)
        data = resp.json()

        balances = {}
        if isinstance(data, dict) and 'balances' in data:
            for b in data['balances']:
                asset = b.get('asset', '')
                if not asset:
                    continue
                free = float(b.get('free', 0) or 0)
                locked = float(b.get('locked', 0) or 0)
                total = free + locked
                if total > 0:
                    balances[asset] = {'free': free, 'locked': locked, 'total': total}
        return balances
    except Exception as e:
        log(f"Error getting MEXC balances: {e}", "ERROR")
        return {}

def get_kucoin_balances(wallet_type: str = None) -> dict:
    """Get KuCoin account balances.
    
    Args:
        wallet_type: Specific wallet type to filter ('trade', 'main', 'margin', 'otc', 'pool').
                     If None, uses setting 'kucoin.trading_wallet' or defaults to 'trade'.
    """
    try:
        # Resolve wallet type from setting if not provided
        if wallet_type is None:
            if get_setting:
                wallet_type = get_setting('kucoin.trading_wallet', 'trade')
            if not wallet_type:
                wallet_type = 'trade'
        
        ts = str(int(time.time() * 1000))
        path = '/api/v1/accounts'
        method = 'GET'
        sig = kucoin_sig(KUCOIN_SECRET, ts, method, path)

        headers = {
            'KC-API-KEY': KUCOIN_KEY,
            'KC-API-SIGN': sig,
            'KC-API-TIMESTAMP': ts,
            'KC-API-PASSPHRASE': kucoin_passphrase_enc(KUCOIN_SECRET, KUCOIN_PASSPHRASE),
            'KC-API-KEY-VERSION': '2'
        }
        resp = requests.get(f'https://api.kucoin.com{path}', headers=headers, timeout=10)
        data = resp.json()

        balances = {}
        if data.get('code') == '200000' and 'data' in data:
            for acc in data['data']:
                currency = acc.get('currency', '')
                acc_type = acc.get('type', '')
                available = float(acc.get('available', 0))
                total = float(acc.get('balance', 0))
                locked = total - available
                # Filter by wallet type if specified
                if acc_type == wallet_type and total > 0:
                    balances[currency] = {'free': available, 'locked': locked, 'total': total}
        else:
            log(f"KuCoin API error: {data}")

        return balances
    except Exception as e:
        log(f"Error getting KuCoin balances: {e}")
        return {}


def get_kucoin_all_wallets() -> dict:
    """Get ALL KuCoin account balances from ALL wallet types for wallet configuration.
    
    Returns dict: {currency: {wallet_type: {free, locked, total}, ...}, ...}
    """
    try:
        ts = str(int(time.time() * 1000))
        path = '/api/v1/accounts'
        method = 'GET'
        sig = kucoin_sig(KUCOIN_SECRET, ts, method, path)

        headers = {
            'KC-API-KEY': KUCOIN_KEY,
            'KC-API-SIGN': sig,
            'KC-API-TIMESTAMP': ts,
            'KC-API-PASSPHRASE': kucoin_passphrase_enc(KUCOIN_SECRET, KUCOIN_PASSPHRASE),
            'KC-API-KEY-VERSION': '2'
        }
        resp = requests.get(f'https://api.kucoin.com{path}', headers=headers, timeout=10)
        data = resp.json()


        all_wallets = {}  # {currency: {wallet_type: {free, locked, total}, ...}}
        if data.get('code') == '200000' and 'data' in data:
            for acc in data['data']:
                currency = acc.get('currency', '')
                acc_type = acc.get('type', '')
                available = float(acc.get('available', 0))
                total = float(acc.get('balance', 0))
                locked = total - available
                if currency not in all_wallets:
                    all_wallets[currency] = {}
                all_wallets[currency][acc_type] = {
                    'free': available,
                    'locked': locked,
                    'total': total
                }
        return all_wallets
    except Exception as e:
        log(f"Error getting KuCoin all wallets: {e}")
        return {}

def check_balances_for_trade(direction: str, qty: float, buy_price: float, sell_price: float) -> tuple:
    """Check if we have sufficient balances for a trade.

    Returns: (can_trade: bool, error_msg: str, max_tradable_qty: float)
    
    If can_trade=False but max_tradable_qty > 0, we can still trade with reduced quantity.
    """
    coin = COIN_SYMBOL.split('-')[0]

    if direction in ['M->K', 'M→K']:
        # Buying on MEXC, selling on KuCoin
        usdt_needed = qty * buy_price * 1.002  # +0.2% for fees
        
        # Get actual balances with error handling
        try:
            mexc_bal = get_mexc_balances()
            kucoin_bal = get_kucoin_balances()
        except Exception as e:
            log(f"Error getting balances for M->K: {e}", "ERROR")
            return False, f"Balance check error: {e}", 0
        
        mexc_usdt = mexc_bal.get('USDT', {}).get('total', 0) if mexc_bal else 0
        coin_available_kucoin = kucoin_bal.get(coin, {}).get('total', 0) if kucoin_bal else 0
        
        # Calculate max tradable qty based on limiting factor
        # SAFETY: Guard against division by zero
        max_from_usdt = mexc_usdt / (buy_price * 1.002) if buy_price > 0 else 0
        # Coin limit on KuCoin: how many coins can we sell?
        max_from_coin = coin_available_kucoin if coin_available_kucoin > 0 else 0
        
        # Minimum of both limits = max tradable qty
        max_tradable = min(max_from_usdt, max_from_coin)
        
        # SAFETY: Ensure max_tradable is valid (NaN check)
        if max_tradable != max_tradable:  # NaN check
            max_tradable = 0
        if max_tradable < 0:
            max_tradable = 0
        
        # Check if we have enough for the requested qty
        if usdt_needed > 0.01 and (mexc_usdt < usdt_needed or coin_available_kucoin < qty):
            # Not enough for full qty - check if we can trade with reduced qty
            min_kucoin_qty = get_kucoin_min_qty(buy_price)
            if max_tradable >= min_kucoin_qty:
                # We can still trade, just with reduced qty
                return True, "", max_tradable
            else:
                return False, f"Insufficient balance for min order ({max_tradable:.1f} < {min_kucoin_qty})", max_tradable

    elif direction in ['K->M', 'K→M']:
        # Buying on KuCoin, selling on MEXC
        usdt_needed = qty * buy_price * 1.002  # +0.2% for fees
        
        # Get actual balances with error handling
        try:
            kucoin_bal = get_kucoin_balances()
            mexc_bal = get_mexc_balances()
        except Exception as e:
            log(f"Error getting balances for K->M: {e}", "ERROR")
            return False, f"Balance check error: {e}", 0
        
        kucoin_usdt = kucoin_bal.get('USDT', {}).get('total', 0) if kucoin_bal else 0
        coin_available_mexc = mexc_bal.get(coin, {}).get('total', 0) if mexc_bal else 0
        
        # Calculate max tradable qty based on limiting factor
        # SAFETY: Guard against division by zero
        max_from_usdt = kucoin_usdt / (buy_price * 1.002) if buy_price > 0 else 0
        max_from_coin = coin_available_mexc if coin_available_mexc > 0 else 0
        max_tradable = min(max_from_usdt, max_from_coin)
        
        # SAFETY: Ensure max_tradable is valid (NaN check)
        if max_tradable != max_tradable:  # NaN check
            max_tradable = 0
        if max_tradable < 0:
            max_tradable = 0
        
        # Check if we have enough for the requested qty
        if usdt_needed > 0.01 and (kucoin_usdt < usdt_needed or coin_available_mexc < qty):
            if max_tradable >= get_kucoin_min_qty(buy_price):
                return True, "", max_tradable
            else:
                return False, f"Insufficient balance for min order ({max_tradable:.1f} < {get_kucoin_min_qty(buy_price)})", max_tradable

    return True, "", qty

def is_active():
    # Check config.yaml 'enabled' setting (dashboard sets this!)
    try:
        if get_setting is not None:
            config_enabled = get_setting(f"trading.pairs.{TRADING_PAIR}.enabled", False)
            if config_enabled:
                return True
    except:
        pass
    
    # Fallback: check flag file
    """Check if bot is marked as active"""
    return os.path.exists(ACTIVE_FLAG_FILE)

def set_active(flag):
    """Enable or disable trading"""
    if flag:
        open(ACTIVE_FLAG_FILE, 'w').write(str(datetime.now()))
    else:
        try:
            os.remove(ACTIVE_FLAG_FILE)
        except:
            pass

def log(msg, level="INFO"):
    """Enhanced logging with optional level - logs to file and HTTP server"""
    ts = datetime.now().strftime('%H:%M:%S.%f')[:-3]
    # Replace decimal separator: . (after digit) -> , (German format)
    # Only replaces . when followed by a digit (not in paths/URLs)
    import re
    msg_comma = re.sub(r'(\d)\.(\d)', r'\1,\2', str(msg))
    line = f"[{ts}] [{level}] {msg_comma}"
    print(line)

    # Check log level - DEBUG messages only logged if debug enabled
    if level == "DEBUG" and not is_debug_enabled():
        return  # Skip DEBUG messages if not in debug mode

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, 'a') as f:
            f.write(line + '\n')
    except Exception:
        pass  # Silently fail if log file can't be written
    # Also send to HTTP log server
    http_log(msg, level)

def log_decision(title, **kwargs):
    """Log a decision point with all conditions"""
    log(f"═══ {title} ═══", "DECISION")
    for key, value in kwargs.items():
        log(f"  {key}: {value}", "DECISION")
    log("─" * 50, "DECISION")

def log_condition(name, result, expected=None, details=""):
    """Log a boolean condition check"""
    symbol = "✅" if result else "❌"
    msg = f"{symbol} {name}: {result}"
    if expected:
        msg += f" (expected: {expected})"
    if details:
        msg += f" | {details}"
    log(msg, "CONDITION")

def kucoin_sig(secret, ts, method, path, body=''):
    message = f'{ts}{method}{path}{body}'
    mac = hmac.new(secret.encode(), message.encode(), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode()

def kucoin_passphrase_enc(secret, passphrase):
    """Encrypt passphrase for KuCoin API v2"""
    mac = hmac.new(secret.encode(), passphrase.encode(), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode()

def get_orderbook_levels():
    """Get detailed orderbook levels from both exchanges for multi-level spread check"""
    try:
        # MEXC depth API - get top 10 levels
        resp_m = requests.get(f'https://api.mexc.com/api/v3/depth?symbol={COIN_SYMBOL_MEXC}&limit=10', timeout=5)
        m_depth = resp_m.json()

        # KuCoin Level2 API - get top 20
        resp_k = requests.get(f'https://api.kucoin.com/api/v1/market/orderbook/level2_20?symbol={COIN_SYMBOL}', timeout=5)
        k_depth = resp_k.json().get('data', {})

        # Parse MEXC asks (sorted low to high - we need to buy)
        mexc_asks = []
        if 'asks' in m_depth:
            for price, qty in m_depth['asks'][:10]:
                mexc_asks.append({'price': float(price), 'qty': float(qty)})

        # Parse KuCoin bids (sorted high to low - we need to sell)
        kucoin_bids = []
        if 'bids' in k_depth:
            for price, qty in k_depth.get('bids', [])[:10]:
                kucoin_bids.append({'price': float(price), 'qty': float(qty)})

        # For K->M direction we also need KuCoin asks and MEXC bids
        # KuCoin asks (sorted low to high)
        kucoin_asks = []
        for price, qty in k_depth.get('asks', [])[:5]:
            kucoin_asks.append({'price': float(price), 'qty': float(qty)})

        # MEXC bids (sorted high to low) - need to parse from m_depth
        mexc_bids = []
        if 'bids' in m_depth:
            for price, qty in m_depth['bids'][:5]:
                mexc_bids.append({'price': float(price), 'qty': float(qty)})

        return {
            'mexc_asks': mexc_asks,
            'kucoin_bids': kucoin_bids,
            'kucoin_asks': kucoin_asks,
            'mexc_bids': mexc_bids
        }
    except Exception as e:
        log(f"Error getting orderbook levels: {e}")
        return None

def get_prices():
    """Get Level 1 prices from real orderbook (not ticker!)"""
    try:
        # KuCoin Level1 orderbook
        resp_k = requests.get(f'https://api.kucoin.com/api/v1/market/orderbook/level1?symbol={COIN_SYMBOL}', timeout=5)
        k_data = resp_k.json()['data']

        # MEXC Level1 from depth (not ticker!)
        resp_m = requests.get(f'https://api.mexc.com/api/v3/depth?symbol={COIN_SYMBOL_MEXC}&limit=1', timeout=5)
        m_depth = resp_m.json()

        # Extract Level 1 prices
        k_bid = float(k_data['bestBid'])
        k_ask = float(k_data['bestAsk'])

        # MEXC: asks[0] = best ask (we buy here), bids[0] = best bid (we sell here)
        m_ask = float(m_depth['asks'][0][0]) if m_depth.get('asks') else 0
        m_bid = float(m_depth['bids'][0][0]) if m_depth.get('bids') else 0

        return {
            'kucoin': {'bid': k_bid, 'ask': k_ask},
            'mexc': {'bid': m_bid, 'ask': m_ask}
        }
    except Exception as e:
        log(f"Error getting prices: {e}")
        return None

def fmt_price(price, exchange):
    """Format price with exchange-specific precision"""
    if exchange == 'mexc':
        return f"{price:.{MEXC_PRICE_PRECISION}f}"
    return f"{price:.{KUCOIN_PRICE_PRECISION}f}"

def get_trading_strategy(pair):
    """Get trading strategy for pair (usdt or mpc)"""
    return get_setting(f'trading.pairs.{pair}.strategy', 'usdt')

def execute_market_buy_kucoin(qty):
    """Buy COIN on KuCoin at market price"""
    ts = str(int(time.time() * 1000))
    body = json_lib.dumps({"clientOid": ts, "symbol": COIN_SYMBOL, "side": "buy", "type": "market", "size": str(qty)})
    log(f"📤 KUCOIN Market BUY Request: {body}", "DEBUG")
    sig = kucoin_sig(KUCOIN_SECRET, ts, 'POST', '/api/v1/orders', body)

    headers = {
        'KC-API-KEY': KUCOIN_KEY,
        'KC-API-SIGN': sig,
        'KC-API-TIMESTAMP': ts,
        'KC-API-PASSPHRASE': kucoin_passphrase_enc(KUCOIN_SECRET, KUCOIN_PASSPHRASE),
        'KC-API-KEY-VERSION': '2',
        'Content-Type': 'application/json'
    }

    resp = requests.post('https://api.kucoin.com/api/v1/orders', headers=headers, data=body, timeout=10)
    return resp.json()

def execute_limit_sell_kucoin(qty, price):
    """"Sell COIN on KuCoin at limit price"""
    ts = str(int(time.time() * 1000))
    body = json_lib.dumps({"clientOid": f"{ts}_sell", "symbol": COIN_SYMBOL, "side": "sell", "type": "limit", "size": str(qty), "price": f"{price:.6f}"})
    log(f"📤 KUCOIN Limit SELL Request: {body}", "DEBUG")
    sig = kucoin_sig(KUCOIN_SECRET, ts, 'POST', '/api/v1/orders', body)

    headers = {
        'KC-API-KEY': KUCOIN_KEY,
        'KC-API-SIGN': sig,
        'KC-API-TIMESTAMP': ts,
        'KC-API-PASSPHRASE': kucoin_passphrase_enc(KUCOIN_SECRET, KUCOIN_PASSPHRASE),
        'KC-API-KEY-VERSION': '2',
        'Content-Type': 'application/json'
    }

    resp = requests.post('https://api.kucoin.com/api/v1/orders', headers=headers, data=body, timeout=10)
    return resp.json()

def execute_limit_buy_kucoin(qty, price):
    """Buy COIN on KuCoin at limit price"""
    ts = str(int(time.time() * 1000))
    body = json_lib.dumps({"clientOid": f"{ts}_buy", "symbol": COIN_SYMBOL, "side": "buy", "type": "limit", "size": str(qty), "price": f"{price:.6f}"})
    log(f"📤 KUCOIN Limit BUY Request: {body}", "DEBUG")
    sig = kucoin_sig(KUCOIN_SECRET, ts, 'POST', '/api/v1/orders', body)

    headers = {
        'KC-API-KEY': KUCOIN_KEY,
        'KC-API-SIGN': sig,
        'KC-API-TIMESTAMP': ts,
        'KC-API-PASSPHRASE': kucoin_passphrase_enc(KUCOIN_SECRET, KUCOIN_PASSPHRASE),
        'KC-API-KEY-VERSION': '2',
        'Content-Type': 'application/json'
    }

    resp = requests.post('https://api.kucoin.com/api/v1/orders', headers=headers, data=body, timeout=10)
    return resp.json()

def execute_market_sell_kucoin(qty):
    """Sell COIN on KuCoin at market price"""
    ts = str(int(time.time() * 1000))
    body = json_lib.dumps({"clientOid": ts, "symbol": COIN_SYMBOL, "side": "sell", "type": "market", "size": str(qty)})
    log(f"📤 KUCOIN Market SELL Request: {body}", "DEBUG")
    sig = kucoin_sig(KUCOIN_SECRET, ts, 'POST', '/api/v1/orders', body)

    headers = {
        'KC-API-KEY': KUCOIN_KEY,
        'KC-API-SIGN': sig,
        'KC-API-TIMESTAMP': ts,
        'KC-API-PASSPHRASE': kucoin_passphrase_enc(KUCOIN_SECRET, KUCOIN_PASSPHRASE),
        'KC-API-KEY-VERSION': '2',
        'Content-Type': 'application/json'
    }

    resp = requests.post('https://api.kucoin.com/api/v1/orders', headers=headers, data=body, timeout=10)
    return resp.json()

def execute_market_buy_mexc(qty):
    """Buy COIN on MEXC at market price"""
    log(f"📤 MEXC Market BUY Request: quantity={qty}", "DEBUG")
    ts = str(int(time.time() * 1000))
    params = f'symbol={COIN_SYMBOL_MEXC}&side=BUY&type=MARKET&quantity={qty}&timestamp={ts}'
    sig = hmac.new(MEXC_SECRET.encode('utf-8'), params.encode('utf-8'), hashlib.sha256).hexdigest()

    url = f'https://api.mexc.com/api/v3/order?{params}&signature={sig}'
    headers = {'X-MEXC-APIKEY': MEXC_KEY}

    resp = requests.post(url, headers=headers, timeout=10)
    return resp.json()

def execute_limit_sell_mexc(qty, price):
    """Sell COIN on MEXC at limit price"""
    log(f"📤 MEXC Limit SELL Request: quantity={qty}, price={price}", "DEBUG")
    ts = str(int(time.time() * 1000))
    params = f'symbol={COIN_SYMBOL_MEXC}&side=SELL&type=LIMIT&quantity={qty}&price={price:.5f}&timestamp={ts}'
    sig = hmac.new(MEXC_SECRET.encode('utf-8'), params.encode('utf-8'), hashlib.sha256).hexdigest()

    url = f'https://api.mexc.com/api/v3/order?{params}&signature={sig}'
    headers = {'X-MEXC-APIKEY': MEXC_KEY}

    resp = requests.post(url, headers=headers, timeout=10)
    return resp.json()

def execute_limit_buy_mexc(qty, price):
    """Buy COIN on MEXC at limit price"""
    log(f"📤 MEXC Limit BUY Request: quantity={qty}, price={price}", "DEBUG")
    ts = str(int(time.time() * 1000))
    params = f'symbol={COIN_SYMBOL_MEXC}&side=BUY&type=LIMIT&quantity={qty}&price={price:.5f}&timestamp={ts}'
    sig = hmac.new(MEXC_SECRET.encode('utf-8'), params.encode('utf-8'), hashlib.sha256).hexdigest()

    url = f'https://api.mexc.com/api/v3/order?{params}&signature={sig}'
    headers = {'X-MEXC-APIKEY': MEXC_KEY}

    resp = requests.post(url, headers=headers, timeout=10)
    return resp.json()

def execute_market_sell_mexc(qty):
    """Sell COIN on MEXC at market price"""
    log(f"📤 MEXC Market SELL Request: quantity={qty}", "DEBUG")
    ts = str(int(time.time() * 1000))
    params = f'symbol={COIN_SYMBOL_MEXC}&side=SELL&type=MARKET&quantity={qty}&timestamp={ts}'
    sig = hmac.new(MEXC_SECRET.encode('utf-8'), params.encode('utf-8'), hashlib.sha256).hexdigest()

    url = f'https://api.mexc.com/api/v3/order?{params}&signature={sig}'
    headers = {'X-MEXC-APIKEY': MEXC_KEY}

    resp = requests.post(url, headers=headers, timeout=10)
    return resp.json()

def get_mexc_order_status(order_id: str) -> dict:
    """Get MEXC order fill status by order ID (for polling market orders)"""
    ts = str(int(time.time() * 1000))
    params = f'symbol={COIN_SYMBOL_MEXC}&orderId={order_id}&timestamp={ts}'
    sig = hmac.new(MEXC_SECRET.encode('utf-8'), params.encode('utf-8'), hashlib.sha256).hexdigest()

    url = f'https://api.mexc.com/api/v3/order?{params}&signature={sig}'
    headers = {'X-MEXC-APIKEY': MEXC_KEY}

    resp = requests.get(url, headers=headers, timeout=10)
    return resp.json()

def poll_mexc_market_order(order_id: str, orig_qty: float, transact_time: int, max_wait_ms: int = 2000, fallback_price: float = 0.011) -> dict:
    """Get MEXC market order fill data.

    Strategy:
    1. Try private my_trades API (with API key auth)
    2. If empty or fails, try private order status API
    3. ONLY if both fail completely, use public trades API as last resort fallback

    Args:
        order_id: The MEXC order ID from the initial response
        orig_qty: Original quantity ordered (for estimating if no trade found)
        transact_time: Transaction timestamp from initial response (ms)
        max_wait_ms: How long to wait
        fallback_price: Price to use if all methods fail

    Returns:
        dict with fill data: quantity, amount, fees, status
    """
    start_time = time.time() * 1000
    poll_interval = 200  # ms
    time_window = 2000  # 2 second window to match trade

    # ========================================================================
    # METHOD 1: Try private my_trades API (PRIMARY)
    # ========================================================================
    private_api_tried = False

    while (time.time() * 1000 - start_time) < max_wait_ms:
        try:
            # Try private my_trades API
            ts = str(int(time.time() * 1000))
            params = f'symbol={COIN_SYMBOL_MEXC}&timestamp={ts}'
            sig = hmac.new(MEXC_SECRET.encode('utf-8'), params.encode('utf-8'), hashlib.sha256).hexdigest()
            url = f'https://api.mexc.com/api/v3/myTrades?{params}&signature={sig}'
            headers = {'X-MEXC-APIKEY': MEXC_KEY}

            resp = requests.get(url, headers=headers, timeout=10)

            if resp.status_code == 200 and resp.text and len(resp.text) > 0:
                private_api_tried = True
                trades = resp.json()

                if isinstance(trades, list) and trades:
                    # Collect ALL trades matching our order by timestamp (multi-fill support!)
                    # MEXC market orders often execute as multiple partial fills
                    # DEDUPLICATE by timestamp to avoid duplicate fills
                    seen_times = set()
                    matching_trades = []
                    for trade in trades:
                        trade_time = int(trade.get('time', 0))
                        if abs(trade_time - transact_time) <= time_window:
                            qty = float(trade.get('qty', 0))
                            if qty > 0:
                                # Skip if we already saw this timestamp
                                if trade_time in seen_times:
                                    continue
                                seen_times.add(trade_time)
                                matching_trades.append(trade)
                    
                    if matching_trades:
                        # Aggregate ALL fills for this order
                        total_qty = sum(float(t.get('qty', 0)) for t in matching_trades)
                        total_value = sum(float(t.get('quoteQty', 0)) for t in matching_trades)
                        total_fee = sum(float(t.get('fee', 0) or 0) for t in matching_trades)
                        # Calculate weighted average price
                        avg_price = total_value / total_qty if total_qty > 0 else 0
                        
                        log(f"   Found {len(matching_trades)} MEXC fills (multi-fill aggregated):")
                        for i, t in enumerate(matching_trades):
                            log(f"      Fill {i+1}: qty={t.get('qty')}, price={t.get('price')}, value=${float(t.get('quoteQty', 0)):.4f}")
                        log(f"   TOTAL: qty={total_qty:.4f}, avg_price={avg_price:.6f}, value=${total_value:.4f}, fees=${total_fee:.6f}")
                        
                        return {
                            'status': 'Filled',
                            'orderId': order_id,  # Preserve original order ID
                            'quantity': str(total_qty),
                            'amount': str(total_value),
                            'fees': total_fee,  # REAL fee from API, not estimated!
                            'price': str(avg_price),  # Weighted average price!
                            'executedQty': str(total_qty),
                            'cummulativeQuoteQty': str(total_value),
                            'fills_count': len(matching_trades),  # Debug info
                            # Individual fills for log_trade(ex1_partial_fills) - structured dict format
                            'ex1_partial_fills': [
                                {
                                    'qty_filled': float(t.get('qty', 0)),
                                    'price_actual': float(t.get('price', 0)),
                                    'value_usdt': float(t.get('quoteQty', 0)),
                                    'fees': float(t.get('fee', 0) or 0),
                                    'create_ts': t.get('time', 0)
                                }
                                for t in matching_trades
                            ]
                        }
        except Exception as e:
            pass  # Silently continue to next method

        time.sleep(poll_interval / 1000)

    # ========================================================================
    # METHOD 2: Try private order status API (SECONDARY)
    # ========================================================================
    log(f"   Private API returned no trades, trying order status...")

    try:
        ts = str(int(time.time() * 1000))
        params = f'symbol={COIN_SYMBOL_MEXC}&orderId={order_id}&timestamp={ts}'
        sig = hmac.new(MEXC_SECRET.encode('utf-8'), params.encode('utf-8'), hashlib.sha256).hexdigest()
        url = f'https://api.mexc.com/api/v3/order?{params}&signature={sig}'
        headers = {'X-MEXC-APIKEY': MEXC_KEY}

        resp = requests.get(url, headers=headers, timeout=10)

        if resp.status_code == 200 and resp.text:
            order_data = resp.json()
            
            # CRITICAL FIX: Check for CANCELED status FIRST
            # If order is CANCELED, we must return qty=0, NOT fall through to fallback
            order_status = order_data.get('status', '')
            if order_status == 'CANCELED':
                log(f"   MEXC order CANCELED (order status API): qty=0")
                return {
                    'status': 'Canceled',  # Return CANCELED status, not Filled!
                    'orderId': order_id,
                    'quantity': '0',
                    'amount': '0',
                    'fees': 0,
                    'price': '0',
                    'executedQty': '0',
                    'cummulativeQuoteQty': '0'
                }
            
            # Order is not canceled - check if it has executed qty
            if order_data.get('executedQty') and float(order_data.get('executedQty', 0)) > 0:
                qty = float(order_data.get('executedQty', 0))
                quote = float(order_data.get('cummulativeQuoteQty', 0))
                price = float(order_data.get('price', 0)) or fallback_price
                # MEXC order API doesn't return fee - use configured rate as estimate
                fee_estimate = quote * MEXC_FEE_TAKER
                log(f"   Found MEXC order (order status API): qty={qty}, value=${quote:.4f}, fee=${fee_estimate:.6f} (est)")
                return {
                    'status': 'Filled',
                    'orderId': order_id,  # Preserve original order ID
                    'quantity': str(qty),
                    'amount': str(quote),
                    'fees': fee_estimate,  # Estimated - order API has no fee field
                    'price': str(price),
                    'executedQty': str(qty),
                    'cummulativeQuoteQty': str(quote)
                }
    except Exception as e:
        pass  # Silently continue to fallback

    # ========================================================================
    # METHOD 3: Public trades API (LAST RESORT FALLBACK ONLY!)
    # ========================================================================
    log(f"   WARNING: Both private APIs failed - using PUBLIC API fallback!")

    try:
        trades_url = f'https://api.mexc.com/api/v3/trades?symbol={COIN_SYMBOL_MEXC}&limit=5'
        resp = requests.get(trades_url, timeout=10)
        trades = resp.json()

        if trades and isinstance(trades, list):
            for trade in trades:
                trade_time = int(trade.get('time', 0))
                if abs(trade_time - transact_time) <= time_window:
                    qty = float(trade.get('qty', 0))
                    price = float(trade.get('price', 0))
                    quote_qty = float(trade.get('quoteQty', 0))
                    # Public API doesn't return fee - use estimate
                    fee_estimate = quote_qty * MEXC_FEE_TAKER

                    if qty > 0:
                        log(f"   PUBLIC API fallback used: qty={qty}, price={price}, fee=${fee_estimate:.6f} (est)")
                        return {
                            'status': 'Filled',
                            'orderId': f'MEXC_{transact_time}',  # Timestamp-based ID
                            'quantity': str(qty),
                            'amount': str(quote_qty),
                            'fees': fee_estimate,  # Estimated - public API has no fee field
                            'price': str(price),
                            'executedQty': str(qty),
                            'cummulativeQuoteQty': str(quote_qty)
                        }
    except:
        pass

    # ========================================================================
    # FINAL FALLBACK: Use estimated data
    # ========================================================================
    log(f"   All APIs failed - using estimated data")
    fee_est = orig_qty * fallback_price * MEXC_FEE_TAKER
    return {
        'status': 'Filled',
        'orderId': f'MEXC_{transact_time}',  # Timestamp-based ID
        'quantity': str(orig_qty),
        'amount': str(orig_qty * fallback_price),
        'fees': fee_est,  # ESTIMATED - all APIs failed, this is a fallback!
        'price': str(fallback_price),
        'executedQty': str(orig_qty),
        'cummulativeQuoteQty': str(orig_qty * fallback_price)
    }

def execute_trade_market_buy_limit_sell(exchange_market, exchange_limit, qty, buy_price, sell_price, strategy='usdt', spread_pct=0.0):
    """Execute arbitrage trade: Market Buy on one exchange, Limit Sell on another.

    GENERIC FUNCTION - Works with ANY two exchanges!
    Examples:
        - KuCoin + MEXC: execute_trade_market_buy_limit_sell("KUCOIN", "MEXC", ...)
        - Binance + KuCoin: execute_trade_market_buy_limit_sell("BINANCE", "KUCOIN", ...)
        - MEXC + Binance: execute_trade_market_buy_limit_sell("MEXC", "BINANCE", ...)

    Args:
        exchange_market: Exchange for market order (BUY) - e.g. "KUCOIN", "MEXC", "BINANCE"
        exchange_limit: Exchange for limit order (SELL) - e.g. "MEXC", "KUCOIN", "BINANCE"
        qty: Quantity to buy on market exchange
        buy_price: Expected price on market exchange
        sell_price: Expected price on limit exchange
        strategy: 'usdt' or 'coins'
        spread_pct: Spread % when trade was triggered

    Returns:
        (success, trade_id)
    """
    # Determine direction string for logging using short_ids
    # Import here to avoid circular dependency issues
    from trade_logger import get_exchange_short_id
    ex1_short = get_exchange_short_id(exchange_market.upper())
    ex2_short = get_exchange_short_id(exchange_limit.upper())
    dir_str = f"{ex1_short}->{ex2_short}"  # e.g. "KCN->MXC"

    log(f"=== EXECUTING TRADE {dir_str} (strategy={strategy}) ===")
    coin = COIN_SYMBOL.split('-')[0]
    log(f"Market BUY on {exchange_market}: {qty} {coin} @ ${buy_price:.6f}")
    log(f"Limit SELL on {exchange_limit}: @ ${sell_price:.6f}")

    # Store expected prices for logging
    market_price_expected = buy_price
    limit_price_expected = sell_price

    # Capture internal timestamp
    internal_ts = datetime.now().isoformat()

    # Track error state
    error_code = None
    error_message = None
    ex1_data = None
    ex2_data = None

    # ========================================================================
    # PRE-TRADE BALANCE CHECK
    # ========================================================================
    log(f"Checking balances for {dir_str} trade...")
    can_trade, balance_error, max_tradable = check_balances_for_trade(dir_str, qty, buy_price, sell_price)
    
    if not can_trade:
        log(f"❌ BALANCE CHECK FAILED: {balance_error}")
        # CRITICAL: Do NOT execute trade if balance check fails!
        # Log failed trade attempt and return False to prevent execution
        ex1_data = {"exchange": exchange_market.upper(), "order_id": "FAILED", "type": "market",
                    "side": "buy", "qty_ordered": qty, "qty_filled": 0,
                    "price_expected": market_price_expected, "price_actual": 0,
                    "value_usdt": 0, "fees": 0, "create_ts": 0, "status": "BALANCE_CHECK_FAILED",
                    "raw_response": {}}
        ex2_data = {"exchange": exchange_limit.upper(), "order_id": "FAILED", "type": "limit",
                    "side": "sell", "qty_ordered": 0, "qty_filled": 0,
                    "price_expected": limit_price_expected, "price_actual": 0,
                    "value_usdt": 0, "fees": 0, "create_ts": 0, "status": "NOT_PLACED",
                    "raw_response": {}}
        log(f"DEBUG: Calling log_trade() - BALANCE_CHECK_FAILED case")
        try:
            trade_id = log_trade(
                pair=TRADING_PAIR,
                internal_ts=internal_ts,
                direction=dir_str,
                ex1_data=ex1_data,
                ex2_data=ex2_data,
                limit_watch_status="ERROR",
                strategy=strategy.upper(),
                spread_pct=spread_pct,
                market_price_expected=market_price_expected,
                limit_price_expected=limit_price_expected,
                error_code="BALANCE_CHECK_FAILED",
                error_message=balance_error
            )
            log(f"✅ log_trade SUCCESS: {trade_id}")
        except Exception as e:
            log(f"❌ log_trade FAILED: {e}", "ERROR")
            import traceback
            log(f"❌ Traceback: {traceback.format_exc()}", "ERROR")
        log(f"📝 Trade blocked by balance check: {trade_id}")
        return False, trade_id
    log(f"✅ Balance check passed")

    # ========================================================================
    # STEP 0: PRE-FLIGHT BALANCE CHECK (safety net - re-check just before execution)
    # ========================================================================
    log(f"⚙️ Pre-flight balance check for {dir_str}...", "DEBUG")
    coin = COIN_SYMBOL.split('-')[0]
    
    # Get BOTH exchanges' balances
    mexc_bal = get_mexc_balances()
    kucoin_bal = get_kucoin_balances()
    
    mexc_usdt = mexc_bal.get('USDT', {}).get('total', 0) if mexc_bal else 0
    mexc_coins = mexc_bal.get(coin, {}).get('total', 0) if mexc_bal else 0
    kucoin_usdt = kucoin_bal.get('USDT', {}).get('total', 0) if kucoin_bal else 0
    kucoin_coins = kucoin_bal.get(coin, {}).get('total', 0) if kucoin_bal else 0
    
    log(f"   MEXC: USDT=${mexc_usdt:.4f}, {coin}={mexc_coins:.2f}", "DEBUG")
    log(f"   KuCoin: USDT=${kucoin_usdt:.4f}, {coin}={kucoin_coins:.2f}", "DEBUG")
    
    # Check needed funds for BOTH sides
    usdt_needed_ex1 = qty * market_price_expected * 1.002  # For market buy on exchange_market
    coins_needed_ex2 = qty  # For limit sell on exchange_limit (same qty for USDT strategy)
    price_for_ex2 = limit_price_expected
    coins_value_ex2 = coins_needed_ex2 * price_for_ex2
    
    if exchange_market.upper() == "MEXC":
        # MEXC = Market BUY (needs USDT), KUCOIN = Limit SELL (needs coins)
        if mexc_usdt < usdt_needed_ex1:
            error_code = "INSUFFICIENT_BALANCE"
            error_message = f"MEXC has insufficient USDT: ${mexc_usdt:.4f} < ${usdt_needed_ex1:.4f} needed"
            log(f"❌ {error_message}")
            return False, None
        
        if kucoin_coins < coins_needed_ex2:
            error_code = "INSUFFICIENT_BALANCE"
            error_message = f"KuCoin has insufficient {coin}: {kucoin_coins:.2f} < {coins_needed_ex2:.2f} needed"
            log(f"❌ {error_message}")
            return False, None
    
    elif exchange_market.upper() == "KUCOIN":
        # KUCOIN = Market BUY (needs USDT), MEXC = Limit SELL (needs coins)
        if kucoin_usdt < usdt_needed_ex1:
            error_code = "INSUFFICIENT_BALANCE"
            error_message = f"KuCoin has insufficient USDT: ${kucoin_usdt:.4f} < ${usdt_needed_ex1:.4f} needed"
            log(f"❌ {error_message}")
            return False, None
        
        if mexc_coins < coins_needed_ex2:
            error_code = "INSUFFICIENT_BALANCE"
            error_message = f"MEXC has insufficient {coin}: {mexc_coins:.2f} < {coins_needed_ex2:.2f} needed"
            log(f"❌ {error_message}")
            return False, None
    
    log(f"✅ Pre-flight balance check passed for both sides", "DEBUG")

    # ========================================================================
    # STEP 1: Market BUY on exchange_market
    # ========================================================================
    log(f"Step 1: {exchange_market} Market BUY...")

    # Route to correct API based on exchange
    if exchange_market.upper() == "KUCOIN":
        result1 = execute_market_buy_kucoin(qty)
        ex1_harmonize = harmonize_kucoin_order
        api_success_check = lambda r: r.get('code') == '200000'
    elif exchange_market.upper() == "MEXC":
        result1 = execute_market_buy_mexc(qty)
        ex1_harmonize = harmonize_mexc_order
        # MEXC returns {'code': -2015, 'msg': 'Insufficient balance.'} on balance errors
        # Success: {'orderId': 'xxx', 'origQty': 'xxx', ...} - no 'code' field on success
        # Error: {'code': -2015, 'msg': '...'} - has 'code' field on error
        if result1.get('code') is not None:
            # API Error - trade failed, log and abort
            error_message = f"MEXC market order failed: {result1.get('msg', str(result1))}"
            log(f"❌ {error_message}")
            ex1_data = {"exchange": "MEXC", "order_id": "FAILED", "type": "market",
                        "side": "buy", "qty_ordered": qty, "qty_filled": 0,
                        "price_expected": market_price_expected, "price_actual": 0,
                        "value_usdt": 0, "fees": 0, "create_ts": 0, "status": "REJECTED",
                        "raw_response": result1}
            ex2_data = {"exchange": "KUCOIN", "order_id": "NOT_PLACED", "type": "limit",
                        "side": "sell", "qty_ordered": 0, "qty_filled": 0,
                        "price_expected": limit_price_expected, "price_actual": 0,
                        "value_usdt": 0, "fees": 0, "create_ts": 0, "status": "NOT_PLACED",
                        "raw_response": {}}
            try:
                trade_id = log_trade(
                    pair=TRADING_PAIR, internal_ts=internal_ts, direction=dir_str,
                    ex1_data=ex1_data, ex2_data=ex2_data,
                    limit_watch_status="ERROR", strategy=strategy.upper(),
                    spread_pct=spread_pct,
                    market_price_expected=market_price_expected,
                    limit_price_expected=limit_price_expected,
                    error_code="API_ERROR", error_message=error_message
                )
                log(f"✅ log_trade SUCCESS: {trade_id}")
            except Exception as e:
                log(f"❌ log_trade FAILED: {e}", "ERROR")
            return False, trade_id
    else:
        error_code = "UNKNOWN_EXCHANGE"
        error_message = f"Unknown market exchange: {exchange_market}"
        log(f"❌ {error_message}")
        return False, None

    log(f"DEBUG {exchange_market} Response: {result1}")

    # Harmonize successful response
    # KuCoin returns {'code': '200000', 'data': {'orderId': 'xxx'}} - orderId is INSIDE data
    # MEXC returns {'orderId': 'xxx', 'origQty': 'xxx', ...} - orderId is at top level
    order_id1 = result1.get('data', {}).get('orderId') or result1.get('orderId', 'unknown')
    orig_qty1 = float(result1.get('data', {}).get('origQty', 0) or result1.get('origQty', 0) or 0)
    transact_time1 = int(result1.get('data', {}).get('transactTime', 0) or result1.get('transactTime', 0) or 0)
    log(f"✅ {exchange_market} Order placed: {order_id1} (qty={orig_qty1}, time={transact_time1})")

    # MEXC market orders are async - get actual fill from trades API
    if exchange_market.upper() == "MEXC":
        log(f"   Polling MEXC trades API for fill...")
        filled_response = poll_mexc_market_order(order_id1, orig_qty1, transact_time1, max_wait_ms=2000, fallback_price=market_price_expected)
        result1 = filled_response  # Use the filled response
        
        # Ensure orderId is set for MEXC market orders (use timestamp-based ID if not present)
        if 'orderId' not in result1 or not result1.get('orderId'):
            result1['orderId'] = f"MEXC_{transact_time1}"  # Fallback timestamp-based ID
        log(f"   After polling: status={filled_response.get('status')}, quantity={filled_response.get('quantity')}, amount={filled_response.get('amount')}")
    
    # KuCoin market orders are async - poll for fill data
    if exchange_market.upper() == "KUCOIN":
        log(f"   Polling KuCoin order for fill...")
        filled_response = poll_kucoin_market_order(order_id1, orig_qty1, max_wait_ms=3000, fallback_price=market_price_expected)
        result1 = filled_response  # Replace result with filled data
        log(f"   After polling: status={filled_response.get('status')}, dealSize={filled_response.get('dealSize', 0):.2f}, amount={filled_response.get('dealFunds', 0):.4f}")

    # Get the response data for harmonization (KuCoin nests in 'data', MEXC doesn't)
    response_data1 = result1.get('data', result1) if exchange_market.upper() == "KUCOIN" else result1
    ex1_data = ex1_harmonize(response_data1, "buy", "market", TRADING_PAIR)
    ex1_data['price_expected'] = market_price_expected
    # CRITICAL: Set qty_ordered to the PLANNED value (qty parameter), not from exchange response
    # Exchange may return 0 for qty_ordered in async market orders
    ex1_data['qty_ordered'] = qty
    # Set create_ts from transactTime if available (extracted earlier)
    if transact_time1 > 0:
        ex1_data['create_ts'] = transact_time1
    # Transfer individual fills (for multi-fill MEXC orders)
    ex1_data['ex1_partial_fills'] = filled_response.get('ex1_partial_fills', [])
    log(f"   Harmonized: qty_ordered={ex1_data['qty_ordered']:.0f}, qty_filled={ex1_data['qty_filled']:.0f}, value_usdt={ex1_data['value_usdt']:.4f}, fees={ex1_data['fees']:.4f}")

    # ========================================================================
    # STEP 1.5: Price Drift Check (Jonas' solution: freeze prices at sweep time)
    # If market price drifted from expected, recalculate sell_price to preserve spread
    # ========================================================================
    price_diff_pct = 0.0
    if ex1_data.get('price_actual', 0) > 0 and market_price_expected > 0:
        price_diff_pct = abs(ex1_data['price_actual'] - market_price_expected) / market_price_expected * 100
    
    if price_diff_pct > 0.1:  # More than 0.1% drift
        log(f"⚠️ PRICE DRIFT DETECTED: expected={market_price_expected:.6f}, actual={ex1_data['price_actual']:.6f}, drift={price_diff_pct:.3f}%")
        
        # Recalculate sell_price to preserve the ORIGINAL spread percentage
        # spread_pct was calculated as: (sell_price - buy_price) / buy_price * 100
        # So: sell_price = buy_price * (1 + spread_pct/100)
        actual_buy_price = ex1_data['price_actual']
        adjusted_sell_price = actual_buy_price * (1 + spread_pct / 100) if spread_pct > 0 else sell_price
        
        # Ensure adjusted price is above some minimum (at least covers buy + fees)
        min_sell_price = actual_buy_price * 1.001  # At least 0.1% profit
        if adjusted_sell_price < min_sell_price:
            adjusted_sell_price = min_sell_price
            log(f"   Adjusted to minimum sell price: {adjusted_sell_price:.6f}")
        else:
            log(f"   Adjusted sell price from spread: {adjusted_sell_price:.6f}")
        
        sell_price = adjusted_sell_price
        log(f"   New sell_price: {sell_price:.6f} (was: {limit_price_expected:.6f})")
    else:
        log(f"   ✅ Price stable: expected={market_price_expected:.6f}, actual={ex1_data.get('price_actual', 0):.6f}")

    # CRITICAL CHECK: qty_filled must not be 0
    if ex1_data['qty_filled'] == 0:
        error_code = "QTY_ZERO"
        error_message = f"{exchange_market} market order returned qty_filled=0! Counter-order ABORTED."
        log(f"❌ {error_message}")

        # Log trade with error but NO limit order placed
        ex2_data = {"exchange": exchange_limit.upper(), "order_id": "NOT_PLACED", "type": "limit",
                    "side": "sell", "qty_ordered": 0, "qty_filled": 0,
                    "price_expected": limit_price_expected, "price_actual": 0,
                    "value_usdt": 0, "fees": 0, "create_ts": 0, "status": "NOT_PLACED",
                    "raw_response": {}}

        log(f"DEBUG: Calling log_trade() - LIMIT_ORDER_FAILED case")
        try:
            trade_id = log_trade(
                pair=TRADING_PAIR,
                internal_ts=internal_ts,
                direction=dir_str,
                ex1_data=ex1_data,
                ex2_data=ex2_data,
                limit_watch_status="ERROR",
                strategy=strategy.upper(),
                spread_pct=spread_pct,
                market_price_expected=market_price_expected,
                limit_price_expected=limit_price_expected,
                error_code=error_code,
                error_message=error_message
            )
            log(f"✅ log_trade SUCCESS: {trade_id}")
        except Exception as e:
            log(f"❌ log_trade FAILED: {e}", "ERROR")
            import traceback
            log(f"❌ Traceback: {traceback.format_exc()}", "ERROR")
        log(f"📝 Trade logged with error: {trade_id}")
        return False, trade_id

    # ========================================================================
    # STEP 2: Determine sell quantity based on strategy
    # ========================================================================
    if strategy == 'coins':
        # Coins strategy: sell less MPC to keep the spread as MPC profit
        # USDT spent (minus fees) / sell price = MPC to sell
        usdt_to_sell = ex1_data['value_usdt'] - ex1_data['fees']
        sell_qty = usdt_to_sell / sell_price if sell_price > 0 else qty
        coin = COIN_SYMBOL.split('-')[0]
        log(f"Strategy=COINS: USDT spent={usdt_to_sell:.4f}, calculating {coin} to sell @ ${sell_price:.6f}")
    else:
        # USDT strategy: sell same quantity as bought
        sell_qty = ex1_data['qty_filled']

    # Round to integer for KuCoin (KuCoin requires whole numbers, increment=1)
    # Also ensure minimum of 10 MPC for KuCoin
    sell_qty = max(10, round(sell_qty))

    coin = COIN_SYMBOL.split('-')[0]
    log(f"Step 2: {exchange_limit} Limit SELL: {sell_qty:.4f} {coin} @ ${sell_price:.6f}")

    # Small delay before placing limit order
    time.sleep(0.5)

    # ========================================================================
    # STEP 3: Limit SELL on exchange_limit
    # ========================================================================
    log(f"Step 2: {exchange_limit} Limit SELL...")

    # Route to correct API based on exchange
    if exchange_limit.upper() == "KUCOIN":
        result2 = execute_limit_sell_kucoin(sell_qty, sell_price)
        ex2_harmonize = harmonize_kucoin_order
        limit_success_check = lambda r: r.get('code') == '200000'
    elif exchange_limit.upper() == "MEXC":
        result2 = execute_limit_sell_mexc(sell_qty, sell_price)
        ex2_harmonize = harmonize_mexc_order
        limit_success_check = lambda r: r.get('code') is None or 'orderId' in r
    else:
        error_code = "UNKNOWN_EXCHANGE"
        error_message = f"Unknown limit exchange: {exchange_limit}"
        log(f"❌ {error_message}")
        result2 = {"error": error_message}

    if limit_success_check(result2):
        order_id2 = result2.get('data', {}).get('orderId') or result2.get('orderId', 'unknown')
        log(f"✅ {exchange_limit} Order placed: {order_id2}")

        # Get the response data for harmonization
        response_data2 = result2.get('data', result2) if exchange_limit.upper() == "KUCOIN" else result2
        ex2_data = ex2_harmonize(response_data2, "sell", "limit", TRADING_PAIR)
        ex2_data['price_expected'] = limit_price_expected
        # CRITICAL: Set qty_ordered to the PLANNED value (sell_qty), not from exchange response
        # Exchange may return 0 or wrong value for limit orders
        ex2_data['qty_ordered'] = sell_qty
        # Set create_ts from order response if available
        order_ts = int(response_data2.get('createTime', 0) or 0)
        if order_ts > 0:
            ex2_data['create_ts'] = order_ts
        log(f"   Harmonized: qty_ordered={ex2_data['qty_ordered']:.0f}, qty_filled={ex2_data['qty_filled']:.0f}, price_actual={ex2_data['price_actual']:.6f}")
    else:
        log(f"❌ {exchange_limit} Error: {result2}")
        error_code = "LIMIT_ORDER_FAILED"
        error_message = f"{exchange_limit} limit order failed: {result2}"

        # Log trade even with limit order failure
        ex2_data = {"exchange": exchange_limit.upper(), "order_id": "FAILED", "type": "limit",
                    "side": "sell", "qty_ordered": sell_qty, "qty_filled": 0,
                    "price_expected": limit_price_expected, "price_actual": 0,
                    "value_usdt": 0, "fees": 0, "create_ts": 0, "status": "FAILED",
                    "raw_response": result2 if isinstance(result2, dict) else {}}

    # ========================================================================
    # STEP 4: Calculate expected profit and log trade
    # ========================================================================
    # Use EXPECTED values for profit calculation (not actual fills)
    # Logic: sell_side_value - buy_side_value - fees
    # Direction determines which side is buy/sell:
    #   - MEXC->KUCOIN: ex1=MEXC (buy), ex2=KUCOIN (sell)
    #   - KUCOIN->MEXC: ex1=KUCOIN (buy), ex2=MEXC (sell)
    # 
    # For expected profit we use:
    #   - buy_side: ex1_data['qty_filled'] * market_price_expected
    #   - sell_side: sell_qty * sell_price
    #   - fees: estimated based on fee tiers (taker ~0.1%, maker ~0.02%)
    
    buy_qty = ex1_data['qty_filled']
    buy_price = market_price_expected  # Expected price, not actual filled price
    sell_price_expected = sell_price
    
    # Buy side value (expected)
    buy_value_expected = buy_qty * buy_price
    
    # Sell side value (expected) - use planned sell_qty and expected price
    sell_value_expected = sell_qty * sell_price_expected
    
    # Estimate fees:
    # - Taker fee (market order): ~0.1% of buy_value
    # - Maker fee (limit order): ~0.02% of sell_value
    fee_taker_estimated = buy_value_expected * 0.001  # 0.1% taker
    fee_maker_estimated = sell_value_expected * 0.0002  # 0.02% maker
    total_fees_estimated = fee_taker_estimated + fee_maker_estimated
    
    # Expected profit = sell - buy - fees
    profit_usdt_expected = sell_value_expected - buy_value_expected - total_fees_estimated
    # profit_mpc_expected = MPC balance change: bought qty - sell qty (as per Doku)
    buy_qty_filled = ex1_data['qty_filled']
    sell_qty_planned = sell_qty
    profit_mpc_expected = buy_qty_filled - sell_qty_planned
    
    # Also calculate actual profit from filled values (for comparison)
    cost = ex1_data['value_usdt']
    actual_revenue = ex2_data['value_usdt']
    if actual_revenue > 0:
        revenue = actual_revenue
    else:
        revenue = sell_value_expected  # Use expected if not filled yet
    gross_profit = revenue - cost
    fee_taker = ex1_data['fees']  # Actual taker fee from market order
    fee_maker = ex2_data.get('fees', 0)  # Actual maker fee from limit (if filled)
    net_profit_actual = gross_profit - fee_taker - fee_maker
    
    log(f"   Expected profit: buy={buy_value_expected:.4f} sell={sell_value_expected:.4f} fees~{total_fees_estimated:.4f} => {profit_usdt_expected:.4f} USDT")
    log(f"   Actual profit: cost={cost:.4f} revenue={revenue:.4f} fees={fee_taker+fee_maker:.4f} => {net_profit_actual:.4f} USDT")

    # Log trade with harmonized data
    log(f"INFO: Calling log_trade() - SUCCESS case for direction={dir_str}")
    log(f"INFO: log_trade params - pair={TRADING_PAIR}, ex1_data keys={list(ex1_data.keys()) if ex1_data else None}, ex2_data keys={list(ex2_data.keys()) if ex2_data else None}")
    try:
        trade_id = log_trade(
            pair=TRADING_PAIR,
            internal_ts=internal_ts,
            direction=dir_str,
            ex1_data=ex1_data,
            ex2_data=ex2_data,
            ex1_partial_fills=ex1_data.get('ex1_partial_fills'),  # Individual MEXC fills
            ex2_partial_fills=ex2_data.get('ex2_partial_fills'),  # Individual limit fills
            limit_watch_status="WATCHING",
            strategy=strategy.upper(),
            spread_pct=spread_pct,
            market_price_expected=market_price_expected,
            limit_price_expected=limit_price_expected,
            profit_usdt_expected=profit_usdt_expected,
            profit_mpc_expected=profit_mpc_expected,
            error_code=error_code,
            error_message=error_message
        )
        log(f"DEBUG: log_trade returned trade_id={trade_id}")
        log(f"✅ log_trade SUCCESS: {trade_id}")
    except Exception as e:
        log(f"❌ log_trade FAILED: {e}", "ERROR")
        import traceback
        log(f"❌ Traceback: {traceback.format_exc()}", "ERROR")
    log(f"📝 Trade logged: {trade_id}")
    
    # Append initial ex2p1 row (pending limit order)
    try:
        append_limit_row(
            pair=TRADING_PAIR,
            trade_id=trade_id,
            exchange=ex2_data.get('exchange', ''),
            order_id=ex2_data.get('order_id', ''),
            side='sell',
            qty_ordered=sell_qty,
            qty_filled=0,
            price_actual=0,
            value_usdt=0,
            fees=0,
            create_ts=ex2_data.get('create_ts', ''),
            ex2_status='PENDING',
            limit_watch_status='WATCHING'
        )
        log(f"📝 Limit order row created: {trade_id}_ex2p1 (pending)")
    except Exception as e:
        log(f"⚠️ Failed to create limit order row: {e}", "WARNING")
    
    log(f"📝 Trade logged: {trade_id}")

    # Determine if profit is actual (limit filled) or expected (limit pending)
    profit_label = "Actual" if actual_revenue > 0 else "Expected"
    profit_note = "" if actual_revenue > 0 else " (limit pending)"
    
    log(f"=== TRADE LOGGED (pending limit fill) ===")
    log(f"Cost: ${cost:.4f} | Revenue: ${revenue:.4f}{profit_note}")
    log(f"Gross Profit: ${gross_profit:.4f} | Fees: ${fee_taker + fee_maker:.4f}")
    coin = COIN_SYMBOL.split('-')[0]
    log(f"{profit_label} Net Profit: ${net_profit:.4f} | {coin} Gain: {mpc_gain:.4f}{profit_note}")

    return True, trade_id


# Legacy alias for backward compatibility (will be removed)
def execute_trade_M_to_K(qty, buy_price, sell_price, strategy='usdt', spread_pct=0.0):
    """Legacy: Use execute_trade_market_buy_limit_sell('MEXC', 'KUCOIN', ...) instead"""
    return execute_trade_market_buy_limit_sell('MEXC', 'KUCOIN', qty, buy_price, sell_price, strategy, spread_pct)


def execute_trade_K_to_M(qty, buy_price, sell_price, strategy='usdt', spread_pct=0.0):
    """Legacy: Use execute_trade_market_buy_limit_sell('KUCOIN', 'MEXC', ...) instead"""
    return execute_trade_market_buy_limit_sell('KUCOIN', 'MEXC', qty, buy_price, sell_price, strategy, spread_pct)




def check_limit_order_fills():
    """
    Background task: Check pending limit orders and update status.
    
    Smart polling strategy:
    - Only check when IDLE (no positive spread available)
    - Only check orders where price has crossed the limit
    - Check interval: 180s when IDLE
    """
    pending = get_pending_limit_orders(TRADING_PAIR)

    if not pending:
        return

    log(f"🔍 Checking {len(pending)} pending limit orders...")

    # Get current prices for pre-filter
    try:
        resp_m = requests.get(f'https://api.mexc.com/api/v3/ticker/price?symbol={COIN_SYMBOL_MEXC}', timeout=5)
        resp_k = requests.get(f'https://api.kucoin.com/api/v1/market/orderbook/level1?symbol={COIN_SYMBOL}', timeout=5)
        mexc_price = float(resp_m.json().get('price', 0)) if resp_m.status_code == 200 else 0
        kucoin_data = resp_k.json().get('data', {}) if resp_k.status_code == 200 else {}
        kucoin_price = float(kucoin_data.get('bestAsk', 0)) or float(kucoin_data.get('price', 0))
    except:
        mexc_price = 0
        kucoin_price = 0

    for trade in pending:
        raw_trade_id = trade.get('trade_id', '')
        
        # ONLY process _ex2sum rows (parent rows for limit orders)
        # Skip _ex2pN sub-rows - they are partial fills, not the main limit order
        if not raw_trade_id.endswith('_ex2sum'):
            continue
        
        # Extract base trade_id (remove _ex2sum suffix)
        trade_id = raw_trade_id.replace('_ex2sum', '')
        
        direction = trade.get('direction', '')
        ex2_exchange = trade.get('ex2', '')
        # Normalize: CSV stores 'KCN'/'MXC', code checks 'KUCOIN'/'MEXC'
        ex2_exchange_normalized = 'KUCOIN' if ex2_exchange == 'KCN' else ('MEXC' if ex2_exchange == 'MXC' else ex2_exchange)
        ex2_order_id = trade.get('ex2_order_id', '')
        ex2_price_expected = to_float(trade.get('ex2_price_expected', 0))

        if not ex2_order_id or ex2_order_id == 'FAILED':
            continue

        # Poll exchange for order status - ALWAYS check, no pre-filter skip
        # (limit orders may have filled hours ago regardless of current price)
        try:
            if ex2_exchange_normalized == 'KUCOIN':
                # Check KuCoin order status
                ts = str(int(time.time() * 1000))
                path = f'/api/v1/orders/{ex2_order_id}'
                sig = kucoin_sig(KUCOIN_SECRET, ts, 'GET', path)

                headers = {
                    'KC-API-KEY': KUCOIN_KEY,
                    'KC-API-SIGN': sig,
                    'KC-API-TIMESTAMP': ts,
                    'KC-API-PASSPHRASE': kucoin_passphrase_enc(KUCOIN_SECRET, KUCOIN_PASSPHRASE),
                    'KC-API-KEY-VERSION': '2'
                }

                resp = requests.get(f'https://api.kucoin.com{path}', headers=headers, timeout=10)
                try:
                    raw = resp.json()
                    if not isinstance(raw, dict):
                        log(f"⚠️ KuCoin order check: non-dict response type={type(raw)}, order_id={ex2_order_id}")
                        continue
                    data = raw.get('data', {})
                except Exception as e:
                    log(f"⚠️ KuCoin JSON parse error for order {ex2_order_id}: {e}")
                    continue

                if not isinstance(data, dict):
                    # "order does not exist" or other non-dict response = order was cancelled/never filled
                    log(f"⚠️ KuCoin order {ex2_order_id}: API returns {type(data).__name__}, falling back to fills API")
                    data = {'isActive': True, 'dealSize': 0}  # Treat as active/pending until fills API confirms

                status = data.get('status', '')
                deal_size = float(data.get('dealSize', 0) or 0)
                is_active = data.get('isActive', True)

                # KuCoin filled orders: status='Done' OR isActive=False with dealSize > 0
                # Also check fills API for any fill data
                fills_data = []
                total_qty = deal_size
                total_cost = float(data.get('dealFunds', 0) or 0)
                total_fees = 0.0

                # Always try fills API to get accurate fill data (handles partial fills, non-dict responses)
                try:
                    fills_path = f'/api/v1/fills?orderId={ex2_order_id}'
                    fills_sig = kucoin_sig(KUCOIN_SECRET, ts, 'GET', fills_path)
                    fills_headers = {
                        'KC-API-KEY': KUCOIN_KEY,
                        'KC-API-SIGN': fills_sig,
                        'KC-API-TIMESTAMP': ts,
                        'KC-API-PASSPHRASE': kucoin_passphrase_enc(KUCOIN_SECRET, KUCOIN_PASSPHRASE),
                        'KC-API-KEY-VERSION': '2'
                    }
                    resp_fills = requests.get(f'https://api.kucoin.com{fills_path}', headers=fills_headers, timeout=10)
                    try:
                        fills_raw = resp_fills.json()
                        if isinstance(fills_raw, dict) and resp_fills.status_code == 200:
                            # KuCoin fills API returns data as dict with 'items' list inside
                            data_field = fills_raw.get('data', {})
                            if isinstance(data_field, dict):
                                fills_data = data_field.get('items', []) or []
                            elif isinstance(data_field, list):
                                fills_data = data_field
                            else:
                                fills_data = []
                        else:
                            fills_data = []
                    except:
                        fills_data = []
                except:
                    fills_data = []


                # Aggregate fills if any found
                if fills_data:
                    total_qty = 0.0
                    total_cost = 0.0
                    total_fees = 0.0
                    for fill in fills_data:
                        qty = float(fill.get('size', 0) or 0)
                        price = float(fill.get('price', 0) or 0)
                        fee = float(fill.get('fee', 0) or 0)
                        total_qty += qty
                        total_cost += qty * price
                        total_fees += fee
                    fill_count = len(fills_data)
                    if fill_count > 1:
                        log(f"   INFO: {trade_id}: aggregated {fill_count} partial fills => {total_qty} MPC")


                # Determine order status for row update
                is_filled = status == 'Done' or (not is_active and total_qty > 0) or (len(fills_data) > 0)
                
                if is_filled and total_qty > 0:
                    # Case 1: Order FILLED - update existing ex2p1 row to FILLED
                    # Find the highest existing ex2p row and update it
                    existing_suffix = get_highest_ex2p_suffix(trade_id, TRADING_PAIR)
                    if existing_suffix == 0:
                        # No ex2p row exists - create first one (shouldn't happen normally)
                        append_limit_row(
                            pair=TRADING_PAIR,
                            trade_id=trade_id,
                            exchange='KUCOIN',
                            order_id=ex2_order_id,
                            side='sell',
                            qty_ordered=ex2_price_expected,
                            qty_filled=total_qty,
                            price_actual=total_cost/total_qty if total_qty > 0 else 0,
                            value_usdt=total_cost,
                            fees=total_fees,
                            create_ts=str(data.get('createTime', '')),
                            ex2_status='FILLED',
                            limit_watch_status='FILLED'
                        )
                    else:
                        # Update existing row with aggregated fill data
                        update_limit_row(
                            pair=TRADING_PAIR,
                            trade_id=trade_id,
                            suffix=existing_suffix,
                            qty_filled=total_qty,
                            price_actual=total_cost/total_qty if total_qty > 0 else 0,
                            value_usdt=total_cost,
                            fees=total_fees,
                            ex2_status='FILLED',
                            limit_watch_status='FILLED'
                        )
                    
                    # Also write individual fills as sub-rows if multiple fills
                    if fills_data and len(fills_data) > 1:
                        for i, fill in enumerate(fills_data):
                            fill_qty = float(fill.get('size', 0) or 0)
                            fill_price = float(fill.get('price', 0) or 0)
                            fill_fee = float(fill.get('fee', 0) or 0)
                            fill_ts = fill.get('time', '')
                            
                            append_limit_row(
                                pair=TRADING_PAIR,
                                trade_id=trade_id,
                                exchange='KUCOIN',
                                order_id=f"{ex2_order_id}_fill{i+1}",
                                side='sell',
                                qty_ordered=fill_qty,
                                qty_filled=fill_qty,
                                price_actual=fill_price,
                                value_usdt=fill_qty * fill_price,
                                fees=fill_fee,
                                create_ts=fill_ts,
                                ex2_status='FILLED',
                                limit_watch_status='FILLED'
                            )
                    
                    update_limit_watch(trade_id, TRADING_PAIR, 'FILLED',
                                     qty_filled=total_qty,
                                     price_actual=total_cost/total_qty if total_qty > 0 else 0,
                                     fees=total_fees,
                                     create_ts=str(data.get('createdAt', '')))
                    log(f"LIMIT FILLED: {trade_id} ({total_qty} MPC @ {total_cost/total_qty if total_qty > 0 else 0:.5f})")
                
                elif total_qty > 0 and is_active:
                    # Case 3: Order PARTIALLY FILLED - update ex2p1 to PARTIAL
                    existing_suffix = get_highest_ex2p_suffix(trade_id, TRADING_PAIR)
                    if existing_suffix > 0:
                        update_limit_row(
                            pair=TRADING_PAIR,
                            trade_id=trade_id,
                            suffix=existing_suffix,
                            qty_filled=total_qty,
                            price_actual=total_cost/total_qty if total_qty > 0 else 0,
                            fees=total_fees,
                            ex2_status='PARTIAL',
                            limit_watch_status='PARTIAL'
                        )
                    
                    update_limit_watch(trade_id, TRADING_PAIR, 'PARTIAL', qty_filled=total_qty)
                
                else:
                    # Order still pending (isActive=True, no fills yet) - do nothing
                    # Will be checked again next poll
                    pass

            elif ex2_exchange_normalized == 'MEXC':
                # Check MEXC order status via /api/v3/order endpoint
                # MEXC's executedQty is CUMULATIVE - no aggregation needed
                ts = str(int(time.time() * 1000))
                params = f'symbol={COIN_SYMBOL_MEXC}&orderId={ex2_order_id}&timestamp={ts}'
                sig = hmac.new(MEXC_SECRET.encode('utf-8'), params.encode('utf-8'), hashlib.sha256).hexdigest()
                url = f'https://api.mexc.com/api/v3/order?{params}&signature={sig}'
                headers_req = {'X-MEXC-APIKEY': MEXC_KEY}

                resp = requests.get(url, headers=headers_req, timeout=10)
                try:
                    raw = resp.json()
                    if not isinstance(raw, dict):
                        log(f"⚠️ MEXC order check: non-dict response type={type(raw)}, order_id={ex2_order_id}")
                        continue
                    data = raw
                except Exception as e:
                    log(f"⚠️ MEXC JSON parse error for order {ex2_order_id}: {e}")
                    continue

                status = data.get('status', '')
                qty_filled = float(data.get('executedQty', 0) or 0)
                amount_filled = float(data.get('cummulativeQuoteQty', 0) or 0)

                if status == 'FILLED' and qty_filled > 0:
                    # Case 1: MEXC Order FILLED
                    existing_suffix = get_highest_ex2p_suffix(trade_id, TRADING_PAIR)
                    if existing_suffix == 0:
                        append_limit_row(
                            pair=TRADING_PAIR,
                            trade_id=trade_id,
                            exchange='MEXC',
                            order_id=ex2_order_id,
                            side='sell',
                            qty_ordered=ex2_price_expected,
                            qty_filled=qty_filled,
                            price_actual=amount_filled/qty_filled if qty_filled > 0 else 0,
                            value_usdt=amount_filled,
                            fees=float(data.get('fee', 0) or 0),
                            create_ts=str(data.get('createTime', '')),
                            ex2_status='FILLED',
                            limit_watch_status='FILLED'
                        )
                    else:
                        update_limit_row(
                            pair=TRADING_PAIR,
                            trade_id=trade_id,
                            suffix=existing_suffix,
                            qty_filled=qty_filled,
                            price_actual=amount_filled/qty_filled if qty_filled > 0 else 0,
                            value_usdt=amount_filled,
                            fees=float(data.get('fee', 0) or 0),
                            ex2_status='FILLED',
                            limit_watch_status='FILLED'
                        )
                    
                    update_limit_watch(trade_id, TRADING_PAIR, 'FILLED',
                                     qty_filled=qty_filled,
                                     price_actual=amount_filled/qty_filled if qty_filled > 0 else 0,
                                     fees=float(data.get('fee', 0) or 0),
                                     create_ts=str(data.get('createTime', '')))
                    log(f"LIMIT FILLED: {trade_id}")
                
                elif status == 'PARTIALLY_FILLED' and qty_filled > 0:
                    # Case 3: MEXC Order PARTIALLY FILLED
                    existing_suffix = get_highest_ex2p_suffix(trade_id, TRADING_PAIR)
                    if existing_suffix > 0:
                        update_limit_row(
                            pair=TRADING_PAIR,
                            trade_id=trade_id,
                            suffix=existing_suffix,
                            qty_filled=qty_filled,
                            price_actual=amount_filled/qty_filled if qty_filled > 0 else 0,
                            fees=float(data.get('fee', 0) or 0),
                            ex2_status='PARTIAL',
                            limit_watch_status='PARTIAL'
                        )
                    
                    update_limit_watch(trade_id, TRADING_PAIR, 'PARTIAL', qty_filled=qty_filled)

        except Exception as e:
            log(f"⚠️ Error checking order {ex2_order_id}: {e}")

def poll_kucoin_market_order(order_id: str, orig_qty: float, max_wait_ms: int = 3000, fallback_price: float = 0.011) -> dict:
    """Get KuCoin market order fill data by polling the order status.
    
    KuCoin market orders are async - the initial response only gives orderId.
    We need to poll to get the actual fill data (dealSize, dealFunds).
    
    Args:
        order_id: The KuCoin order ID from the initial response
        orig_qty: Original quantity ordered (for fallback if no fill found)
        max_wait_ms: How long to wait for fill (default 3 seconds)
        fallback_price: Price to use if all methods fail
    
    Returns:
        dict with fill data: quantity, amount, fees, status, price
    """
    start_time = time.time() * 1000
    poll_interval = 200  # ms
    
    while (time.time() * 1000 - start_time) < max_wait_ms:
        try:
            # Check order status via KuCoin API
            ts = str(int(time.time() * 1000))
            path = f'/api/v1/orders/{order_id}'
            sig = kucoin_sig(KUCOIN_SECRET, ts, 'GET', path)
            
            headers = {
                'KC-API-KEY': KUCOIN_KEY,
                'KC-API-SIGN': sig,
                'KC-API-TIMESTAMP': ts,
                'KC-API-PASSPHRASE': kucoin_passphrase_enc(KUCOIN_SECRET, KUCOIN_PASSPHRASE),
                'KC-API-KEY-VERSION': '2',
            }
            
            resp = requests.get(f'https://api.kucoin.com{path}', headers=headers, timeout=10)
            data = resp.json()
            
            if data.get('code') == '200000':
                order_data = data.get('data', {})
                # KuCoin doesn't always return 'status' field - check isActive instead
                # If isActive=False and dealSize > 0, order is filled
                is_active = order_data.get('isActive', True)
                status = order_data.get('status', '')
                deal_size = float(order_data.get('dealSize', 0) or 0)
                deal_funds = float(order_data.get('dealFunds', 0) or 0)
                fee = float(order_data.get('fee', 0) or 0)
                
                # Order is done if: status='Done' OR isActive=False with dealSize > 0
                if (status == 'Done' or (not is_active and deal_size > 0)) and deal_size > 0:
                    price = deal_funds / deal_size if deal_size > 0 else fallback_price
                    log(f"   Found KuCoin fill: qty={deal_size}, value=${deal_funds:.4f}, fee=${fee:.4f}")
                    return {
                        'status': 'FILLED',
                        'quantity': deal_size,
                        'amount': deal_funds,
                        'fees': fee,
                        'price': price,
                        'dealSize': deal_size,
                        'dealFunds': deal_funds,
                        'fee': fee,
                        'orderId': order_id,
                        # Individual fills for log_trade(ex1_partial_fills)
                        'ex1_partial_fills': [{
                            'qty_filled': deal_size,
                            'price_actual': price,
                            'value_usdt': deal_funds,
                            'fees': fee,
                            'create_ts': int(order_data.get('createdAt', 0) or 0)
                        }]
                    }
                elif status == 'Active' or is_active:
                    # Order still filling, keep polling
                    log(f"   KuCoin order {order_id} still Active, polling again...", "DEBUG")
        
        except Exception as e:
            log(f"   Error polling KuCoin order: {e}", "DEBUG")
        
        time.sleep(poll_interval / 1000)
    
    # Timeout - return estimated data based on original quantity
    log(f"   KuCoin polling timeout for order {order_id}, using fallback")
    return {
        'status': 'TIMEOUT',
        'quantity': orig_qty,
        'amount': orig_qty * fallback_price,
        'fees': orig_qty * fallback_price * KUCOIN_FEE_TAKER,  # ESTIMATED - timeout fallback
        'price': fallback_price,
        'dealSize': orig_qty,
        'dealFunds': orig_qty * fallback_price,
        'fee': orig_qty * fallback_price * KUCOIN_FEE_TAKER,  # ESTIMATED - timeout fallback
        'orderId': order_id
    }


def calculate_best_trade(ob_data, min_trade_qty, threshold_start, stop_threshold, strategy, for_follow_up_trade=False):
    """Calculate best trade using CORRECT multi-level accumulation.
    
    CORRECT ALGORITHM (per 8 Trade Cases):
    1. Erst L1单独 prüfen - wenn genug Volumen + Spread >= threshold → Trade
    2. Nur wenn nicht genug: Level akkumulieren (L1+L2, L1+L2+L3, ...)
    3. An jedem Akkumulations-Punkt: Spread + Volumen checken
    4. trade_vol = MIN(akkumulierte dünnere Seite, andere Seite Vol an diesem Punkt)
    5. Dünnere Seite kann sich ändern → dann ggf. andere Trade-Richtung!
    
    Threshold-Logik:
    - for_follow_up_trade=True: threshold_stop (während Hysteresis aktiv)
    - for_follow_up_trade=False: threshold_start (erster Trade)
    """
    threshold = stop_threshold if for_follow_up_trade else threshold_start
    
    best_trade = None
    
    if not ob_data:
        return None
    
    # Get orderbook levels
    kucoin_bids = ob_data.get('kucoin_bids', [])  # KuCoin sell depth (we buy here)
    kucoin_asks = ob_data.get('kucoin_asks', [])  # KuCoin buy depth (we sell here)
    mexc_asks = ob_data.get('mexc_asks', [])      # MEXC sell depth (we buy here)
    mexc_bids = ob_data.get('mexc_bids', [])      # MEXC buy depth (we sell here)
    
    # =========================================================================
    # Direction M→K: KuCoin Bid > MEXC Ask → Buy MEXC, Sell KuCoin
    # =========================================================================
    best_mk = _find_best_trade_for_direction(
        kucoin_bids,  # sell side (we sell here = Limit side)
        mexc_asks,    # buy side (we buy here = Market side)
        'M→K',
        'KUCOIN',     # Limit exchange
        'MEXC',       # Market exchange
        min_trade_qty,
        threshold,
        strategy
    )
    if best_mk:
        best_trade = best_mk
    
    # =========================================================================
    # Direction K→M: MEXC Bid > KuCoin Ask → Buy KuCoin, Sell MEXC
    # =========================================================================
    best_km = _find_best_trade_for_direction(
        mexc_bids,   # sell side (we sell here = Limit side)
        kucoin_asks, # buy side (we buy here = Market side)
        'K→M',
        'MEXC',      # Limit exchange
        'KUCOIN',    # Market exchange
        min_trade_qty,
        threshold,
        strategy
    )
    if best_km:
        # Compare profits and pick better
        profit_mk = best_mk.get('profit_usdt' if strategy != 'coins' else 'profit_mpc', 0) if best_mk else 0
        profit_km = best_km.get('profit_usdt' if strategy != 'coins' else 'profit_mpc', 0) if best_km else 0
        if best_trade is None or profit_km > profit_mk:
            best_trade = best_km
    
    return best_trade


def _find_best_trade_for_direction(sell_levels, buy_levels, direction, limit_ex, market_ex, min_trade_qty, threshold, strategy):
    """Find best trade for a specific direction (M→K or K→M).
    
    IMPORTANT: The thinner side gets the Market Order, the thicker side gets Limit Order.
    We don't know which is which just from the direction!
    
    Algorithm:
    1. AkkumuliereLevel auf BEIDEN Seiten
    2. Nach jedem Level-Paar: Prüfe welche Seite dünner ist
    3. trade_vol = MIN(akkumulierte dünnere Seite, dickere Seite an diesem Punkt)
    4. Spread muss >= threshold sein für dieses Level-Paar
    5. Dünnere Seite = Market Order
    """
    best = None
    
    if not sell_levels or not buy_levels:
        return None
    
    # Akkumuliere auf BEIDEN Seiten gleichzeitig
    cum_sell = 0  # Akkumulierte Volumen auf Sell side
    cum_buy = 0   # Akkumulierte Volumen auf Buy side
    
    for sell_level in sell_levels:
        cum_sell += sell_level['qty']
        
        # Für JEDES Sell Level: akkumuliere Buy Side bis dieses Level erreicht
        cum_buy = 0
        for buy_level in buy_levels:
            cum_buy += buy_level['qty']
            
            # Spread: sell price - buy price
            spread = sell_level['price'] - buy_level['price']
            spread_pct = (spread / buy_level['price']) * 100 if buy_level['price'] > 0 else 0
            
            # Spread muss >= threshold sein für DIESES Level-Paar
            if spread_pct < threshold:
                break  # Nächstes Buy Level hat vielleicht besseren Spread
            
            #trade_vol = MIN(dünnere Seite, dickere Seite an diesem Punkt)
            #Die dünnere Seite = die mit dem KLEINEREN akkumulierten Volumen
            thinner_vol = min(cum_sell, cum_buy)
            thicker_vol = max(cum_sell, cum_buy)
            
            trade_vol = thinner_vol  # Wir können nur das handeln was die dünnere Seite hergibt
            
            if trade_vol >= min_trade_qty:
                # Gültiger Trade gefunden! -> SOFORT return, nicht weiter akkumulieren!
                # Wir wollen nur genau genug Volume für die Mindestorder, nicht mehr
                profit_usdt = spread * trade_vol
                profit_mpc = profit_usdt / buy_level['price'] if buy_level['price'] > 0 else 0
                
                # Bestimme welche Seite Market Order bekommt (die dünnere)
                if cum_sell <= cum_buy:
                    # Sell side ist dünner → Market BUY auf Sell side
                    actual_market_ex = limit_ex
                    actual_limit_ex = market_ex
                    actual_market_side = 'BUY'
                    actual_limit_side = 'SELL'
                else:
                    # Buy side ist dünner → Market SELL auf Buy side
                    actual_market_ex = market_ex
                    actual_limit_ex = limit_ex
                    actual_market_side = 'SELL'
                    actual_limit_side = 'BUY'
                
                return {
                    'dir': direction,
                    'buy': buy_level['price'],
                    'sell': sell_level['price'],
                    'buy_ex': actual_market_ex if actual_market_side == 'BUY' else actual_limit_ex,
                    'sell_ex': actual_limit_ex if actual_limit_side == 'SELL' else actual_market_ex,
                    'pct': spread_pct,
                    'vol': trade_vol,
                    'cum_sell': cum_sell,
                    'cum_buy': cum_buy,
                    'thinner_side': 'SELL' if cum_sell <= cum_buy else 'BUY',
                    'profit_usdt': profit_usdt,
                    'profit_mpc': profit_mpc,
                    'strategy': strategy
                }
    
    return best


def main():
    log("=== AUTO-TRADE BOT STARTED ===")
    log("Strategy: Coin-Gewinn (COIN akkumulieren)")
    log("Principle: ONE TRADE AT A TIME")
    log(f"Logging: Harmonized CSV per pair -> {TRADING_PAIR}_trades.csv")

    # Ensure logs directory exists
    os.makedirs('/app/logs', exist_ok=True)
    
    # Start TradeLogger background service
    try:
        from trade_logger_service import start as start_logger
        start_logger()
        log("TradeLogger service gestartet")
    except Exception as e:
        log(f"TradeLogger start fehlgeschlagen: {e}")

    # Thresholds - load from config directly (avoiding settings_sync import issues)
    try:
        config_path = Path('/app/config/config.yaml')
        with open(config_path, 'r') as f:
            cfg = yaml.safe_load(f)
        pair_cfg = cfg.get('trading', {}).get('pairs', {}).get(TRADING_PAIR, {})
        START_THRESHOLD = pair_cfg.get('threshold_start', 1.0)
        # NOTE: STOP_THRESHOLD constant is deprecated - thresholds are read dynamically in the loop
        STOP_THRESHOLD = pair_cfg.get('threshold_stop', 0.5)  # DEPRECATED, use threshold_stop variable
        log(f"Thresholds geladen: start={START_THRESHOLD}%, stop={STOP_THRESHOLD}%")
    except Exception as e:
        log(f"Konnte thresholds nicht aus config laden: {e}, verwende defaults")
        START_THRESHOLD = 1.0
        STOP_THRESHOLD = 0.5

    # State machine
    STATE_WAITING = 'WAITING'
    STATE_RUNNING = 'RUNNING'
    state = STATE_WAITING
    trade_in_progress = False
    hysteresis_armed = False  # Hysteresis flag for start/stop behavior
    last_spread_ok = None  # Track spread condition changes
    last_pair_enabled = None  # Track pair enabled changes

    # Start HTTP logging server for real-time monitoring
    start_http_log_server(port=8505)
    http_log("Bot gestartet", "INFO")
    last_config_hash = None  # Track config changes for immediate logging
    heartbeat_counter = 0
    last_heartbeat_ts = time.time()
    last_cpu_mem = (0, 0)
    last_limit_check = 0

    # NOTE: pair_enabled is READ-ONLY from config!
    # It can ONLY be changed by:
    #   1. Dashboard (user toggles the checkbox)
    #   2. Container restart (safety flag file, see below)
    # NO other code may write to this value!
    
    # Read enabled status from config (READ ONLY - never write!)
    config = load_config()
    pair_enabled = get_setting(f'trading.pairs.{TRADING_PAIR}.enabled', False)
    log(f"Pair {TRADING_PAIR} enabled in config: {pair_enabled}")

    # SAFETY: On every startup, bot starts DISABLED
    # User must manually enable via Dashboard after redeploy
    # This is the proven approach that works reliably
    log(f"SAFETY: Setting pair_enabled=False on startup (bot must be enabled via Dashboard)", "CONFIG")
    set_pair_settings(TRADING_PAIR, enabled=False)
    pair_enabled = False
    log(f"SAFETY: Bot started in disabled state", "CONFIG")
    
    while True:
        # Heartbeat log every 30s - shows bot is alive + Mem/CPU
        heartbeat_counter += 1
        if time.time() - last_heartbeat_ts >= 30:
            proc = psutil.Process()
            mem_mb = proc.memory_info().rss / 1024 / 1024
            cpu_pct = proc.cpu_percent(interval=0.1)
            last_heartbeat_ts = time.time()
            log(f"HEARTBEAT alive=30s | mem={mem_mb:.1f}MB | cpu={cpu_pct:.1f}% | threads={threading.active_count()}", "INFO")
        
        # Re-read all settings from config each cycle
        pair_enabled = get_setting(f'trading.pairs.{TRADING_PAIR}.enabled', False)
        current_strategy = get_setting(f'trading.pairs.{TRADING_PAIR}.strategy', 'usdt')
        threshold_start = get_setting(f'trading.pairs.{TRADING_PAIR}.threshold_start', 1.0)
        threshold_stop = get_setting(f'trading.pairs.{TRADING_PAIR}.threshold_stop', 0.5)
        current_log_level = get_log_level()

        # Check if any setting changed - log immediately if so
        import hashlib
        config_hash = f"{pair_enabled}|{current_strategy}|{threshold_start}|{threshold_stop}|{current_log_level}"
        if config_hash != last_config_hash:
            log_decision("CONFIG_CHANGED",
                pair_enabled=str(pair_enabled),
                strategy=current_strategy,
                log_level=f"Level {current_log_level}",
                threshold=f"{threshold_start:.2f}%",
                threshold_stop=f"{threshold_stop:.2f}%"
            )
            last_config_hash = config_hash

        prices = get_prices()
        if not prices:
            time.sleep(1)
            continue

        k = prices['kucoin']
        m = prices['mexc']

        # Check M->K (Buy MEXC, Sell KuCoin)
        spread_mk = k['bid'] - m['ask']
        spread_pct_mk = (spread_mk / m['ask']) * 100 if m['ask'] > 0 else 0

        # Check K->M (Buy KuCoin, Sell MEXC)
        spread_km = m['bid'] - k['ask']
        spread_pct_km = (spread_km / k['ask']) * 100 if k['ask'] > 0 else 0

        # Get real orderbook levels
        ob_data = get_orderbook_levels()

        # Calculate minimum trade quantity (dynamically from exchange APIs)
        mexc_min_qty = round((MEXC_MIN_USDT + 0.1) / m['ask']) if m['ask'] > 0 else 10
        kucoin_min_qty = get_kucoin_min_qty(k['bid']) if k['bid'] > 0 else 10
        min_trade_qty = max(mexc_min_qty, kucoin_min_qty)

        # Find best tradeable spread using BIDIRECTIONAL VOLUME ACCUMULATION
        # This replaces the old sweep that fixed one side - now both sides accumulate!
        strategy = get_trading_strategy(TRADING_PAIR)
        best_trade = calculate_best_trade(ob_data, min_trade_qty, threshold_start, threshold_stop, strategy)

        # Log sweep results every 30 seconds
        if int(time.time()) % 10 == 0:
            if ob_data:
                total_mexc = sum(x['qty'] for x in ob_data['mexc_asks'][:5])
                total_kucoin = sum(x['qty'] for x in ob_data['kucoin_bids'][:5])
                strategy = get_trading_strategy(TRADING_PAIR)
                coin = COIN_SYMBOL.split('-')[0]
                log(f"Sweep: {strategy.upper()} strategy | MEXC top5={total_mexc:.0f} {coin}, KuCoin top5={total_kucoin:.0f} {coin}, min={min_trade_qty}")
                if best_trade:
                    coin = COIN_SYMBOL.split('-')[0]
                    log(f"  Best: {best_trade['dir']} @ {best_trade['pct']:.3f}% | Vol={best_trade['vol']:.0f} {coin} | profit_usdt=${best_trade['profit_usdt']:.4f} | profit_{coin}={best_trade['profit_mpc']:.4f}")
                else:
                    log(f"  No tradeable spread found (spread below thresholds or insufficient volume)")

        # Log volume check every 15s
        if int(time.time()) % 15 == 0 and ob_data:
            total_mexc_vol = sum(x['qty'] for x in ob_data['mexc_asks'][:5])
            total_kucoin_vol = sum(x['qty'] for x in ob_data['kucoin_bids'][:5])
            coin = COIN_SYMBOL.split('-')[0]
            log(f"Orderbook: MEXC top5={total_mexc_vol:.0f} {coin}, KuCoin top5={total_kucoin_vol:.0f} {coin}, min_needed={min_trade_qty}")
            coin = COIN_SYMBOL.split('-')[0]
            log(f"Best trade: {best_trade['dir']} @ {best_trade['pct']:.3f}% | Vol={best_trade['vol']:.0f} {coin}" if best_trade else "No tradeable spread")

        if not ob_data:
            # Fallback when orderbook fetch fails
            vol_for_mexc = round((MEXC_MIN_USDT + 1) / m['ask']) if m['ask'] > 0 else 10
            vol_for_kucoin = max(get_kucoin_min_qty(k['bid']), vol_for_mexc)
        else:
            # Always define these for logging
            vol_for_mexc = round((MEXC_MIN_USDT + 1) / m['ask']) if m['ask'] > 0 else 10
            vol_for_kucoin = max(get_kucoin_min_qty(k['bid']), vol_for_mexc)


        # Log every 30 seconds
        if int(time.time()) % 10 == 0:
            log(f"Prices: K={fmt_price(k['bid'],'kucoin')}/{fmt_price(k['ask'],'kucoin')} | M={fmt_price(m['bid'],'mexc')}/{fmt_price(m['ask'],'mexc')}")
            log(f"  M->K spread: {spread_pct_mk:.2f}% | K->M spread: {spread_pct_km:.2f}%")

        # Check limit order fills every 10 seconds
        if time.time() - last_limit_check > 10:
            check_limit_order_fills()
            last_limit_check = time.time()

        # Determine which spread direction is profitable
        profitable_spread = max(spread_pct_km, spread_pct_mk)
        direction = "K→M" if spread_pct_km >= spread_pct_mk else "M→K"

        # Log periodic status every 30 seconds for monitoring
        if int(time.time()) % 10 == 0:
            log_decision("STATUS_CHECK",
                state=state,
                pair_enabled=str(pair_enabled),
                strategy=current_strategy,
                log_level=f"Level {get_log_level()}",
                spread_mk=f"{spread_pct_mk:.3f}%",
                spread_km=f"{spread_pct_km:.3f}%",
                best_spread=f"{profitable_spread:.3f}%",
                direction=direction,
                threshold=f"{threshold_start:.2f}%",
                threshold_stop=f"{threshold_stop:.2f}%",
                vol_mexc=f"{vol_for_mexc:.0f}",
                vol_kucoin=f"{vol_for_kucoin:.0f}"
            )

        # Trade BOTH directions when profitable!
        # Check for hourly wallet snapshot (BEFORE spread check, so it runs every loop)
        take_wallet_snapshot()
        
        if not pair_enabled or not is_active():
            state = STATE_WAITING
            if int(time.time()) % 10 == 0:
                log(f"INAKTIV - keine Trades")
            time.sleep(1)
            continue

        # Log condition check only when state CHANGES (reduce spam)
        current_spread_ok = profitable_spread >= threshold_start
        if current_spread_ok != last_spread_ok:
            log_condition("Spread >= START_THRESHOLD",
                current_spread_ok,
                expected=f"{threshold_start}%",
                details=f"actual={profitable_spread:.3f}%"
            )
            last_spread_ok = current_spread_ok

        # State machine logic
        # IMPORTANT: Check balance BEFORE setting trade_in_progress=True
        # This prevents the flag from being set when we can't actually trade
        # Hysteresis logic: Once activated by threshold_start, stay active until threshold_stop is breached
        # Check if we need to arm or disarm hysteresis
        if not hysteresis_armed and profitable_spread >= threshold_start:
            # First trigger - arm hysteresis
            hysteresis_armed = True
            log(f"🔘 HYSTERESIS ARMED: spread={profitable_spread:.2f}% >= {threshold_start}%", "DECISION")
        elif hysteresis_armed and profitable_spread < threshold_stop:
            # Breach of stop threshold - disarm hysteresis
            hysteresis_armed = False
            log(f"🔴 HYSTERESIS DISARMED: spread={profitable_spread:.2f}% < {threshold_stop}%", "DECISION")

        if state == STATE_WAITING:
            # Trade if: spread >= threshold_start (initial activation) OR (hysteresis armed AND spread >= threshold_stop)
            trade_condition = (profitable_spread >= threshold_start) or (hysteresis_armed and profitable_spread >= threshold_stop)
            if trade_condition and not trade_in_progress:
                
                # Pre-flight balance check BEFORE entering trade
                # Determine direction and simulate balance check
                if best_trade:
                    dir_check = best_trade['dir']  # e.g. 'M→K' or 'K→M'
                elif spread_pct_km >= spread_pct_mk:
                    dir_check = 'K→M'
                else:
                    dir_check = 'M→K'
                
                # Estimate quantities
                if best_trade:
                    check_qty = math.floor(best_trade['vol'])
                    check_buy = best_trade['buy']
                    check_sell = best_trade['sell']
                else:
                    check_qty = min(vol_for_mexc, vol_for_kucoin)
                    check_buy = m['ask'] if dir_check == 'M→K' else k['ask']
                    check_sell = k['bid'] if dir_check == 'M→K' else m['bid']
                
                # Pre-check: can we actually trade?
                can_trade, balance_error, max_tradable = check_balances_for_trade(dir_check, check_qty, check_buy, check_sell)
                if not can_trade:
                    # CANNOT trade - do NOT set trade_in_progress, stay in WAITING
                    if int(time.time()) % 5 == 0:  # Log every 5s to avoid spam
                        log(f"⛔ TRIGGER SKIPPED: {balance_error}", "BALANCE")
                    return  # ← EXIT early, do NOT enter trade
                
                # Balance OK - proceed with trade (possibly with reduced qty)
                # Override volume with max_tradable if needed
                if max_tradable < check_qty and max_tradable >= get_kucoin_min_qty(best_trade.get('buy', 0.017)):
                    log(f"⚠️ Reduced trade qty: {check_qty:.0f} → {math.floor(max_tradable):.0f} (wallet limit)", "BALANCE")
                    if best_trade:
                        best_trade['vol'] = math.floor(max_tradable)
                
                # Balance OK - proceed with trade
                log(f"🚀 TRIGGER: spread={profitable_spread:.2f}% >= threshold={threshold_start}%", "DECISION")
                state = STATE_RUNNING
                trade_in_progress = True
                # Hysteresis stays armed - we already set it above

                # Execute best trade found by sweep
                if best_trade:
                    # KuCoin requires WHOLE NUMBER quantities (baseIncrement=1 for MPC-USDT)
                    # Fractional quantities like 119.34 cause 'Order size increment invalid' error
                    # IMPORTANT: For Market BUY orders (takes liquidity from orderbook)
                    # -> use math.floor() to NEVER exceed available volume
                    # For Limit SELL orders (creates new order on book) -> can use round()
                    vol_for_mexc = math.floor(best_trade['vol'])
                    vol_for_kucoin = math.floor(best_trade['vol'])
                    trade_strategy = best_trade.get('strategy', current_strategy)
                    coin = COIN_SYMBOL.split('-')[0]
                    log(f"🚀 Executing: {best_trade['dir']} @ {best_trade['pct']:.3f}% | Vol={best_trade['vol']:.0f} {coin} | strategy={trade_strategy}")
                    if best_trade['dir'] == 'K→M':
                        success, trade_id = execute_trade_market_buy_limit_sell('KUCOIN', 'MEXC', vol_for_kucoin, best_trade['buy'], best_trade['sell'], trade_strategy, best_trade['pct'])
                    else:
                        success, trade_id = execute_trade_market_buy_limit_sell('MEXC', 'KUCOIN', vol_for_mexc, best_trade['buy'], best_trade['sell'], trade_strategy, best_trade['pct'])
                elif spread_pct_km >= spread_pct_mk:
                    success, trade_id = execute_trade_market_buy_limit_sell('KUCOIN', 'MEXC', math.floor(vol_for_kucoin), k['ask'], m['bid'], current_strategy, spread_pct_km)
                else:
                    success, trade_id = execute_trade_market_buy_limit_sell('MEXC', 'KUCOIN', math.floor(vol_for_mexc), m['ask'], k['bid'], current_strategy, spread_pct_mk)
                
                # Only complete trade if SUCCESS=True
                if success:
                    log(f"✅ Trade executed - Limit Order placed successfully")
                    # CRITICAL: Re-fetch orderbook BEFORE checking for next trade
                    # The market buy changed the orderbook - we need fresh data
                    log(f"📡 Refreshing orderbook after trade execution...")
                    ob_data = get_orderbook_levels()
                    if ob_data:
                        log(f"📡 Orderbook refreshed - checking for next trade")
                    else:
                        log(f"⚠️ Orderbook refresh failed - waiting...")
                        time.sleep(2)
                    
                    # Reset trade_in_progress to allow next trade check
                    trade_in_progress = False
                    state = STATE_RUNNING  # Stay in RUNNING to check for next trade
                else:
                    log(f"⚠️ Trade execution failed (API error). Resetting.")
                    trade_in_progress = False
                    state = STATE_WAITING
        
        # Re-check spread before EACH trade in RUNNING state (critical bug fix!)
        # Re-check spread before EACH trade in RUNNING state
        # IMPORTANT: Use FRESH orderbook data (not stale get_prices data)!
        if state == STATE_RUNNING and not trade_in_progress:
            # Get FRESH orderbook data for spread check (not stale prices from get_prices)
            ob_data = get_orderbook_levels()
            if not ob_data:
                # No fresh data - pause and retry next cycle
                time.sleep(1)
                continue
            
            # Calculate fresh spread from orderbook data
            # SAFEGUARD: Check all list accesses to prevent IndexError crashes
            kucoin_bids = ob_data.get('kucoin_bids', [])
            mexc_asks = ob_data.get('mexc_asks', [])
            mexc_bids = ob_data.get('mexc_bids', [])
            kucoin_asks = ob_data.get('kucoin_asks', [])
            
            if not kucoin_bids or not mexc_asks:
                log(f"⚠️ Orderbook empty - pausing and retrying next cycle")
                time.sleep(1)
                continue
            
            best_k_bid = kucoin_bids[0]['price'] if kucoin_bids else 0
            best_m_ask = mexc_asks[0]['price'] if mexc_asks else 0
            best_m_bid = mexc_bids[0]['price'] if mexc_bids else 0
            best_k_ask = kucoin_asks[0]['price'] if kucoin_asks else 0
            
            fresh_spread_pct_mk = ((best_k_bid - best_m_ask) / best_m_ask * 100) if best_m_ask > 0 else 0
            fresh_spread_pct_km = ((best_m_bid - best_k_ask) / best_k_ask * 100) if best_k_ask > 0 else 0
            fresh_profitable_spread = max(fresh_spread_pct_mk, fresh_spread_pct_km)
            
            # STOP if spread below stop threshold
            if fresh_profitable_spread < threshold_stop:
                log(f"⏹ STOPPING: fresh spread={fresh_profitable_spread:.3f}% < STOP_THRESHOLD={threshold_stop}%")
                state = STATE_WAITING
                trade_in_progress = False
                continue
            
            # START check: spread must still be >= threshold_start (not just > stop)
            # This prevents rapid-fire trades when spread is collapsing toward zero
            if fresh_profitable_spread < threshold_start:
                log(f"⏸ PAUSING: fresh spread={fresh_profitable_spread:.3f}% < START_THRESHOLD={threshold_start}% (but > stop)")
                state = STATE_WAITING
                trade_in_progress = False
                continue
            
            # Recalculate best trade with fresh orderbook data
            best_trade = calculate_best_trade(ob_data, min_trade_qty, threshold_start, threshold_stop, current_strategy, for_follow_up_trade=True)
            
            if not best_trade:
                log(f"No tradeable spread found (spread below thresholds or insufficient volume)")
                state = STATE_WAITING
                trade_in_progress = False
                continue
            
            # Execute trade
            # Pre-flight balance check before setting trade_in_progress
            dir_check = best_trade['dir']
            check_qty = math.floor(best_trade['vol'])
            can_trade, balance_error, max_tradable = check_balances_for_trade(dir_check, check_qty, best_trade['buy'], best_trade['sell'])
            if not can_trade:
                log(f"⛔ TRADE BLOCKED: {balance_error}")
                trade_in_progress = False
                state = STATE_WAITING
                continue
            
            # Override volume with max_tradable if wallet is limiting
            if max_tradable < check_qty and max_tradable >= get_kucoin_min_qty(best_trade.get('buy', 0.017)):
                log(f"⚠️ Reduced trade qty: {check_qty:.0f} → {math.floor(max_tradable):.0f} (wallet limit)", "BALANCE")
                best_trade['vol'] = math.floor(max_tradable)
            
            trade_in_progress = True
            vol_for_mexc = math.floor(best_trade['vol'])
            vol_for_kucoin = math.floor(best_trade['vol'])
            trade_strategy = best_trade.get('strategy', current_strategy)
            coin = COIN_SYMBOL.split('-')[0]
            log(f"🚀 Executing: {best_trade['dir']} @ {best_trade['pct']:.3f}% | Vol={best_trade['vol']:.0f} {coin} | strategy={trade_strategy}")
            if best_trade['dir'] == 'K→M':
                success, trade_id = execute_trade_market_buy_limit_sell('KUCOIN', 'MEXC', vol_for_kucoin, best_trade['buy'], best_trade['sell'], trade_strategy, best_trade['pct'])
            else:
                success, trade_id = execute_trade_market_buy_limit_sell('MEXC', 'KUCOIN', vol_for_mexc, best_trade['buy'], best_trade['sell'], trade_strategy, best_trade['pct'])
            
            # Only complete trade if SUCCESS=True
            if success:
                log(f"✅ Trade executed - waiting for limit fill confirmation")
                state = STATE_WAITING
                trade_in_progress = False  # Allow next trade to start
            else:
                log(f"⚠️ Trade execution failed (API error). Resetting.")
                trade_in_progress = False
                state = STATE_WAITING

        # Check for hourly wallet snapshot
        take_wallet_snapshot()
        
        time.sleep(1)  # Check every second

if __name__ == '__main__':
    main()

