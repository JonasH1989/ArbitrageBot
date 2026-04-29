#!/usr/bin/env python3
import requests
import time
from datetime import datetime

ENDPOINT = "http://192.168.113.14:18888/logs/today"
LOG_FILE = "/home/openclaw/.openclaw/logs/arb_live_log.txt"
LAST_TS_FILE = "/home/openclaw/.openclaw/logs/arb_last_ts.txt"

def get_last_ts():
    try:
        with open(LAST_TS_FILE, 'r') as f:
            return f.read().strip()
    except:
        return "0"

def save_last_ts(ts):
    with open(LAST_TS_FILE, 'w') as f:
        f.write(ts)

print(f"Live Log Fetcher started at {datetime.now()}")

while True:
    try:
        resp = requests.get(ENDPOINT, timeout=5)
        data = resp.json()
        last_ts = get_last_ts()
        new_entries = []
        
        for entry in data:
            ts = entry['timestamp']
            if ts > last_ts:
                new_entries.append(f'[{ts[11:19]}] [{entry["level"]:8}] {entry["message"]}')
                if ts > last_ts:
                    last_ts = ts
        
        if new_entries:
            with open(LOG_FILE, 'a') as f:
                f.write('\n'.join(new_entries) + '\n')
            save_last_ts(last_ts)
            print(f"{datetime.now().strftime('%H:%M:%S')} - Wrote {len(new_entries)} new entries")
        
    except Exception as e:
        print(f"Error: {e}")
    
    time.sleep(15)