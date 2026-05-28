"""
Settings Sync Module
Ensures all configurable values are always in sync with config.yaml

This module is COMPLETELY STANDALONE - does not import from config package
to avoid dependency issues. All config operations are direct YAML file I/O.
"""

import yaml
import hashlib
import traceback
from pathlib import Path
from typing import Any, Dict
from datetime import datetime
import threading

# Config file path - use DYNAMIC path based on runtime environment
# In Docker: /app/config/config.yaml
# Locally: relative to this file's location
self_dir = Path(__file__).parent
in_docker = Path('/app').exists()

if in_docker:
    SETTINGS_FILE = Path("/app/config/config.yaml")
else:
    SETTINGS_FILE = self_dir / "config.yaml"

# Config change tracking - use a class to avoid global scope issues
class _ConfigChangeTracker:
    _log = []
    _lock = threading.Lock()
    
    @classmethod
    def append(cls, entry):
        with cls._lock:
            cls._log.append(entry)
            if len(cls._log) > 100:
                cls._log = cls._log[-100:]
    
    @classmethod
    def get_all(cls):
        with cls._lock:
            return list(cls._log)

def _get_file_hash() -> str:
    """Get SHA256 hash of config file content"""
    if SETTINGS_FILE.exists():
        with open(SETTINGS_FILE, 'rb') as f:
            return hashlib.sha256(f.read()).hexdigest()[:16]
    return "empty"

def _log_config_change(path: str, value: Any, caller_info: str):
    """Log a config change with caller information"""
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
    entry = {
        'timestamp': ts,
        'path': path,
        'value': str(value)[:100],
        'caller': caller_info,
        'file_hash': _get_file_hash()
    }
    _ConfigChangeTracker.append(entry)
    import sys
    print(f"[CONFIG_CHANGE] {ts} | {path} = {str(value)[:50]}... | From: {caller_info}", file=sys.stderr)

def get_config_change_log():
    """Get the config change log"""
    return _ConfigChangeTracker.get_all()

def get_last_config_hash() -> str:
    """Get the current config file hash"""
    return _get_file_hash()

def _get_caller_info() -> str:
    """Get information about who called set_setting"""
    # Get the full stack trace
    stack = traceback.extract_stack()
    # Find our call in the stack (skip internal calls)
    caller_info = "unknown"
    for i, frame in enumerate(stack):
        if 'settings_sync' in frame.filename:
            continue  # Skip internal calls
        if frame.filename.endswith('arb_autotrade.py') or frame.filename.endswith('dashboard.py'):
            caller_info = f"{frame.filename}:{frame.lineno} ({frame.name})"
            break
    return caller_info

def load_config() -> Dict[str, Any]:
    """Load config from YAML file with better error reporting"""
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, 'r') as f:
                config = yaml.safe_load(f)
                if config is None:
                    return {}
                return config
        except yaml.YAMLError as e:
            # Provide helpful error message with file path and line info
            error_msg = f"YAML Error in {SETTINGS_FILE}: {e}"
            if hasattr(e, 'problem_mark') and e.problem_mark:
                error_msg += f"\n  Line {e.problem_mark.line + 1}, Column {e.problem_mark.column + 1}"
            if hasattr(e, 'context') and e.context:
                error_msg += f"\n  Context: {e.context}"
            # Try to read raw content for debugging
            try:
                with open(SETTINGS_FILE, 'r') as f:
                    lines = f.readlines()
                    if hasattr(e, 'problem_mark') and e.problem_mark and e.problem_mark.line < len(lines):
                        error_msg += f"\n  Problem line: {lines[e.problem_mark.line].rstrip()}"
                        if e.problem_mark.line > 0:
                            error_msg += f"\n  Previous line: {lines[e.problem_mark.line - 1].rstrip()}"
            except:
                pass
            # Print to stderr for visibility in Docker logs
            import sys
            print(error_msg, file=sys.stderr)
            return {}
    return {}

def save_config(config: Dict[str, Any]):
    """Save config to YAML file"""
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SETTINGS_FILE, 'w') as f:
        yaml.dump(config, f, default_flow_style=False)

def get_setting(path: str, default: Any = None) -> Any:
    """
    Get setting using dot notation.
    e.g. get_setting('trading.pairs.MPC-USDT.enabled')
    """
    config = load_config()
    keys = path.split('.')
    value = config
    for k in keys:
        if isinstance(value, dict):
            value = value.get(k, default)
        else:
            return default
    return value if value is not None else default

