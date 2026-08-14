#!/usr/bin/env bash
#
# Deploy the speech-to-text service (SenseVoice via sherpa-onnx) to Cloud Run.
#
# This one is NOT a Cloud Function: it needs the ffmpeg binary and bakes a 237 MB model into the image,
# so it ships as a container (deploy_functions.sh handles the buildpack-based functions).
#
# Usage:
#   PROJECT_ID=your-gcp-project REGION=us-east4 ./scripts/deploy_transcribe.sh
set -euo pipefail

PROJECT_ID="${PROJECT_ID:?set PROJECT_ID=your-gcp-project}"
REGION="${REGION:-us-east4}"
SERVICE="${SERVICE:-convo-live-transcribe}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# min-instances=1: the model load costs ~1.6s, so keep one instance warm rather than paying it per cold
# start. 2 vCPU because decode speed scales with CPU (RTF 0.083 measured on 8 vCPU) — if a 5s utterance
# takes more than ~1.5s end to end, raise --cpu and re-measure.
# --clear-base-image: required when the source contains a Dockerfile (no managed base image).
gcloud run deploy "$SERVICE" \
  --project "$PROJECT_ID" --region "$REGION" \
  --source "$ROOT/functions/convo_live_transcribe" \
  --memory 2Gi --cpu 2 --min-instances 1 --max-instances 4 --timeout 120 \
  --clear-base-image \
  --allow-unauthenticated

echo
echo "URL: $(gcloud run services describe "$SERVICE" --project "$PROJECT_ID" --region "$REGION" \
          --format='value(status.url)')"
echo "Put that in frontend/src/services/firebase.config.ts -> appConfig.transcribeUrl"
