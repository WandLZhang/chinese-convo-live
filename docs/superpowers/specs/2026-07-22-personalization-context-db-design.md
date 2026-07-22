# Personalization Context DB — Design Spec

**Date:** 2026-07-22
**Project:** chinese-convo-live
**Status:** Approved (brainstorming) → pending implementation plan

## Overview

chinese-convo-live opens each conversation with a personalized question grounded in the learner's
real life (Calendar, Gmail, Drive, Signal). This spec defines a **deterministic context database**
built **server-side, hourly**, from which a **client-side randomizer** picks one unused entry per
language to flavor the opener. Generation already accepts `personalContext`; this feature supplies it.

## Goals / Non-goals

**Goals**
- Server-side hourly ingestion of Calendar + Gmail + Drive (Cloud Scheduler + Cloud Function).
- Persistent server-side Signal ingestion (locked-down VM with a linked signal-cli device).
- A deterministic, deduplicated DB (`context_entries`); no duplicate entries across runs.
- Randomizer picks an **unused** entry, **no repeats per language** (mark-used on generation).
- Identity-theft-safe: strip credentials/financial/ID data at distill time.
- Owner-only access; Secret Manager for all secrets; least-privilege service accounts.

**Non-goals**
- Real-time ingestion (hourly is enough). Multi-user. WhatsApp / Messenger.

## Architecture

```
Cloud Scheduler (hourly)
   └─> convo_live_ingest_google  (Cloud Function, gen2, us-east4)
          ├─ Secret Manager: OAuth refresh token + client secret
          ├─ Calendar / Gmail / Drive  ── distill(Grok, identity-filter) ─┐
          └─ dedup + write ──────────────────────────────────────────────┤
                                                                          ▼
GCE VM  convo-live-signal (cron)                               context_entries (Firestore, owner-only)
   └─ signal-cli receive ── distill(Grok, identity-filter) ── dedup + write ┘
                                                                          ▲
App opener (client) ─ read unused entry (per lang) ─ personalContext ─ generate ─ mark used{Lang}At ┘
```

## Components

### 1. `context_entries` (Firestore, owner-only)

One document per source-item. Document id = deterministic hash so re-ingesting the same
event/email/file/chat **updates rather than duplicates**.

```
doc id: sha1(source + ":" + sourceRef)[:20]
{
  source:        "calendar" | "gmail" | "drive" | "signal",
  text:          "<one short, conversation-worthy fact in English>",
  sourceRef:     "<original id: event id / message id / file id / signal msg key>",
  createdAt:     <serverTimestamp>,
  usedCantoneseAt: <timestamp | null>,
  usedMandarinAt:  <timestamp | null>
}
```

- Owner-only rules already deployed (`context_entries/{doc}` → owner read/write only).
- Composite index: `(usedCantoneseAt asc)` and `(usedMandarinAt asc)` for "pick an unused entry".

### 2. Google ingestion — `convo_live_ingest_google` (Cloud Function, gen2, us-east4)

- Triggered **hourly by Cloud Scheduler** (OIDC-authenticated invoker; function is not public).
- Credentials from **Secret Manager**: `convo-live-google-oauth-refresh-token`, `convo-live-google-oauth-client` (client id+secret). Read at runtime via the function SA's `secretAccessor`.
- **Calendar** (`calendar.readonly`): all events in a rolling window (e.g. −30d … +60d); one entry per event (title, time, attendees → a fact like "You have dinner with X on Fri").
- **Gmail** (`gmail.readonly`): up to **100 messages/run**, preferring important + to/from the user (`is:important OR to:me OR from:me`). A stored cursor (pageToken + newest-seen `internalDate`) walks fresh-first then backfills older, so it covers the inbox **over time**; dedup by message id means no re-work.
- **Drive** (`drive.readonly`): recently-modified files — names + extracted text (Docs export as text/plain; skip binaries); one entry per file.
- **Distill**: each raw item → Grok → one short English fact, **identity-theft filtered** (see §5). Batched per source to limit calls.
- **Write**: upsert `context_entries` by hash; leave `used*At` untouched on updates.
- **SA** `convo-live-ingest@…`: `datastore.user`, `aiplatform.user`, `secretmanager.secretAccessor` (on the two secrets only).

### 3. Signal ingestion — locked-down GCE VM `convo-live-signal`

