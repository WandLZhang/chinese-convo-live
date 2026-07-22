# chinese-convo-live

A conversational spaced-repetition trainer for **Cantonese and Mandarin**. It picks a vocab word
that is due for review, weaves it into a natural, colloquial sentence anchored to something from
your own life, and you reply in a chat. Your answer is graded inline (fluency + meaningful usage +
romanization + an improved rewrite) and the word is rescheduled. Text-to-speech reads each prompt.

It is a single-user app: every function and every Firestore document is gated to one owner account.

**Live demo:** https://wz-chinese-convo-live.web.app (owner-gated — sign-in is restricted to the
configured account, so a visitor cannot read any data).

---

## How it works

```
        due/new word ──► generate ──► colloquial sentence + your life + last exchange
                                         │  (Grok 4.1 Fast, streamed)
   you reply ──► grade (Grok) ──► fluent? meaningful? + rewrite + jyutping/pinyin ──► reschedule (SRS)
                                         ▲
   personalization DB (context_entries) ┘  built hourly, server-side, from Calendar/Gmail/Drive/Signal
```

### The colloquial-alternative design (Cantonese)

A formal written word is often not what a Cantonese speaker actually says. The **decision of which
word to use is precomputed, not left to the model at request time**:

1. An offline audit (`audit/`) reads each word's [Words.hk](https://words.hk) dictionary entry and
   applies fixed rules, in order:
   - the entry's example sentences use the word directly → **use the word**;
   - the entry lists a colloquial synonym (a `sim:` tag, or a spoken form inside the gloss) → **use that**;
   - neither → **use the word directly** (a signal it is already the spoken form).
2. The chosen colloquial form is stored as an `alt` field on the vocab document (only about 2% of
   words need one).
3. At request time the generator simply uses `alt` if present, else the word — **no RAG, no
   on-the-fly synonym guessing.** The `alt` path validates that the word actually appears (with a
   retry); the direct path mandates it in the prompt.

Why precompute instead of just handing the model the dictionary at request time and letting it pick
the colloquial word? Because that approach — which is what `bench/` measures — tops out around
55-60% even for the best model, too unreliable to ship. Moving the rule to an offline step makes the
runtime **deterministic**: the app uses the correct word by construction, not by the model's
judgment. (So that 55-60% describes the *rejected* design, not the shipped app, whose word choice is
100% by construction.)

### Models (all benchmark-selected — see `bench/`)

| Job | Choice | Why |
|---|---|---|
| Generation | **Claude Sonnet 5** (Vertex, AnthropicVertex, streamed) | most authentic colloquial register — 雪糕 not 冰淇淋, 擔保 used in its real vouch sense; top of an LLM-judge quality panel (4.21/5); TTFT ~0.6-0.8s |
| Grading | **Grok 4.1 Fast** (Vertex MaaS) | 100% agreement with gold labels on the curated set, ~1.1s (classification is easy — speed wins) |
| Romanization | **ToJyutping / pypinyin** (libraries) | deterministic and instant — beats the LLM, especially jyutping tones |
| Text-to-speech | **Cloud TTS Chirp 3 HD** (`yue-HK`, `cmn-CN`) | ~0.6s both languages; replaced Gemini native-audio (4-6s, garbled Cantonese) |

The functions derive their GCP project from Application Default Credentials, so **no project id is
hardcoded** — deploy them anywhere the models are enabled in Vertex (Claude Sonnet 5 for generation,
xAI Grok for grading).

---

## Repository layout

```
frontend/                         Vite + React + TypeScript chat app (Firebase Hosting)
functions/
  convo_live_generate_question/   generate the colloquial sentence (Grok, streamed)
  convo_live_evaluate_answer/     grade the answer + schedule next review (evaluate_answer,
                                    update_review_time — two handlers, one source)
  convo_live_generate_audio/      Cloud TTS Chirp 3 HD -> base64 WAV
  convo_live_mark_word_mastered/  mark a word mastered
  convo_live_ingest_google/       hourly server-side Calendar/Gmail/Drive -> context_entries (private)
bench/                            latency + quality harness (generation, grading, TTS)
audit/                            offline Words.hk rule audit that computes the `alt` field
local/                            OAuth token mint + Signal VM reader (workstation/VM only)
scripts/                          setup_infra.sh, deploy_functions.sh
firestore.rules                   single-owner lockdown (default deny)
firestore.indexes.json           SRS composite indexes (nextReview{Mandarin,Cantonese} + timestamp)
```

