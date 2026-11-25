#!/bin/bash
set -e

# Pass critical env vars to cron jobs (cron starts with a minimal env)
printenv | grep -E '^(PATH|PYTHONPATH|SPACETRACK_|SATTLE_|TZ)' > /etc/environment
echo "TZ=America/Santiago" >> /etc/environment

# Install the crontab
crontab /etc/cron.d/tle-refresh

# Start cron daemon in the background
cron

# Hand off to the application as PID 1
exec python app.py
