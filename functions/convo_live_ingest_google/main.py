"""
convo_live_ingest_google — hourly server-side ingestion of Calendar / Gmail / Drive into the
`context_entries` personalization DB. Triggered by Cloud Scheduler (OIDC-authenticated invoker).

- OAuth refresh token + client are read from Secret Manager (never env/code/logs).
- Each raw item is distilled by Grok into ONE short conversation-worthy fact, with a hard
  identity-theft filter (drop credentials/financial/ID data).
- Entries dedup by hash(source+sourceRef): re-ingesting the same item updates text, never
  duplicates, and never touches the per-language used flags.

See docs/superpowers/specs/2026-07-22-personalization-context-db-design.md.
"""
import datetime
import hashlib
import json
import os
import traceback

import functions_framework
import google.auth
import google.auth.transport.requests
import requests
from flask import jsonify
from google.cloud import firestore, secretmanager
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

_adc, _adc_project = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
PROJECT = os.getenv("PROJECT_ID") or _adc_project  # deploy project; no hardcoded id
GROK_MODEL = "xai/grok-4.1-fast-non-reasoning"
GROK_URL = (f"https://aiplatform.googleapis.com/v1/projects/{PROJECT}"
            "/locations/global/endpoints/openapi/chat/completions")
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly",
          "https://www.googleapis.com/auth/gmail.readonly",
          "https://www.googleapis.com/auth/drive.readonly"]
GMAIL_PER_RUN = 100
SECRET_CLIENT = "convo-live-google-oauth-client"          # JSON: {client_id, client_secret}
SECRET_REFRESH = "convo-live-google-oauth-refresh-token"  # the refresh token string

db = firestore.Client(project=PROJECT)
_sm = secretmanager.SecretManagerServiceClient()


def _secret(name):
    r = _sm.access_secret_version(name=f"projects/{PROJECT}/secrets/{name}/versions/latest")
    return r.payload.data.decode("utf-8")


def _google_creds():
    client = json.loads(_secret(SECRET_CLIENT))
    creds = Credentials(
        None, refresh_token=_secret(SECRET_REFRESH).strip(),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client["client_id"], client_secret=client["client_secret"], scopes=SCOPES)
    creds.refresh(google.auth.transport.requests.Request())
    return creds


def _grok_token():
    _adc.refresh(google.auth.transport.requests.Request())
    return _adc.token


def distill(raw, source):
    """One short conversation-worthy fact, identity-theft filtered. Returns '' to skip."""
    sysp = ("You turn a raw personal-data item into ONE short, natural, conversation-worthy fact about "
            "the user (<=20 words, English) usable to open a friendly chat. "
            "HARD RULE — NEVER include: passwords, passcodes, PINs, 2FA/OTP/security codes, credentials, "
            "API keys; financial account/card/routing/CVV numbers; SSN/national-ID/passport/license "
            "numbers; full home address. If the item is entirely sensitive or has no conversational "
            "value, output NOTHING. Output ONLY the fact, no preamble, no quotes.")
    r = requests.post(GROK_URL, timeout=60,
        headers={"Authorization": f"Bearer {_grok_token()}", "Content-Type": "application/json"},
        json={"model": GROK_MODEL, "temperature": 0.3, "max_tokens": 60,
              "messages": [{"role": "system", "content": sysp},
                           {"role": "user", "content": f"Source: {source}\nRaw item:\n{raw[:4000]}"}]})
    r.raise_for_status()
    content = r.json()["choices"][0]["message"].get("content")  # null when the model emits nothing
    return (content or "").strip()


def _looks_sensitive(text):
    """Deterministic safety net UNDER the LLM redaction (not semantic parsing): drop if a long
    digit run (card/account/routing, 11+) or an SSN-shaped 3-2-4 group survived the distill."""
    groups, cur = [], ""
    for ch in text:
        if ch.isdigit():
            cur += ch
        else:
            if cur:
                groups.append(cur)
                cur = ""
    if cur:
        groups.append(cur)
    if any(len(g) >= 11 for g in groups):
        return True
    return any(len(groups[i]) == 3 and len(groups[i + 1]) == 2 and len(groups[i + 2]) == 4
               for i in range(len(groups) - 2))