def set_setting(path: str, value: Any):
    """
    Set setting using dot notation and save immediately.
    e.g. set_setting('trading.pairs.MPC-USDT.enabled', False)
    
    Logs all changes with caller info for debugging config corruption issues.
    """
    config = load_config()
    
    # GUARD: If config is empty/None, something is wrong with the YAML file
    # Do NOT save empty config - this would wipe all settings!
    if not config or not isinstance(config, dict):
        import sys
        print(f"⚠️ WARNING: Config file corrupted or empty! Refusing to save.", file=sys.stderr)
        print(f"   Will NOT overwrite config.yaml with empty config.", file=sys.stderr)
        print(f"   Please fix config.yaml manually!", file=sys.stderr)
        return  # ← EXIT without saving!
    
    # Log the change BEFORE applying
    caller_info = _get_caller_info()
    _log_config_change(path, value, caller_info)
    
    # TRACKER: Extra logging for safety-critical changes (especially enabled=False)
    if 'enabled' in path and value is False:
        import traceback as tb, sys
        print(f"\n🚨 SAFETY TRACKER: enabled=False set!", file=sys.stderr)
        print(f"   Path: {path}", file=sys.stderr)
        print(f"   Caller: {caller_info}", file=sys.stderr)
        print(f"   Full stack trace:", file=sys.stderr)
        for line in tb.format_stack()[:10]:
            print(f"     {line.strip()}", file=sys.stderr)
        print(f"\n", file=sys.stderr)
    
    keys = path.split('.')
    d = config
    for k in keys[:-1]:
        if k not in d:
            d[k] = {}
        d = d[k]
    d[keys[-1]] = value
    save_config(config)

def get_pair_settings(pair: str) -> Dict[str, Any]:
    """Get all settings for a trading pair"""
    return {
        'enabled': get_setting(f'trading.pairs.{pair}.enabled', False),
        'strategy': get_setting(f'trading.pairs.{pair}.strategy', 'usdt'),
        'alert_enabled': get_setting(f'trading.pairs.{pair}.alert_enabled', True),
        'threshold_start': get_setting(f'trading.pairs.{pair}.threshold_start', 1.0),
        'threshold_stop': get_setting(f'trading.pairs.{pair}.threshold_stop', 0.5),
    }

def set_pair_settings(pair: str, **kwargs):
    """Set multiple settings for a trading pair"""
    for key, value in kwargs.items():
        set_setting(f'trading.pairs.{pair}.{key}', value)

def get_alert_settings() -> Dict[str, Any]:
    """Get alert settings"""
    return {
        'enabled': get_setting('alert.enabled', True),
        'volume': get_setting('alert.volume', 0.3),
    }

def set_alert_settings(enabled: bool = None, volume: float = None):
    """Set alert settings"""
    if enabled is not None:
        set_setting('alert.enabled', enabled)
    if volume is not None:
        set_setting('alert.volume', volume)

def get_api_keys(exchange: str) -> Dict[str, str]:
    """Get API keys for exchange"""
    if exchange == 'kucoin':
        return {
            'api_key': get_setting('kucoin.api_key', ''),
            'api_secret': get_setting('kucoin.api_secret', ''),
            'api_passphrase': get_setting('kucoin.api_passphrase', ''),
        }
    elif exchange == 'mexc':
        return {
            'api_key': get_setting('mexc.api_key', ''),
            'api_secret': get_setting('mexc.api_secret', ''),
        }
    return {}

def set_api_keys(exchange: str, **keys):
    """Set API keys for exchange"""
    for key, value in keys.items():
        set_setting(f'{exchange}.{key}', value)

def get_all_pairs() -> list:
    """Get list of all configured trading pairs"""
    pairs = get_setting('trading.pairs', {})
    return list(pairs.keys()) if pairs else ['MPC-USDT']

def add_pair(pair: str):
    """Add a new trading pair with default settings"""
    if not get_setting(f'trading.pairs.{pair}'):
        set_setting(f'trading.pairs.{pair}', {
            'enabled': False,
            'strategy': 'usdt',
            'alert_enabled': True,
            'threshold_start': 1.0,
            'threshold_stop': 0.5,
        })

def remove_pair(pair: str):
    """Remove a trading pair"""
    config = load_config()
    if 'trading' in config and 'pairs' in config['trading'] and pair in config['trading']['pairs']:
        del config['trading']['pairs'][pair]
        save_config(config)

# ========================================================================
# LOG LEVEL SETTINGS
# ========================================================================
# Level 1 (BASIC): Trade Events, Config Changes, Errors, Bot Start/Stop, Status Changes
# Level 2 (DEBUG): Everything + API Requests, Orderbook Details, Price Details

def get_log_level() -> int:
    """Get current log level (1=Basic, 2=Debug)"""
    return get_setting('system.log_level', 1)

def set_log_level(level: int):
    """Set log level (1=Basic, 2=Debug)"""
    set_setting('system.log_level', level)

def is_debug_enabled() -> bool:
    """Check if debug logging is enabled - reads fresh from config each time"""
    return get_log_level() >= 2

def get_all_settings() -> Dict[str, Any]:
    """Get all settings as a flat dict"""
    return load_config()