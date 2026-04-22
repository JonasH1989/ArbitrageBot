#!/usr/bin/env python3
"""
Dashboard Monitor - watches for errors and auto-fixes
"""
import subprocess
import time
import sys
import re

LOG_FILE = '/home/openclaw/.openclaw/logs/arb_autotrade.log'
DASHBOARD_LOG = '/tmp/arb_dashboard_errors.log'

def check_dashboard():
    """Check if dashboard is running and error-free"""
    try:
        # Check container
        result = subprocess.run(['docker', 'ps', '--filter', 'name=arb-dashboard', '--format', '{{.Names}}'], 
                              capture_output=True, text=True, timeout=5)
        if 'arb-dashboard' not in result.stdout:
            print(f"[{time.strftime('%H:%M:%S')}] Dashboard not running - restarting...")
            restart_dashboard()
            return
        
        # Get container logs
        result = subprocess.run(['docker', 'logs', '--tail', '20', 'arb-dashboard'], 
                              capture_output=True, text=True, timeout=5)
        logs = result.stdout + result.stderr
        
        # Check for errors
        error_patterns = [
            r'IndentationError',
            r'SyntaxError',
            r'Traceback.*dashboard\.py',
            r'Script execution error',
        ]
        
        for pattern in error_patterns:
            if re.search(pattern, logs):
                print(f"[{time.strftime('%H:%M:%S')}] ERROR DETECTED: {pattern}")
                # Extract error
                for line in logs.split('\n'):
                    if 'dashboard.py' in line or 'Error' in line:
                        print(f"  -> {line.strip()}")
                
                # Try to fix
                fix_dashboard_errors()
                return
        
        # Check page loads with playwright
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto('http://localhost:8501/', timeout=10000)
                page.wait_for_timeout(2000)
                content = page.inner_text('body')[:200]
                
                # Check for error messages in page
                if 'Script execution error' in content or 'Traceback' in content:
                    print(f"[{time.strftime('%H:%M:%S')}] Page shows error content")
                    fix_dashboard_errors()
                
                browser.close()
        except Exception as e:
            print(f"Playwright check failed: {e}")
        
    except Exception as e:
        print(f"Monitor error: {e}")

def restart_dashboard():
    """Restart the dashboard container"""
    try:
        subprocess.run(['docker', 'stop', 'arb-dashboard'], capture_output=True, timeout=10)
        subprocess.run(['docker', 'rm', 'arb-dashboard'], capture_output=True, timeout=10)
        subprocess.run(['docker', 'run', '-d', '--name', 'arb-dashboard', '-p', '8501:8501', 'arbitrage-dashboard:latest'], 
                      capture_output=True, timeout=30)
        print(f"[{time.strftime('%H:%M:%S')}] Dashboard restarted")
    except Exception as e:
        print(f"Restart failed: {e}")

def fix_dashboard_errors():
    """Attempt to fix common dashboard errors"""
    try:
        # Check for syntax errors in the mounted file
        result = subprocess.run(['python3', '-m', 'py_compile', 
                              '/home/openclaw/.openclaw/workspace/trading/arbitrage-bot/dashboard.py'],
                              capture_output=True, text=True)
        
        if result.returncode != 0:
            error = result.stderr
            print(f"Syntax error in dashboard.py: {error[:200]}")
            
            # Try to restore from git
            try:
                subprocess.run(['git', 'checkout', '--', 'dashboard.py'], 
                             cwd='/home/openclaw/.openclaw/workspace/trading/arbitrage-bot',
                             capture_output=True, timeout=10)
                
                # Rebuild and restart
                subprocess.run(['docker', 'build', '-f', 'Dockerfile.dashboard', '-t', 'arbitrage-dashboard:latest', '.'],
                             cwd='/home/openclaw/.openclaw/workspace/trading/arbitrage-bot',
                             capture_output=True, timeout=120)
                
                restart_dashboard()
                print(f"[{time.strftime('%H:%M:%S')}] Dashboard restored from git")
            except Exception as e:
                print(f"Restore failed: {e}")
    except Exception as e:
        print(f"Fix attempt failed: {e}")

def main():
    print(f"Starting Dashboard Monitor... (checking every 10 seconds)")
    while True:
        check_dashboard()
        time.sleep(10)

if __name__ == '__main__':
    main()