def upsert(source, source_ref, text):
    """Dedup by hash; new -> insert with null used flags; existing -> refresh text only."""
    if not text or len(text) < 4:
        return False
    if _looks_sensitive(text):
        print(f"backstop dropped {source}:{source_ref} (number pattern in '{text[:40]}')")
        return False
    doc_id = "e" + hashlib.sha1(f"{source}:{source_ref}".encode("utf-8")).hexdigest()[:20]
    ref = db.collection("context_entries").document(doc_id)
    if ref.get().exists:
        ref.update({"text": text})
        return False
    ref.set({"source": source, "sourceRef": source_ref, "text": text,
             "createdAt": firestore.SERVER_TIMESTAMP, "usedCantoneseAt": None, "usedMandarinAt": None})
    return True


def ingest_calendar(creds):
    svc = build("calendar", "v3", credentials=creds, cache_discovery=False)
    now = datetime.datetime.utcnow()
    events = svc.events().list(
        calendarId="primary", timeMin=(now - datetime.timedelta(days=30)).isoformat() + "Z",
        timeMax=(now + datetime.timedelta(days=60)).isoformat() + "Z",
        maxResults=100, singleEvents=True, orderBy="startTime").execute().get("items", [])
    n = 0
    for e in events:
        try:
            start = e.get("start", {}).get("dateTime", e.get("start", {}).get("date", ""))
            att = ", ".join(a.get("email", "") for a in e.get("attendees", [])[:5])
            raw = f"Event: {e.get('summary','')}\nWhen: {start}\nWith: {att}\nNotes: {e.get('description','')[:500]}"
            if upsert("calendar", e.get("id", ""), distill(raw, "calendar")):
                n += 1
        except Exception as ex:  # noqa: BLE001 — one bad item must not abort the batch
            print(f"calendar item skipped: {ex}")
    return n


def ingest_gmail(creds):
    svc = build("gmail", "v1", credentials=creds, cache_discovery=False)
    state = db.collection("ingest_state").document("gmail")
    page = (state.get().to_dict() or {}).get("pageToken")
    resp = svc.users().messages().list(
        userId="me",
        # in:inbox — the owner keeps a curated inbox (junk gets trashed), so everything still in it is
        # worthwhile, important or not. Respects their own filing better than Gmail's is:important guess.
        q="in:inbox",
        maxResults=GMAIL_PER_RUN, pageToken=page).execute()
    n = 0
    for m in resp.get("messages", []):
        try:
            full = svc.users().messages().get(
                userId="me", id=m["id"], format="metadata",
                metadataHeaders=["Subject", "From", "To", "Date"]).execute()
            h = {x["name"]: x["value"] for x in full.get("payload", {}).get("headers", [])}
            raw = f"Subject: {h.get('Subject','')}\nFrom: {h.get('From','')}\nSnippet: {full.get('snippet','')[:600]}"
            if upsert("gmail", m["id"], distill(raw, "gmail")):
                n += 1
        except Exception as ex:  # noqa: BLE001
            print(f"gmail item skipped: {ex}")
    # advance cursor to walk the inbox over time; None restarts from newest next run
    state.set({"pageToken": resp.get("nextPageToken")}, merge=True)
    return n


def ingest_drive(creds):
    svc = build("drive", "v3", credentials=creds, cache_discovery=False)
    files = svc.files().list(orderBy="modifiedTime desc", pageSize=30, q="trashed=false",
                             fields="files(id,name,mimeType)").execute().get("files", [])
    n = 0
    for f in files:
        try:
            text = ""
            if f.get("mimeType") == "application/vnd.google-apps.document":
                try:
                    text = svc.files().export(fileId=f["id"], mimeType="text/plain").execute().decode("utf-8")[:1500]
                except Exception:  # noqa: BLE001
                    text = ""
            raw = f"File: {f.get('name','')}\nContent: {text}"
            if upsert("drive", f["id"], distill(raw, "drive")):
                n += 1
        except Exception as ex:  # noqa: BLE001
            print(f"drive item skipped: {ex}")
    return n


@functions_framework.http
def convo_live_ingest_google(request):
    try:
        creds = _google_creds()
        counts = {"calendar": ingest_calendar(creds),
                  "gmail": ingest_gmail(creds),
                  "drive": ingest_drive(creds)}
        print(f"ingest counts (new entries): {counts}")
        return (jsonify({"ok": True, "new": counts}), 200)
    except Exception as e:  # noqa: BLE001
        print(traceback.format_exc())
        return (jsonify({"error": str(e)}), 500)