---

## Setup from scratch

### Prerequisites
- `gcloud` (authenticated), `firebase-tools`, Node 18+, Python 3.12.
- A GCP project with billing, and access to Grok 4.1 Fast in Vertex Model Garden.

### 1. OAuth consent + client (console — needed only for personalization)
Create an OAuth consent screen (External, **Testing** mode; add your account as a test user) with
scopes `calendar.readonly`, `gmail.readonly`, `drive.metadata.readonly`. Create an **OAuth Client
ID** of type *Desktop app* for the token-mint flow. (The app itself uses Firebase Auth, not this
client — this is only for the server-side ingestion pipeline.)

### 2. Provision infrastructure
```bash
PROJECT_ID=your-gcp-project OWNER_EMAIL=you@example.com ./scripts/setup_infra.sh
firebase use your-gcp-project        # writes .firebaserc (gitignored)
```
This enables APIs, grants the runtime SA (build + Vertex + Firestore), creates the Firestore
database + indexes + rules, the Hosting site, and — unless `WITH_PERSONALIZATION=false` — the VPC,
Cloud NAT, Shielded Signal VM, and hourly Cloud Scheduler job. Set `WITH_PERSONALIZATION=false` to
run just the core app.

### 3. Frontend config
```bash
cp frontend/src/services/firebase.config.example.ts frontend/src/services/firebase.config.ts
# fill in your Firebase web app values + appConfig.ownerEmail + appConfig.region
```
`firebase.config.ts` is gitignored; it is the single source of project-specific frontend config
(the function base URL and owner email are derived from it). Update `firebase.json`'s `hosting.site`
to your own globally-unique site name.

### 4. Deploy
```bash
PROJECT_ID=your-gcp-project ./scripts/deploy_functions.sh
(cd frontend && npm install && npm run build) && firebase deploy --only hosting
```

### 5. (Optional) Personalization
```bash
PROJECT_ID=your-gcp-project OWNER_EMAIL=you@example.com \
  python local/mint_google_token.py /path/to/client_secret.json   # mints OAuth secrets
# re-run the secret-access + scheduler steps of setup_infra.sh now that the secrets/function exist
```
The Signal reader runs on the private VM (`local/signal_vm_startup.sh` installs signal-cli; link a
device with `local/signal_link.sh`, then `local/signal_ingest.py` runs hourly via cron). All
ingestion distills each item through Grok with a hard identity-theft filter before storing.

---

## Local development

```bash
cd frontend
npm install
npm run dev      # http://localhost:5173
npm run build    # tsc -b && vite build -> frontend/dist
npm test         # vitest (SRS scheduling logic)
```

## Benchmarks

```bash
python -m venv bench/.venv && source bench/.venv/bin/activate && pip install -r bench/requirements.txt
PROJECT_ID=your-gcp-project RAG_PROJECT_ID=your-rag-corpus-project \
  python bench/bench_colloquial.py --n 20 --methods A,D   # generation: synonym recall + latency
PROJECT_ID=your-gcp-project python bench/bench_grading.py  # grading: label agreement + latency
PROJECT_ID=your-gcp-project python bench/bench_tts.py      # TTS: latency + round-trip STT accuracy
```
`bench_colloquial` scores whether a model uses a Words.hk-attested colloquial synonym (objective,
against the dictionary) — it is what proved the precompute-the-`alt` design and selected Grok.

## Security model

- `firestore.rules` denies everything except reads/writes from the one verified owner email.
- Public functions (generate, evaluate, audio, mark) only ever touch the `vocabulary` collection.
- The only function that reads personal data (`ingest_google`) is **private** — invocable solely by
  the scheduler's service account via OIDC — and writes to `context_entries`, which the rules gate
  to the owner. There is no endpoint through which a visitor can extract personal data.
- OAuth secrets live in Secret Manager (user-managed replication), never in code, env, or logs.
