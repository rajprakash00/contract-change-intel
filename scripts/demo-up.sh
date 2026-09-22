#!/usr/bin/env bash
# Bring the published demo to a working state (ADR-012): api, ui, and worker
# at desired count 1, then print the URL and demo credentials.
#
# Override for a different stack:
#   CCI_CLUSTER=cci-prod CCI_REGION=ap-south-1 CCI_URL=https://... scripts/demo-up.sh
set -euo pipefail

CLUSTER="${CCI_CLUSTER:-cci-prod}"
REGION="${CCI_REGION:-ap-south-1}"
URL="${CCI_URL:-https://change-report.byraj.dev}"

for service in api ui worker; do
  echo "scaling ${CLUSTER}-${service} to 1"
  aws ecs update-service \
    --region "$REGION" \
    --cluster "$CLUSTER" \
    --service "${CLUSTER}-${service}" \
    --desired-count 1 \
    --output text >/dev/null
done

echo "waiting for services to reach steady state (can take a few minutes)"
aws ecs wait services-stable \
  --region "$REGION" \
  --cluster "$CLUSTER" \
  --services "${CLUSTER}-api" "${CLUSTER}-ui" "${CLUSTER}-worker"

cat <<EOF
Demo is up: ${URL}

  admin    demo-admin@byraj.dev    / 78KeoOwmxw0HrY4fsLITpkR
  reviewer demo-reviewer@byraj.dev / 47EO4c9K13BTq8O5K4tY3W

"Try the demo" on the landing page prefills the admin email; paste the
password on the Auth0 screen. Scale down with scripts/demo-down.sh.
EOF
