#!/opt/venv/bin/python
"""
Signal ingestion (runs on the convo-live-signal VM, hourly via cron).
`signal-cli receive` -> distill each incoming message via Grok (identity-theft filter + digit
backstop) -> upsert into Firestore `context_entries` (source="signal", dedup by timestamp).
Uses the VM's attached SA (convo-live-signal: datastore.user + aiplatform.user).
"""
import hashlib
import json
import os
import subprocess

import google.auth
import google.auth.transport.requests
import requests
from google.cloud import firestore

PROJECT = os.getenv("PROJECT_ID", "your-gcp-project")
GROK_URL = (f"https://aiplatform.googleapis.com/v1/projects/{PROJECT}"
            "/locations/global/endpoints/openapi/chat/completions")
db = firestore.Client(project=PROJECT)
_creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])

DISTILL_SYS = (
    "You turn a raw personal chat message into ONE short, natural, conversation-worthy fact about "
    "the user (<=20 words, English) usable to open a friendly chat. HARD RULE — NEVER include: "
    "passwords, passcodes, PINs, 2FA/OTP/security codes, credentials, API keys; financial "
    "account/card/routing/CVV numbers; SSN/national-ID/passport/license numbers; full home address. "
    "If the message is entirely sensitive or has no conversational value, output NOTHING. "
    "Output ONLY the fact, no preamble, no quotes.")


def _token():
    _creds.refresh(google.auth.transport.requests.Request())
    return _creds.token


def distill(raw):
    r = requests.post(GROK_URL, timeout=60,
        headers={"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"},
        json={"model": "xai/grok-4.1-fast-non-reasoning", "temperature": 0.3, "max_tokens": 60,
              "messages": [{"role": "system", "content": DISTILL_SYS},
                           {"role": "user", "content": raw[:4000]}]})
    r.raise_for_status()
    return (r.json()["choices"][0]["message"].get("content") or "").strip()


def _looks_sensitive(text):
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


def upsert(source_ref, text):
    if not text or len(text) < 4 or _looks_sensitive(text):
        return False
    doc_id = "e" + hashlib.sha1(f"signal:{source_ref}".encode("utf-8")).hexdigest()[:20]
    ref = db.collection("context_entries").document(doc_id)
    if ref.get().exists:
        ref.update({"text": text})
        return False
    ref.set({"source": "signal", "sourceRef": source_ref, "text": text,
             "createdAt": firestore.SERVER_TIMESTAMP, "usedCantoneseAt": None, "usedMandarinAt": None})
    return True


def _account():
    out = subprocess.run(["signal-cli", "listAccounts"], capture_output=True, text=True).stdout
    for tok in out.replace(":", " ").split():
        if tok.startswith("+"):
            return tok
    return None


def main():
    acc = _account()
    if not acc:
        print("no linked signal account")
        return
    out = subprocess.run(["signal-cli", "-a", acc, "-o", "json", "receive"],
                         capture_output=True, text=True, timeout=180).stdout
    n = 0
    for line in out.splitlines():
        try:
            env = json.loads(line).get("envelope", {})
        except Exception:  # noqa: BLE001
            continue
        dm = env.get("dataMessage") or {}
        body = dm.get("message")
        if not body:
            continue
        src = env.get("sourceName") or env.get("sourceNumber") or "someone"
        ts = env.get("timestamp", "")
        try:
            if upsert(str(ts), distill(f"From {src}: {body}")):
                n += 1
        except Exception as ex:  # noqa: BLE001
            print(f"signal item skipped: {ex}")
    print(f"signal ingest: {n} new entries")


if __name__ == "__main__":
    main()
