"""
Benchmark the GENERATION step — the sentence the learner actually reads every turn.

Uses the REAL production prompt (imported from the deployed function) with REAL vocab words and REAL
personal-context facts from Firestore, so this measures the app as it actually runs.

Quality is reference-free (there is no gold "correct sentence"), so an anonymized + comparative
LLM-judge panel scores each candidate on the axes that matter here — word usage & register, grammar,
naturalness, relevance. This is the axis that plain synonym-recall + latency missed (it's why the app
moved off Grok 4.1 Fast: grok wrote 冰淇淋 in Cantonese and forced 擔保 where 保證 belongs).

Latency is reported separately (TTFT matters — the sentence is streamed).

Run:
  source bench/.venv/bin/activate
  LLM_PROJECT=your-model-project DATA_PROJECT=your-gcp-project python bench/bench_generation.py --n 16
"""
import argparse
import json
import os
import random
import statistics
import sys
import time
from collections import defaultdict

import google.auth
import google.auth.transport.requests
import requests
from anthropic import AnthropicVertex
from google.cloud import firestore

# Reuse the deployed function's prompt builder verbatim — no drift between bench and production.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "functions", "convo_live_generate_question"))
from main import build_prompt  # noqa: E402

LLM_PROJECT = os.getenv("LLM_PROJECT", "your-model-project")  # where the candidate models are enabled
DATA_PROJECT = os.getenv("DATA_PROJECT", "your-gcp-project")  # where vocab + context live

_creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
_ant = AnthropicVertex(region="global", project_id=LLM_PROJECT)
_db = firestore.Client(project=DATA_PROJECT)
_MAAS = (f"https://aiplatform.googleapis.com/v1/projects/{LLM_PROJECT}"
         "/locations/global/endpoints/openapi/chat/completions")

# Candidates: the shipped model, the new Opus, and the fast contender.
CANDIDATES = [
    {"id": "claude-sonnet-5", "vertex_id": "claude-sonnet-5", "family": "claude"},   # currently shipped
    {"id": "claude-opus-5", "vertex_id": "claude-opus-5", "family": "claude"},
    {"id": "grok-4.20", "vertex_id": "xai/grok-4.20-non-reasoning", "family": "maas"},
]
# Judges from two families; neither is a candidate (avoids self-preference).
JUDGES = [
    {"id": "gemini-judge", "vertex_id": "gemini-3.6-flash", "family": "gemini"},
    {"id": "opus48-judge", "vertex_id": "claude-opus-4-8", "family": "claude"},
]

RUBRIC = """You are judging short CHINESE PRACTICE SENTENCES written for a language learner.
Every candidate was given the SAME task: write ONE natural, colloquial sentence that USES a target
vocabulary word, in the given language, tied to a fact about the learner's life.

Score each candidate 1-5 (5 best) on overall quality, judged on:
1. WORD USAGE & REGISTER (most important) — does it contain the exact target word, used correctly and
   in a register a real speaker would use for THAT word? Forcing a formal/written word into a breezy
   casual line, or using a wrong sense, is a major flaw.
2. GRAMMAR & CONSTRUCTION — grammatical, no register/logic clashes.
3. NATURALNESS — a real speaker would actually say this out loud. For Cantonese it must be colloquial
   口語 in Traditional characters (嘅/喺/唔/佢/啲/咗) and must NOT use Mandarin-only words
   (e.g. 冰淇淋 instead of 雪糕); for Mandarin, natural spoken Mandarin.
4. RELEVANCE — plausibly ties to the learner's fact.
Cap at 1 if the target word is absent, the language is wrong, romanization leaked, or it's garbled.

Be discriminating — do NOT cluster scores; use the full 1-5 range. Return ONLY JSON:
{"scores":{"A":{"overall":n,"rationale":"<=12 words"},...},"best":"X"}"""


def _token():
    _creds.refresh(google.auth.transport.requests.Request())
    return _creds.token


def generate(model, system, nudge, max_tokens=1200):
    """Streamed generation -> (text, ttft, total). Streaming so TTFT is the real felt latency."""
    t0 = time.monotonic()
    ttft = None
    parts = []
    if model["family"] == "claude":
        with _ant.messages.stream(model=model["vertex_id"], max_tokens=max_tokens, system=system,
                                  messages=[{"role": "user", "content": nudge}]) as s:
            for t in s.text_stream:
                if ttft is None:
                    ttft = time.monotonic() - t0
                parts.append(t)
    else:
        r = requests.post(_MAAS, stream=True, timeout=90,
                          headers={"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"},
                          json={"model": model["vertex_id"], "temperature": 0.7, "max_tokens": max_tokens,
                                "stream": True,
                                "messages": [{"role": "system", "content": system},
                                             {"role": "user", "content": nudge}]})
        r.raise_for_status()
        for raw in r.iter_lines():
            if not raw:
                continue
            line = raw.decode("utf-8")
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                delta = json.loads(data)["choices"][0]["delta"].get("content")
            except Exception:  # noqa: BLE001
                continue
            if delta:
                if ttft is None:
                    ttft = time.monotonic() - t0
                parts.append(delta)
    return "".join(parts).strip(), ttft, time.monotonic() - t0


