#!/usr/bin/env bash
#
# Deploy the chinese-convo-live Cloud Functions (gen2, Python 3.12).
#
# The functions derive their GCP project from Application Default Credentials
# (the deploy project) — nothing is hardcoded — so this script only needs to
# know the project + region.
#
# Usage:
#   PROJECT_ID=your-gcp-project REGION=us-east4 ./scripts/deploy_functions.sh
#   PROJECT_ID=your-gcp-project ./scripts/deploy_functions.sh generate_question   # one function
#
# Prereqs: gcloud authenticated; run scripts/setup_infra.sh once first.
set -euo pipefail

PROJECT_ID="${PROJECT_ID:?set PROJECT_ID=your-gcp-project}"
REGION="${REGION:-us-east4}"
RUNTIME="python312"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# name | entry-point | source-subdir | memory | timeout | auth(public|private)
# Note: evaluate_answer and update_review_time share one source dir (two handlers).
FUNCTIONS=(
  "convo_live_generate_question|convo_live_generate_question|convo_live_generate_question|512Mi|120|public"
  "convo_live_evaluate_answer|evaluate_answer|convo_live_evaluate_answer|512Mi|120|public"
  "convo_live_update_review_time|update_review_time|convo_live_evaluate_answer|256Mi|60|public"
  "convo_live_generate_audio|convo_live_generate_audio|convo_live_generate_audio|512Mi|60|public"
  "convo_live_translate|convo_live_translate|convo_live_translate|256Mi|60|public"
  "convo_live_mark_word_mastered|mark_word_mastered|convo_live_mark_word_mastered|256Mi|60|public"
  "convo_live_ingest_google|convo_live_ingest_google|convo_live_ingest_google|512Mi|600|private"
)

FILTER="${1:-}"

for spec in "${FUNCTIONS[@]}"; do
  IFS='|' read -r name entry subdir mem timeout auth <<< "$spec"
  if [[ -n "$FILTER" && "$name" != *"$FILTER"* ]]; then continue; fi

  auth_flag="--allow-unauthenticated"
  [[ "$auth" == "private" ]] && auth_flag="--no-allow-unauthenticated"

  echo "==> deploying $name ($entry, $mem/${timeout}s, $auth)"
  gcloud functions deploy "$name" \
    --gen2 --project "$PROJECT_ID" --region "$REGION" \
    --runtime "$RUNTIME" --entry-point "$entry" \
    --source "$ROOT/functions/$subdir" \
    --trigger-http "$auth_flag" \
    --memory "$mem" --timeout "$timeout"
done

echo "Done. Function base URL: https://${REGION}-${PROJECT_ID}.cloudfunctions.net"
