#!/usr/bin/env bash
# Watchdog: auto-restart vwap-bot engine if it dies.
# Add this to cron: */5 * * * * /root/trading-bot/vwap-bot/vwap-watchdog.sh >> /root/trading-bot/vwap-bot/logs/watchdog.log 2>&1
set -e
cd /root/trading-bot/vwap-bot
mkdir -p logs
LOG=logs/watchdog.log
echo "[$(date -Iseconds)] watchdog tick" >> $LOG

# 1) Restart engine if not already running
if ! pgrep -f "engine_multi.py --loop" >/dev/null 2>&1; then
    echo "[$(date -Iseconds)] engine not running, starting..." >> $LOG
    nohup /usr/bin/python3 /root/trading-bot/vwap-bot/src/engine_multi.py --loop --loop-seconds 60 \
        >> /root/trading-bot/vwap-bot/logs/vwap_bot.log 2>&1 &
    disown
    echo "[$(date -Iseconds)] started PID $!" >> $LOG
else
    echo "[$(date -Iseconds)] engine alive PID $(pgrep -f 'engine_multi.py --loop' | head -1)" >> $LOG
fi
