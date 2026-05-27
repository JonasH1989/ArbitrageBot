#!/bin/bash
# Post-Deploy Script for Coolify
# Creates a flag file that tells the bot it was just redeployed
# Bot will check for this file on startup and disable itself until user enables via dashboard

FLAG_FILE="/app/logs/.just_redeployed.flag"

# Create flag file
touch "$FLAG_FILE"
echo "$(date): Bot redeployed" >> "$FLAG_FILE"

echo "[POST-DEPLOY] Redeploy flag created: $FLAG_FILE"
