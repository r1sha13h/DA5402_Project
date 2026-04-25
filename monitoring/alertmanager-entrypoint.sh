#!/bin/sh
# Render the alertmanager config template, substituting $ALERTMANAGER_SMTP_PASSWORD
# from the container environment, then exec alertmanager so it owns PID 1.
set -e
sed "s|\${ALERTMANAGER_SMTP_PASSWORD}|${ALERTMANAGER_SMTP_PASSWORD}|g" \
  /etc/alertmanager/alertmanager.yml.tmpl > /tmp/alertmanager.yml
exec /bin/alertmanager \
  --config.file=/tmp/alertmanager.yml \
  --storage.path=/alertmanager
