#!/usr/bin/env bash
# Close the published demo window (ADR-012): api, ui, and worker to desired
# count 0. The stack itself (RDS, ALB, EFS) keeps billing until
# `terraform destroy`; see infra/README.md.
#
#   CCI_CLUSTER=cci-prod CCI_REGION=ap-south-1 scripts/demo-down.sh
set -euo pipefail

CLUSTER="${CCI_CLUSTER:-cci-prod}"
REGION="${CCI_REGION:-ap-south-1}"

for service in api ui worker; do
  echo "scaling ${CLUSTER}-${service} to 0"
  aws ecs update-service \
    --region "$REGION" \
    --cluster "$CLUSTER" \
    --service "${CLUSTER}-${service}" \
    --desired-count 0 \
    --output text >/dev/null
done

echo "scaled to zero. Bring it back with scripts/demo-up.sh."
