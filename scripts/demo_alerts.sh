#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# demo_alerts.sh — Fire 5 of the 11 production alerts and verify each is
#                  routed to email by Alertmanager.
#
# Alerts demonstrated (all at production thresholds, no rule modifications):
#   1. IngestFailed         — Pushgateway POST: pipeline_ingest_success=0
#   2. LowTestF1            — Pushgateway POST: test_f1_macro=0.50
#   3. ModelNotLoaded       — docker compose stop backend (>60s)
#   4. HighErrorRate        — burst 120 malformed /predict requests
#   5. DataDriftDetected    — trigger Airflow DAG (drift CSV is present)
#
# Prereqs: full stack running locally (docker compose up).
#          GMail SMTP password injected into Alertmanager via .env.
# Usage:   bash scripts/demo_alerts.sh
# ─────────────────────────────────────────────────────────────────────────────

set -u

PUSHGW=http://localhost:9091
PROM=http://localhost:9090
AM=http://localhost:9093
BACKEND=http://localhost:8000
AIRFLOW=http://localhost:8080
AUTH_HDR="Authorization: Basic $(echo -n admin:admin | base64)"

# ── helpers ──────────────────────────────────────────────────────────────────
hr() { printf '\n\033[1;34m%s\033[0m\n' "──── $* ────"; }
ok() { printf '  \033[1;32m✓\033[0m %s\n' "$*"; }
info() { printf '  • %s\n' "$*"; }

email_count() {
  curl -s "$AM/metrics" 2>/dev/null \
    | awk -F'[ {}]' '/^alertmanager_notifications_total{integration="email"}/ {print $NF; exit}'
}

is_firing() {
  local name=$1
  curl -s "$PROM/api/v1/alerts" \
    | A="$name" python3 -c "import json,sys,os; print(any(a['labels']['alertname']==os.environ['A'] and a['state']=='firing' for a in json.load(sys.stdin)['data']['alerts']))"
}

wait_until_firing() {
  local name=$1 budget=${2:-180}
  for ((i=0; i<budget; i+=5)); do
    if [[ "$(is_firing "$name")" == "True" ]]; then
      ok "$name → firing (after ${i}s)"
      return 0
    fi
    sleep 5
  done
  printf '  \033[1;33m⚠\033[0m  %s did not reach firing within %ss\n' "$name" "$budget"
  return 1
}

# ── baseline ─────────────────────────────────────────────────────────────────
hr "Baseline"
EMAIL_BEFORE=$(email_count)
info "Email notifications before demo: $EMAIL_BEFORE"
info "Currently-firing alerts: $(curl -s "$PROM/api/v1/alerts" | python3 -c "import json,sys; print(len([a for a in json.load(sys.stdin)['data']['alerts'] if a['state']=='firing']))")"

# ── 1. IngestFailed ──────────────────────────────────────────────────────────
hr "1/5  IngestFailed (instant)"
info "Pushing pipeline_ingest_success=0 to Pushgateway"
echo "spendsense_pipeline_ingest_success 0" \
  | curl -s --data-binary @- "$PUSHGW/metrics/job/spendsense_demo_ingest" >/dev/null
wait_until_firing IngestFailed 60

# ── 2. LowTestF1 ─────────────────────────────────────────────────────────────
hr "2/5  LowTestF1 (instant)"
info "Pushing test_f1_macro=0.50 to Pushgateway"
echo "spendsense_test_f1_macro 0.50" \
  | curl -s --data-binary @- "$PUSHGW/metrics/job/spendsense_demo_eval" >/dev/null
wait_until_firing LowTestF1 60

# ── 3. ModelNotLoaded ────────────────────────────────────────────────────────
hr "3/5  ModelNotLoaded (for: 1m)"
info "Stopping backend container (alert must observe down state for ≥60s)"
docker compose stop backend >/dev/null 2>&1
wait_until_firing ModelNotLoaded 120
info "Bringing backend back up so it's ready for HighErrorRate next"
docker compose start backend >/dev/null 2>&1
for i in $(seq 1 30); do
  S=$(curl -s -o /dev/null -w "%{http_code}" "$BACKEND/ready" 2>/dev/null) || S=000
  [[ "$S" == "200" ]] && ok "Backend ready" && break
  sleep 2
done

# ── 4. HighErrorRate ─────────────────────────────────────────────────────────
hr "4/5  HighErrorRate (>5% over rolling 100 reqs, for: 2m)"
info "Sending 120 malformed POST /predict requests"
for i in $(seq 1 120); do
  curl -s -o /dev/null -X POST "$BACKEND/predict" \
    -H "Content-Type: application/json" -d '{}' &
  (( i % 30 == 0 )) && wait
done
wait
info "Burst sent. Waiting up to 3 min for the 2-minute 'for' clause to elapse"
wait_until_firing HighErrorRate 200

# ── 5. DataDriftDetected ─────────────────────────────────────────────────────
hr "5/5  DataDriftDetected (Airflow DAG)"
RUN_ID="demo_$(date +%s)"
info "Triggering DAG via REST API (run_id=$RUN_ID)"
curl -s -o /dev/null -w "  POST status: %{http_code}\n" -X POST \
  -H "Content-Type: application/json" -H "$AUTH_HDR" \
  -d "{\"dag_run_id\":\"$RUN_ID\"}" \
  "$AIRFLOW/api/v1/dags/spendsense_ingestion_pipeline/dagRuns"
info "DAG runs ~50s of work + 75s sleep in pipeline_complete (so alert fires once then resolves)"
wait_until_firing DataDriftDetected 240

# ── summary ──────────────────────────────────────────────────────────────────
hr "Summary"
sleep 30  # give Alertmanager group_wait + last batches time to dispatch
EMAIL_AFTER=$(email_count)
DELTA=$(python3 -c "print(int(float('$EMAIL_AFTER') - float('$EMAIL_BEFORE')))")
info "Email notifications after demo: $EMAIL_AFTER  (delta: $DELTA)"
info "Currently-firing alerts:"
curl -s "$PROM/api/v1/alerts" \
  | python3 -c "
import json, sys
for a in json.load(sys.stdin)['data']['alerts']:
    if a['state'] == 'firing':
        print(f\"      {a['labels']['alertname']:25s} sev={a['labels'].get('severity','-')}\")"

cat <<EOF

Cleanup commands (run when you're done with the demo):
  curl -X DELETE $PUSHGW/metrics/job/spendsense_demo_ingest
  curl -X DELETE $PUSHGW/metrics/job/spendsense_demo_eval
  # ModelNotLoaded resolves once /ready returns 200 (already restarted above)
  # HighErrorRate resolves after ≥100 successful requests roll the window clean
  # DataDriftDetected already auto-resolved via pipeline_complete sleep+reset
EOF
