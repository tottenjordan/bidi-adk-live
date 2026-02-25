#!/usr/bin/env bash
# Creates the BigQuery dataset and table for appliance inventory.
# Requires: gcloud auth, GOOGLE_CLOUD_PROJECT set or passed as $1.
#
# Usage: ./scripts/create_bq_table.sh [project-id]

set -euo pipefail

PROJECT="${1:-hybrid-vertex}"
DATASET="appliances_v2"
TABLE="inventory"
LOCATION="us-central1"

echo "Creating dataset ${PROJECT}.${DATASET} ..."
bq --project_id="${PROJECT}" mk \
  --dataset \
  --location="${LOCATION}" \
  --description="Home appliance inventory (v2)" \
  "${DATASET}" 2>/dev/null || echo "Dataset already exists."

echo "Creating table ${PROJECT}.${DATASET}.${TABLE} ..."
bq --project_id="${PROJECT}" mk \
  --table \
  --description="Logged home appliances" \
  "${DATASET}.${TABLE}" \
  appliance_type:STRING,make:STRING,model:STRING,location:STRING,finish:STRING,notes:STRING,user_id:STRING,timestamp:TIMESTAMP \
  2>/dev/null || echo "Table already exists."

echo "Done. Table: ${PROJECT}.${DATASET}.${TABLE}"
bq --project_id="${PROJECT}" show --schema --format=prettyjson "${DATASET}.${TABLE}"
