#!/usr/bin/env bash
#
# One-time infrastructure setup for chinese-convo-live on Google Cloud.
#
# Reproduces the project's real topology: APIs, IAM, Firestore, Firebase Hosting,
# and (optional) the server-side personalization pipeline (VPC + NAT + Signal VM +
# Secret Manager + Cloud Scheduler). Safe to re-run; steps are idempotent where the
# CLI allows and otherwise tolerate "already exists".
#
# Usage:
#   PROJECT_ID=your-gcp-project OWNER_EMAIL=you@example.com ./scripts/setup_infra.sh
#
# Then, in order:
#   1. Create the OAuth consent screen + Web client ID in the console (see README).
#   2. ./scripts/setup_infra.sh                 # this script (core + personalization)
#   3. firebase use $PROJECT_ID                 # writes .firebaserc (gitignored)
#   4. python local/mint_google_token.py ...    # mints OAuth secrets (personalization)
#   5. ./scripts/deploy_functions.sh            # deploy the Cloud Functions
#   6. (cd frontend && npm i && npm run build) && firebase deploy --only hosting
set -euo pipefail

PROJECT_ID="${PROJECT_ID:?set PROJECT_ID=your-gcp-project}"
OWNER_EMAIL="${OWNER_EMAIL:?set OWNER_EMAIL=you@example.com}"
REGION="${REGION:-us-east4}"
ZONE="${ZONE:-${REGION}-c}"
WITH_PERSONALIZATION="${WITH_PERSONALIZATION:-true}"   # set false to skip VPC/VM/secrets/scheduler

PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
COMPUTE_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
gcloud config set project "$PROJECT_ID" >/dev/null

echo "== [1/8] Enable APIs =="
gcloud services enable --project "$PROJECT_ID" \
  aiplatform.googleapis.com cloudfunctions.googleapis.com run.googleapis.com \
  cloudbuild.googleapis.com artifactregistry.googleapis.com eventarc.googleapis.com \
  firestore.googleapis.com datastore.googleapis.com \
  firebase.googleapis.com firebasehosting.googleapis.com firebaserules.googleapis.com \
  identitytoolkit.googleapis.com securetoken.googleapis.com \
  texttospeech.googleapis.com speech.googleapis.com \
  secretmanager.googleapis.com cloudscheduler.googleapis.com \
  compute.googleapis.com iap.googleapis.com iamcredentials.googleapis.com \
  calendar-json.googleapis.com gmail.googleapis.com drive.googleapis.com

echo "== [2/8] IAM for the runtime/build service account =="
# This org disables auto-grants, so grant explicitly. Functions run as the compute SA:
# it builds (cloudbuild), calls Vertex models — Claude + Grok + TTS (aiplatform), and reads/writes Firestore.
for role in roles/cloudbuild.builds.builder roles/aiplatform.user roles/datastore.user; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${COMPUTE_SA}" --role="$role" --condition=None >/dev/null
done

echo "== [3/8] Firestore (Native) database + indexes + rules =="
gcloud firestore databases create --project "$PROJECT_ID" --location="$REGION" 2>/dev/null \
  || echo "   (database already exists)"
# firestore.rules ships with a placeholder owner email; substitute the real one in place for the
# deploy, then restore the placeholder so the committed file stays generic.
cp firestore.rules firestore.rules.bak
sed -i "s/owner@example.com/${OWNER_EMAIL}/" firestore.rules
firebase deploy --only firestore:indexes,firestore:rules --project "$PROJECT_ID"
mv firestore.rules.bak firestore.rules

echo "== [4/8] Firebase Hosting site =="
firebase hosting:sites:create "wz-chinese-convo-live" --project "$PROJECT_ID" 2>/dev/null \
  || echo "   (hosting site already exists — pick your own unique name and update firebase.json)"

if [[ "$WITH_PERSONALIZATION" != "true" ]]; then
  echo "Core setup done. (WITH_PERSONALIZATION=false — skipped VPC/VM/secrets/scheduler.)"
  exit 0
fi

