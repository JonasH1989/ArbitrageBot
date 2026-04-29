#!/bin/bash
# Analyze arb_live_log.txt and report significant events
LOG_FILE="/home/openclaw/.openclaw/logs/arb_live_log.txt"
REPORT_FILE="/home/openclaw/.openclaw/logs/arb_report_15min.txt"

echo "=== Arb Bot Report $(date '+%Y-%m-%d %H:%M') ===" > "$REPORT_FILE"
echo "" >> "$REPORT_FILE"

# Check last lines for activity
LAST_TRADES=$(grep -c "EXECUTING TRADE" "$LOG_FILE" 2>/dev/null || echo 0)
LAST_ERRORS=$(grep -c "ERROR" "$LOG_FILE" 2>/dev/null || echo 0)
LAST_BALANCE_ISSUES=$(grep -c "BALANCE CHECK FAILED" "$LOG_FILE" 2>/dev/null || echo 0)
LAST_SPREADS=$(grep "spread" "$LOG_FILE" 2>/dev/null | tail -1)

echo "Statistik (seit Log-Start):" >> "$REPORT_FILE"
echo "  Trades executed: $LAST_TRADES" >> "$REPORT_FILE"
echo "  Errors: $LAST_ERRORS" >> "$REPORT_FILE"
echo "  Balance issues: $LAST_BALANCE_ISSUES" >> "$REPORT_FILE"
echo "" >> "$REPORT_FILE"

# Last 5 minutes activity
LAST5_MIN=$(date -d "-5 minutes" +"%H:%M" 2>/dev/null || date -v-5m +"%H:%M")
echo "Letzte Aktivität (ab $LAST5_MIN):" >> "$REPORT_FILE"
grep "\[16:[0-4][0-9]\]" "$LOG_FILE" 2>/dev/null | tail -10 >> "$REPORT_FILE" 2>/dev/null || echo "  Keine neue Aktivität" >> "$REPORT_FILE"

echo "" >> "$REPORT_FILE"
echo "Letzter Spread-Check:" >> "$REPORT_FILE"
grep "spread" "$LOG_FILE" 2>/dev/null | tail -3 >> "$REPORT_FILE" 2>/dev/null || echo "  Keine Daten" >> "$REPORT_FILE"

cat "$REPORT_FILE"