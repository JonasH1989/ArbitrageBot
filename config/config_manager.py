"""
Configuration Manager for MPC Arbitrage Bot
Handles config loading, saving, and authentication with 2FA
"""

import os
import yaml
import hashlib
from passlib.hash import pbkdf2_sha256 as ph
import pyotp
import secrets
from pathlib import Path
from typing import Optional, Dict, Any
from loguru import logger


class ConfigManager:
    """Manages configuration and authentication"""
    
    def __init__(self, config_path: str = None):
        if config_path is None:
            config_path = Path(__file__).parent / "config.yaml"
        self.config_path = Path(config_path)
        self._config: Dict[str, Any] = {}
        self._load()
    
    def _load(self):
        """Load configuration from YAML file"""
        if self.config_path.exists():
            with open(self.config_path, 'r') as f:
                self._config = yaml.safe_load(f) or {}
        else:
            self._config = self._get_default_config()
            self._save()
    
    def _get_default_config(self) -> Dict[str, Any]:
        """Get default configuration"""
        return {
            'app': {
                'name': 'MPC Arbitrage Bot',
                'version': '1.0.0',
                'debug': False
            },
            'auth': {
                'admin_username': None,
                'admin_password_hash': None,
                'admin_2fa_secret': None,
                'registration_locked': False
            },
            'trading': {
                'pair': 'MPC-USDT',
                'exchanges': ['kucoin', 'mexc'],
                'thresholds': {
                    'start': 2.0,
                    'stop': 1.0
                },
                'mode': 'coin_multiplication',
                'max_order_size_mpc': 10000,
                'min_order_size_mpc': 100,
                'execution_mode': 'test'
            },
            'kucoin': {
                'api_key': '',
                'api_secret': '',
                'api_passphrase': '',
                'sandbox': False
            },
            'mexc': {
                'api_key': '',
                'api_secret': ''
            },
            'dashboard': {
                'port': 8501,
                'host': '0.0.0.0'
            },
            'logging': {
                'level': 'INFO',
                'file': 'logs/arbitrage.log',
                'rotation': '100 MB',
                'retention': '30 days'
            }
        }
    
    def _save(self):
        """Save configuration to YAML file"""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, 'w') as f:
            yaml.dump(self._config, f, default_flow_style=False)
    
    def get(self, key: str, default=None):
        """Get config value using dot notation (e.g., 'auth.admin_username')"""
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
        """Set config value using dot notation"""
        keys = key.split('.')
        config = self._config
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
        config[keys[-1]] = value
        self._save()
    
    @property
    def is_registered(self) -> bool:
        """Check if admin is registered"""
        return (
            self.get('auth.admin_username') is not None and
            self.get('auth.admin_password_hash') is not None and
            self.get('auth.admin_2fa_secret') is not None
        )
    
    @property
    def is_registration_locked(self) -> bool:
        """Check if registration is locked"""
        return self.get('auth.registration_locked', False)
    
    def register_admin(self, username: str, password: str) -> Dict[str, Any]:
        """
        Register admin user with 2FA
        Returns: {success: bool, message: str, backup_codes: list}
        """
        if self.is_registered and self.is_registration_locked:
            return {
                'success': False,
                'message': 'Registration is locked. Only admin can login.'
            }
        
        # Validate password strength
        if len(password) < 8:
            return {
                'success': False,
                'message': 'Password must be at least 8 characters'
            }
        
        # Generate 2FA secret
        totp_secret = pyotp.random_base32()
        
        # Generate backup codes
        backup_codes = [secrets.token_hex(8) for _ in range(10)]
        
        # Hash password using pbkdf2
        password_hash = ph.hash(password)
        
        # Save config
        self.set('auth.admin_username', username)
        self.set('auth.admin_password_hash', password_hash)
        self.set('auth.admin_2fa_secret', totp_secret)
        self.set('auth.backup_codes', [ph.hash(code) for code in backup_codes])
        self.set('auth.registration_locked', True)
        
        logger.info(f"Admin user '{username}' registered successfully")
        
        return {
            'success': True,
            'message': 'Admin registered successfully',
            'totp_secret': totp_secret,
            'backup_codes': backup_codes,
            'qr_uri': pyotp.totp.TOTP(totp_secret).provisioning_uri(
                name=username,
                issuer_name='MPC-Arbitrage-Bot'
            )
        }
    
    def verify_password(self, password: str) -> bool:
        """Verify admin password"""
        stored_hash = self.get('auth.admin_password_hash')
        if not stored_hash:
            return False
        try:
            return ph.verify(stored_hash, password)
        except:
            return False
    
    def verify_2fa(self, token: str) -> bool:
        """Verify 2FA token"""
        secret = self.get('auth.admin_2fa_secret')
        if not secret:
            return False
        totp = pyotp.TOTP(secret)
        return totp.verify(token, valid_window=1)
    
    def verify_backup_code(self, code: str) -> bool:
        """Verify backup code and invalidate it"""
        backup_codes = self.get('auth.backup_codes', [])
        for i, stored_hash in enumerate(backup_codes):
            if ph.verify(stored_hash, code):
                # Invalidate used backup code
                backup_codes.pop(i)
                self.set('auth.backup_codes', backup_codes)
                logger.info("Backup code used and invalidated")
                return True
        return False
    
    def authenticate(self, username: str, password: str, token: str = None) -> Dict[str, Any]:
        """
        Authenticate admin user
        Returns: {success: bool, message: str}
        """
        # Check username
        if username != self.get('auth.admin_username'):
            return {'success': False, 'message': 'Invalid credentials'}
        
        # Check password
        if not self.verify_password(password):
            return {'success': False, 'message': 'Invalid credentials'}
        
        # Check 2FA
        if not self.verify_2fa(token):
            return {'success': False, 'message': 'Invalid 2FA token'}
        
        logger.info(f"Admin '{username}' logged in successfully")
        return {'success': True, 'message': 'Login successful'}
    
    def get_thresholds(self) -> Dict[str, float]:
        """Get current threshold settings"""
        return {
            'start': self.get('trading.thresholds.start', 2.0),
            'stop': self.get('trading.thresholds.stop', 1.0)
        }
    
    def set_thresholds(self, start: float, stop: float) -> Dict[str, Any]:
        """Set threshold values (0-50%)"""
        # Validate
        if not (0 <= start <= 50):
            return {'success': False, 'message': 'Start threshold must be 0-50%'}
        if not (0 <= stop <= 50):
            return {'success': False, 'message': 'Stop threshold must be 0-50%'}
        if start < stop:
            return {'success': False, 'message': 'Start threshold must be >= stop threshold'}
        
        self.set('trading.thresholds.start', start)
        self.set('trading.thresholds.stop', stop)
        
        logger.info(f"Thresholds updated: start={start}%, stop={stop}%")
        return {'success': True, 'message': 'Thresholds updated'}
    
    def set_api_keys(self, exchange: str, api_key: str, api_secret: str, api_passphrase: str = None):
        """Set API keys for exchange"""
        if exchange == 'kucoin':
            self.set('kucoin.api_key', api_key)
            self.set('kucoin.api_secret', api_secret)
            if api_passphrase:
                self.set('kucoin.api_passphrase', api_passphrase)
        elif exchange == 'mexc':
            self.set('mexc.api_key', api_key)
            self.set('mexc.api_secret', api_secret)
    
    def get_execution_mode(self) -> str:
        """Get trading execution mode"""
        return self.get('trading.execution_mode', 'test')
    
    def set_execution_mode(self, mode: str):
        """Set trading execution mode (test or live)"""
        if mode not in ['test', 'live']:
            raise ValueError("Mode must be 'test' or 'live'")
        self.set('trading.execution_mode', mode)
        logger.info(f"Execution mode set to: {mode}")


# Global instance
_config: Optional[ConfigManager] = None

def get_config(config_path: str = None) -> ConfigManager:
    """Get global config manager instance"""
    global _config
    if _config is None:
        _config = ConfigManager(config_path)
    return _config