def judge_group(judge, item, outputs):
    """Anonymized + comparative: all candidates for one item, shuffled, scored together."""
    order = list(outputs.items())
    random.Random(hash(item["word"]) & 0xFFFFFFFF).shuffle(order)
    labels = [chr(ord("A") + i) for i in range(len(order))]
    blocks = "\n\n".join(f"### Candidate {lab}\n{txt or '(no output)'}" for lab, (_, txt) in zip(labels, order))
    user = (f"Language: {item['language']}\nTarget word: {item['target']}\n"
            f"Learner's fact: {item['fact']}\n\n{blocks}\n\nGrade every candidate now. JSON only.")
    if judge["family"] == "claude":
        m = _ant.messages.create(model=judge["vertex_id"], max_tokens=2000, system=RUBRIC,
                                 messages=[{"role": "user", "content": user}])
        txt = "".join(b.text for b in m.content if getattr(b, "type", None) == "text")
    else:
        from google import genai
        from google.genai.types import GenerateContentConfig
        cl = genai.Client(vertexai=True, project=LLM_PROJECT, location="global")
        resp = cl.models.generate_content(model=judge["vertex_id"], contents=user,
                                          config=GenerateContentConfig(system_instruction=RUBRIC,
                                                                       temperature=0, max_output_tokens=2000))
        txt = resp.text or ""
    a, b = txt.find("{"), txt.rfind("}")
    parsed = json.loads(txt[a:b + 1])
    scores = parsed.get("scores", {})
    best = parsed.get("best")
    out = {}
    for lab, (mid, _) in zip(labels, order):
        sc = scores.get(lab) or {}
        out[mid] = {"overall": sc.get("overall"), "rationale": sc.get("rationale", ""), "is_best": lab == best}
    return out


def load_items(n):
    """Real vocab words (mix of both languages) + real personal-context facts."""
    vocab = [d.to_dict() for d in _db.collection("vocabulary").limit(400).stream()]
    vocab = [v for v in vocab if v.get("simplified")]
    facts = [str(d.to_dict().get("text", ""))
             for d in _db.collection("context_entries").order_by(
                 "createdAt", direction=firestore.Query.DESCENDING).limit(60).stream()]
    facts = [f for f in facts if f]
    rnd = random.Random(7)
    items = []
    for i in range(n):
        v = rnd.choice(vocab)
        language = "cantonese" if i % 2 else "mandarin"
        alt = v.get("alt") if language == "cantonese" else None
        system, target = build_prompt(v["simplified"], alt, language, rnd.choice(facts), "")
        items.append({"word": v["simplified"], "target": target, "language": language,
                      "fact": "(see prompt)", "system": system,
                      "nudge": "開始。" if language == "cantonese" else "开始。"})
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=12)
    ap.add_argument("--out", default="bench/results/generation_models.jsonl")
    args = ap.parse_args()

    items = load_items(args.n)
    print(f"{len(items)} items | candidates: {[c['id'] for c in CANDIDATES]} | judges: {[j['id'] for j in JUDGES]}\n")
    os.makedirs(os.path.dirname(args.out), exist_ok=True)

    lat = defaultdict(lambda: {"ttft": [], "total": [], "ok": 0})
    quality = defaultdict(list)
    wins = defaultdict(int)
    with open(args.out, "w", encoding="utf-8") as f:
        for idx, item in enumerate(items, 1):
            outputs = {}
            for c in CANDIDATES:
                try:
                    text, ttft, total = generate(c, item["system"], item["nudge"])
                    outputs[c["id"]] = text
                    s = lat[c["id"]]
                    s["ttft"].append(ttft)
                    s["total"].append(total)
                    s["ok"] += 1
                    print(f"[{idx}/{len(items)}] {item['language'][:3]} {item['target']:6} {c['id']:16} "
                          f"ttft={ttft:.2f}s  {text[:60]}")
                except Exception as e:  # noqa: BLE001
                    outputs[c["id"]] = ""
                    print(f"[{idx}/{len(items)}] {c['id']:16} ERROR {str(e)[:70]}")
            verdicts = {}
            for j in JUDGES:
                try:
                    verdicts[j["id"]] = judge_group(j, item, outputs)
                except Exception as e:  # noqa: BLE001
                    print(f"    judge {j['id']} failed: {str(e)[:70]}")
            for mid in outputs:
                vals = [v[mid]["overall"] for v in verdicts.values()
                        if v.get(mid, {}).get("overall") is not None]
                if vals:
                    quality[mid].append(statistics.mean(vals))
                wins[mid] += sum(1 for v in verdicts.values() if v.get(mid, {}).get("is_best"))
            f.write(json.dumps({"item": {k: item[k] for k in ("word", "target", "language")},
                                "outputs": outputs, "verdicts": verdicts}, ensure_ascii=False) + "\n")
            f.flush()

    print("\n=== SUMMARY (quality 1-5, judge mean | wins | p50 TTFT | p50 total) ===")
    rows = []
    for c in CANDIDATES:
        mid = c["id"]
        q = statistics.mean(quality[mid]) if quality[mid] else float("nan")
        s = lat[mid]
        p50t = sorted(s["ttft"])[len(s["ttft"]) // 2] if s["ttft"] else float("nan")
        p50a = sorted(s["total"])[len(s["total"]) // 2] if s["total"] else float("nan")
        rows.append((q, mid, wins[mid], p50t, p50a, s["ok"]))
    for q, mid, w, p50t, p50a, ok in sorted(rows, reverse=True):
        print(f"  {mid:18} quality={q:.2f}  wins={w:2}  ttft={p50t:.2f}s  total={p50a:.2f}s  ok={ok}/{len(items)}")
    print(f"\nraw -> {args.out}")


if __name__ == "__main__":
    main()