- `e2-micro`, us-east4; **no external IP**; **Shielded VM**; **OS Login**; SSH only via **IAP**; egress via **Cloud NAT**; Private Google Access on for Firestore/Vertex/Secret Manager.
- signal-cli (+ JRE) installed; **linked device** created once via `signal-cli link` (QR shown over IAP SSH, scanned from phone). Linked-device store lives on the persistent boot disk (encrypted at rest).
- **cron** (hourly, offset from the Google run): `signal-cli receive` → distill (Grok, same identity filter) → upsert `context_entries` (source=`signal`, dedup by message key).
- **SA** `convo-live-signal@…`: `datastore.user`, `aiplatform.user` (no secret access needed; no Google-OAuth on this box).

### 4. Randomizer — client-side (opener path in `useConversation`)

On an opener turn:
1. Query `context_entries where used{Lang}At == null orderBy(used{Lang}At) limit(N)`, pick one (random among the batch, or oldest-created).
2. Pass its `text` as `personalContext` to `generateQuestion({ isOpener: true, personalContext })`.
3. On success, set that entry's `used{Lang}At = serverTimestamp()` (no repeats **per language** — an entry can flavor one Cantonese opener and one Mandarin opener).
4. If no unused entry exists → generic opener (best-effort, non-blocking).

### 5. Identity-theft filter (at distill)

Applied inside every distill call (Google + Signal). The model must **drop and never emit**:
passwords, passcodes, PINs, 2FA/OTP/security codes, credentials/API keys; financial account,
card, routing, or CVV numbers; SSN / national-ID / passport / driver-license numbers; full home
address; anything whose leak enables identity theft or account takeover. It **keeps** ordinary
life facts (hikes, trips, meals, projects, people, plans, hobbies). Distill returns `""` (→ entry
skipped) if the item is entirely sensitive. Cloud Logging is IAM-gated, so logs are acceptable, but
the distilled `text` is what persists and it must already be scrubbed.

### 6. Secrets (best practice)

- **Secret Manager** holds the OAuth **refresh token** and OAuth **client** (id+secret). Versioned.
- Access via **per-SA `secretmanager.secretAccessor`** on the specific secrets only (least privilege).
- Nothing secret in code, env vars, or the repo. Refresh-token rotation = add a new secret version.

## One-time setup (user, manual — cannot be automated)

1. **OAuth consent screen → Production** publishing status (see Risks: Testing status expires refresh
   tokens in 7 days). Single-user personal app; click through the "unverified app" screen.
2. **Authorize offline access once** (browser, `access_type=offline&prompt=consent`, scopes:
   calendar.readonly, gmail.readonly, drive.readonly) → capture the **refresh token** → store in
   Secret Manager.
3. **Signal**: `gcloud compute ssh` (IAP) into the VM, `signal-cli link -n convo-live`, scan the QR.

## Verification

- **Ingestion function**: invoke once; confirm `context_entries` populated per source; re-invoke and
  confirm **no duplicates** (dedup by hash); inject a synthetic email containing a fake password and
  confirm the entry is dropped/scrubbed (identity filter).
- **Randomizer**: confirm an opener consumes one unused entry, sets `used{Lang}At`, and never reuses
  it for that language; confirm generic fallback when the pool is empty.
- **Signal VM**: link device; send a test message; confirm it appears distilled in `context_entries`.
- **Secrets**: confirm the function reads the refresh token from Secret Manager (not env); confirm
  the token survives >7 days (Production publishing).

## Risks / open items

- **Refresh-token expiry (KEY):** OAuth apps in **Testing** publishing status expire refresh tokens
  after **7 days** — fatal for "hourly forever." Mitigation: publish the consent screen to
  **Production** (unverified is fine for the sole owner-user). If Google blocks the restricted
  gmail/drive scopes while unverified, fall back to narrower scopes or accept periodic re-auth.
- **Gmail "forever" cursor:** needs a durable cursor (pageToken + high-water `internalDate`) in a
  small state doc so runs don't loop over the same 100.
- **Drive content:** only text-extractable files (Docs/txt); binaries contribute name only.
- **VM cost:** e2-micro ≈ $6–7/mo (us-east4 is not free-tier). Acceptable.
- **Distill cost/volume:** 100 emails/hr + events + files + signal → cap calls, batch per source.
