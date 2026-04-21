#!/usr/bin/env python3
"""Check for arbitrage opportunities and alert if found"""
import sys
import os
import json
from datetime import datetime

# Check if opportunity file exists
opp_file = '/tmp/arb_opportunity.json'
last_check_file = '/tmp/arb_last_alert.txt'

if os.path.exists(opp_file):
    with open(opp_file, 'r') as f:
        data = json.load(f)
    
    opp = data['opportunity']
    timestamp = data['timestamp']
    
    # Check if we already alerted recently (within 5 minutes)
    should_alert = True
    if os.path.exists(last_check_file):
        with open(last_check_file, 'r') as f:
            last_alert = f.read().strip()
            if last_alert == timestamp:
                should_alert = False
    
    if should_alert:
        print(f"ALERT: Arbitrage opportunity at {timestamp}!")
        print(f"Direction: {opp['direction']}")
        print(f"Spread: {opp['spread_pct']:.2f}%")
        print(f"Profit: ${opp['profit_usdt']:.4f}")
        
        # Save alert timestamp
        with open(last_check_file, 'w') as f:
            f.write(timestamp)
        
        # Exit with error code to trigger alert
        sys.exit(1)
    else:
        print("No new opportunity (already alerted)")
        sys.exit(0)
else:
    print("No opportunity found")
    sys.exit(0)