echo "== [5/8] Custom VPC + Cloud NAT (no default VPC on this org) =="
gcloud compute networks create convo-live-vpc --project "$PROJECT_ID" \
  --subnet-mode=custom 2>/dev/null || echo "   (vpc exists)"
gcloud compute networks subnets create convo-live-subnet --project "$PROJECT_ID" \
  --network=convo-live-vpc --region="$REGION" --range=10.10.0.0/24 2>/dev/null || echo "   (subnet exists)"
gcloud compute routers create convo-live-router --project "$PROJECT_ID" \
  --network=convo-live-vpc --region="$REGION" 2>/dev/null || echo "   (router exists)"
gcloud compute routers nats create convo-live-nat --project "$PROJECT_ID" \
  --router=convo-live-router --region="$REGION" \
  --auto-allocate-nat-external-ips --nat-all-subnet-ip-ranges 2>/dev/null || echo "   (nat exists)"
# Allow IAP TCP forwarding to reach SSH (no public IP on the VM).
gcloud compute firewall-rules create convo-live-allow-iap-ssh --project "$PROJECT_ID" \
  --network=convo-live-vpc --direction=INGRESS --action=ALLOW \
  --rules=tcp:22 --source-ranges=35.235.240.0/20 2>/dev/null || echo "   (firewall exists)"

echo "== [6/8] Signal reader VM service account + IAM =="
gcloud iam service-accounts create convo-live-signal --project "$PROJECT_ID" \
  --display-name="convo-live Signal reader" 2>/dev/null || echo "   (SA exists)"
VM_SA="convo-live-signal@${PROJECT_ID}.iam.gserviceaccount.com"
for role in roles/datastore.user roles/aiplatform.user; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${VM_SA}" --role="$role" --condition=None >/dev/null
done

echo "== [7/8] Shielded Signal VM (private, OS Login, IAP SSH only) =="
gcloud compute instances create convo-live-signal --project "$PROJECT_ID" \
  --zone="$ZONE" --machine-type=e2-small \
  --network=convo-live-vpc --subnet=convo-live-subnet --no-address \
  --service-account="$VM_SA" --scopes=cloud-platform \
  --shielded-secure-boot --shielded-vtpm --shielded-integrity-monitoring \
  --metadata=enable-oslogin=TRUE \
  --metadata-from-file=startup-script=local/signal_vm_startup.sh \
  --image-family=debian-12 --image-project=debian-cloud 2>/dev/null || echo "   (VM exists)"

echo "== [8/8] Secret access + hourly ingestion scheduler =="
# Secrets themselves are created by local/mint_google_token.py (user-managed replication in
# $REGION, because this org's gcp.resourceLocations policy blocks global/automatic). Grant the
# runtime SA read access once they exist.
for s in convo-live-google-oauth-client convo-live-google-oauth-refresh-token; do
  gcloud secrets add-iam-policy-binding "$s" --project "$PROJECT_ID" \
    --member="serviceAccount:${COMPUTE_SA}" --role=roles/secretmanager.secretAccessor 2>/dev/null \
    || echo "   ($s not created yet — run mint_google_token.py, then re-run this step)"
done
# Scheduler invokes the private ingest function with an OIDC token as the compute SA.
gcloud run services add-iam-policy-binding convo-live-ingest-google --project "$PROJECT_ID" \
  --region="$REGION" --member="serviceAccount:${COMPUTE_SA}" --role=roles/run.invoker 2>/dev/null \
  || echo "   (ingest not deployed yet — deploy functions, then re-run this step)"
gcloud scheduler jobs create http convo-live-ingest-hourly --project "$PROJECT_ID" \
  --location="$REGION" --schedule="17 * * * *" \
  --uri="https://${REGION}-${PROJECT_ID}.cloudfunctions.net/convo_live_ingest_google" \
  --http-method=POST --oidc-service-account-email="$COMPUTE_SA" 2>/dev/null \
  || echo "   (scheduler job exists)"

echo "Infra setup complete for $PROJECT_ID ($REGION)."
