#!/bin/bash
set -euo pipefail

# Write crontab entries from config.json so schedule changes only need a restart.
PIPELINE_CRON=$(python3 -c "
import json, sys
try:
    c = json.load(open('/app/config.json'))
    val = c['schedule']['pipeline_cron']
    if not val or not val.strip():
        raise ValueError('pipeline_cron is empty')
    print(val.strip())
except Exception as e:
    print('ERROR: ' + str(e), file=sys.stderr)
    sys.exit(1)
")

if [ -z "$PIPELINE_CRON" ]; then
    echo "FATAL: PIPELINE_CRON is empty — check config.json schedule.pipeline_cron" >&2
    exit 1
fi

cat > /etc/cron.d/havi <<EOF
PATH=/usr/local/bin:/usr/bin:/bin
${PIPELINE_CRON} havi cd /app && python havi.py -a >> /var/log/havi/pipeline.log 2>&1

EOF

chmod 0644 /etc/cron.d/havi
mkdir -p /var/log/havi
touch /var/log/havi/pipeline.log
chown -R havi:havi /var/log/havi /app/Downloads /app/Extracted

# Keep local cron logs bounded when bind-mounted logs are used.
find /var/log/havi -name "*.log" -size +50M -exec truncate -s 0 {} \;

exec "$@"
