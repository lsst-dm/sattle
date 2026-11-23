#!/bin/bash
# Refresh the TLE catalog by calling the sattle HTTP endpoint.
# Called by cron; output goes to the sattle log directory.

LOGFILE="/app/sattle/python/lsst/sattle/logs/tle_cron.log"
TIMESTAMP=$(date -u '+%Y-%m-%dT%H:%M:%S')

echo "${TIMESTAMP} Starting TLE refresh via cron" >> "${LOGFILE}"

RESPONSE=$(curl -sf -X POST \
    --max-time 300 \
    --retry 2 \
    --retry-delay 60 \
    http://localhost:9999/refresh_tles 2>&1)

EXIT_CODE=$?

if [ ${EXIT_CODE} -eq 0 ]; then
    echo "${TIMESTAMP} TLE refresh succeeded: ${RESPONSE}" >> "${LOGFILE}"
else
    echo "${TIMESTAMP} TLE refresh FAILED (exit ${EXIT_CODE}): ${RESPONSE}" >> "${LOGFILE}"
fi
