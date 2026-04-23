#!/bin/bash
# Start script for arbitrage bot
# Creates log directory and flag file if needed

mkdir -p /app/logs

# Check if we should start active or inactive
if [ -f "/app/logs/arb_active.flag" ]; then
    echo "Flag file exists - starting ACTIVE"
else
    echo "No flag file - starting INAKTIV"
fi

exec python arb_autotrade.py
