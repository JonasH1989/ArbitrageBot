#!/bin/bash
# Live log fetcher for arbitrage bot - writes ALL logs continuously
# Appends new entries as they appear on the server

LOG_FILE="/home/openclaw/.openclaw/logs/arb_live_log.txt"
ENDPOINT="http://192.168.113.14:18888/logs/today"
LAST_TIMESTAMP_FILE="/home/openclaw/.openclaw/logs/arb_last_ts.txt"

# Get last timestamp we have
LAST_TS=$(cat "$LAST_TIMESTAMP_FILE" 2>/dev/null || echo "0")

echo "=== Live Log Fetcher gestartet $(date) ===" >> "$LOG_FILE"

while true; do
    # Fetch all logs
    RESPONSE=$(curl -s "$ENDPOINT" 2>/dev/null)
    
    if [ $? -eq 0 ] && [ -n "$RESPONSE" ]; then
        # Extract logs newer than LAST_TS and write them
        echo "$RESPONSE" | python3 -c "
import sys,json
last_ts = '$LAST_TS'
data = json.load(sys.stdin)
new_count = 0
for l in data:
    ts = l['timestamp']
    if ts > last_ts:
        print(f'[{ts[11:19]}] [{l[\"level\"]:8}] {l[\"message\"]}')
        new_count += 1
        global last_ts
        if ts > last_ts:
            last_ts = ts
# Write last timestamp for next run
if new_count > 0:
    with open('/home/openclaw/.openclaw/logs/arb_last_ts.txt', 'w') as f:
        f.write(last_ts)
" >> "$LOG_FILE"
    fi
    
    sleep 15  # Check every 15 seconds
done