"""
Benchmark: does the model use the CORRECT colloquial synonym that Words.hk lists
for a formal word — NOT whether it merely "sounds" colloquial.

Ground truth = the colloquial Cantonese synonym(s) Words.hk attests for the word
(extracted by an LLM from the retrieved dictionary entry — the answer key).

Metric = synonym_hit: does the generated question contain a Words.hk-attested
colloquial synonym (and avoid the formal word)? This is deterministic against
ground truth, not an opinion.

Methods:
  A = RAG (Words.hk corpus)         — inject retrieved entry
  B = web-fetch (live words.hk)     — Claude web_search / Gemini Google-Search grounding
  C = stored-sentence               — inject the Firestore native sentence only
  D = LLM-alone (no reference)      — baseline; should score LOW, proving grounding is needed

Run: source bench/.venv/bin/activate && python bench/bench_colloquial.py --n 5
"""
import argparse
import json
import os
import statistics
import time
from collections import defaultdict

import opencc
from google.cloud import firestore
from anthropic import AnthropicVertex
import vertexai
from vertexai.preview import rag
from google import genai
from google.genai.types import GenerateContentConfig, Tool, GoogleSearch
import google.auth
import google.auth.transport.requests
import requests

LLM_PROJECT = os.getenv("PROJECT_ID", "your-gcp-project")            # billing/serving project for the LLMs
RAG_PROJECT = os.getenv("RAG_PROJECT_ID", "your-rag-corpus-project")  # project hosting the Words.hk RAG corpus
RAG_LOCATION = "us-central1"

conv = opencc.OpenCC("s2t")
_anthropic = AnthropicVertex(region="global", project_id=LLM_PROJECT)
_genai = genai.Client(vertexai=True, project=LLM_PROJECT, location="global")
vertexai.init(project=RAG_PROJECT, location=RAG_LOCATION)
_db = firestore.Client(project=LLM_PROJECT)
_creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])

_ONLY = "Output ONLY one natural spoken-Cantonese question — no jyutping, no translation."

# ---------- RAG ----------
_CORPUS = None
def _retrieve(text: str, k: int) -> list:
    global _CORPUS
    if _CORPUS is None:
        cs = list(rag.list_corpora())
        _CORPUS = cs[0].name if cs else ""
    if not _CORPUS or not text:
        return []
    try:
        r = rag.retrieval_query(rag_resources=[rag.RagResource(rag_corpus=_CORPUS)],
                                text=text, similarity_top_k=k, vector_distance_threshold=0.6)
        return list(r.contexts.contexts)
    except Exception:  # noqa: BLE001
        return []

def rag_entry(word: str) -> str:
    """Method-A context: retrieve on the TRADITIONAL headword, top-12 (was simplified/top-3
    — which missed the entry entirely for ~20% of words)."""
    return "\n".join(c.text for c in _retrieve(conv.convert(word), 12))[:4000]

def rag_ground_truth(word: str, stored: str) -> str:
    """Widest net for building the answer key: traditional headword (top-12) UNION the stored
    native sentence (top-8). The sentence embeds near colloquial forms the formal headword
    never reaches (叼->咬住, 洽談->傾偈)."""
    seen, out = set(), []
    for c in _retrieve(conv.convert(word), 12) + _retrieve(stored, 8):
        if c.text not in seen:
            seen.add(c.text); out.append(c.text)
    return "\n".join(out)[:6000]

# ---------- ground-truth answer key ----------
def answer_key(word: str, entry: str) -> list:
    """Colloquial Cantonese synonym(s) Words.hk attests for `word`, extracted STRICTLY from
    the retrieved entries text — then a deterministic guard drops anything not literally
    present, so the key is Words.hk ground truth, never the extractor's own knowledge."""
    sysp = ("You extract ground truth STRICTLY from provided Words.hk (粵典) entries. List the "
            "spoken-Cantonese word(s)/expression(s) usable for the given meaning that LITERALLY "
            "APPEAR in the entries text (as headwords, sim: tags, or inside yue: glosses/examples). "
            "Include colloquial and neutral spoken forms; exclude only the formal input word "
            "itself. Never add a word that is not written in the text. Traditional characters.")
    user = (f"Formal word: {word}\nWords.hk entries:\n{entry}\n\n"
            'Return ONLY JSON: {"synonyms":["..."]} — colloquial items that appear verbatim above.')
    try:
        raw = _claude_text("claude-sonnet-4-5@20250929", sysp, user, max_tokens=250)
        import re
        m = re.search(r"\{.*\}", raw, 16)  # 16 = re.DOTALL — extract the JSON blob only
        syns = json.loads(m.group(0))["synonyms"] if m else []
        # hard grounding guard: keep only synonyms that literally occur in the retrieved text
        return [s.strip() for s in syns if s.strip() and s.strip() in entry]
    except Exception:  # noqa: BLE001
        return []

# ---------- model text helpers ----------
def _claude_text(model_id, system, user, max_tokens=160):
    r = _anthropic.messages.create(model=model_id, max_tokens=max_tokens, temperature=0.7,
                                   system=system, messages=[{"role": "user", "content": user}])
    return "".join(b.text for b in r.content if getattr(b, "type", None) == "text").strip()

def _gemini_text(model_id, system, user, max_tokens=160):
    r = _genai.models.generate_content(model=model_id, contents=user,
        config=GenerateContentConfig(system_instruction=system, temperature=0.7, max_output_tokens=max_tokens))
    return (r.text or "").strip()

def _grok_text(model_id, system, user, max_tokens=160):
    """xAI on Vertex via the OpenAI-compatible endpoint (global region)."""
    _creds.refresh(google.auth.transport.requests.Request())
    url = (f"https://aiplatform.googleapis.com/v1/projects/{LLM_PROJECT}"
           "/locations/global/endpoints/openapi/chat/completions")
    resp = requests.post(url, timeout=60,
        headers={"Authorization": f"Bearer {_creds.token}", "Content-Type": "application/json"},
        json={"model": model_id, "temperature": 0.7, "max_tokens": max_tokens,
              "messages": [{"role": "system", "content": system},
                           {"role": "user", "content": user}]})
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()

def _claude_websearch(model_id, word):
    r = _anthropic.messages.create(model=model_id, max_tokens=400,
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}],
        system=("You are a HK Cantonese generator. Search words.hk to find the colloquial "
                "Cantonese expression natives use for the given formal word, then write ONE "
                "natural spoken-Cantonese question using that colloquial expression (not the "
                f"formal word). {_ONLY}"),
        messages=[{"role": "user", "content": f"Formal word: {word}. Search site:words.hk for its colloquial Cantonese equivalent, then write the question."}])
    return "".join(b.text for b in r.content if getattr(b, "type", None) == "text").strip()

def _gemini_websearch(model_id, word):
    r = _genai.models.generate_content(model=model_id,
        contents=(f"Search words.hk for the colloquial Cantonese equivalent of the formal word "
                  f"'{word}', then write ONE natural spoken-Cantonese question using that colloquial "
                  f"word (not the formal one). {_ONLY}"),
        config=GenerateContentConfig(tools=[Tool(google_search=GoogleSearch())], temperature=0.7, max_output_tokens=250))
    return (r.text or "").strip()

# model registry: family + text/websearch callables
MODELS = {
    "claude-haiku-4-5":      ("claude", "claude-haiku-4-5@20251001"),
    "claude-sonnet-4-5":     ("claude", "claude-sonnet-4-5@20250929"),
    "gemini-3.5-flash-lite": ("gemini", "gemini-3.5-flash-lite"),
    "gemini-3.5-flash":      ("gemini", "gemini-3.5-flash"),
    "gemini-3.6-flash":      ("gemini", "gemini-3.6-flash"),
    "gemini-3.6-flash-lite": ("gemini", "gemini-3.6-flash-lite"),
    "grok-4.1-fast":         ("grok", "xai/grok-4.1-fast-non-reasoning"),
}

def generate(model_name, method, word, rag_ctx, stored):
    family, mid = MODELS[model_name]
    if method == "B":  # web-fetch
        return _claude_websearch(mid, word) if family == "claude" else _gemini_websearch(mid, word)
    if method == "A":
        ref = f"Words.hk dictionary entry:\n{rag_ctx}"
    elif method == "C":
        ref = f"Native example sentence:\n{stored}"
    else:  # D
        ref = "(no reference provided)"
    system = (f'You are a natural Hong Kong Cantonese generator. "{word}" is FORMAL/written — do '
              f"NOT use it; use the colloquial expression natives actually say.\n{ref}\n{_ONLY}")
    user = f"Formal word: {word}. Write ONE natural spoken-Cantonese question."
    if family == "claude":
        return _claude_text(mid, system, user)
    if family == "grok":
        return _grok_text(mid, system, user)
    return _gemini_text(mid, system, user)

def synonym_hit(output: str, synonyms: list) -> bool:
    return any(s and s in output for s in synonyms)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--methods", default="A,B,C,D")
    ap.add_argument("--out", default="bench/results/colloquial.jsonl")
    args = ap.parse_args()
    methods = args.methods.split(",")

    words = []
    for d in _db.collection("vocabulary").limit(args.n * 30).stream():
        x = d.to_dict()
        w, c = x.get("simplified"), x.get("cantonese")
        if w and c and conv.convert(w) not in c:   # requires_alt
            entry = rag_entry(w)                      # method-A context (word-based retrieval)
            gt = rag_ground_truth(w, c)              # widest net (word + native sentence) for the key
            key = answer_key(w, gt)
            if key:                                  # drop words with no grounded answer key (e.g. 公式)
                words.append({"word": w, "cantonese": c, "entry": entry, "key": key})
        if len(words) >= args.n:
            break
    print(f"{len(words)} words with Words.hk answer keys:")
    for x in words:
        print(f"  {x['word']}: {x['key']}")
    print()

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    rows = []
    with open(args.out, "w", encoding="utf-8") as f:
        for x in words:
            for method in methods:
                for mname in MODELS:
                    t0 = time.time()
                    try:
                        out = generate(mname, method, x["word"], x["entry"], x["cantonese"])
                        row = {"word": x["word"], "method": method, "model": mname,
                               "latency": round(time.time() - t0, 2),
                               "synonym_hit": synonym_hit(out, x["key"]),
                               "formal_absent": conv.convert(x["word"]) not in out,
                               "key": x["key"], "output": out}
                    except Exception as e:  # noqa: BLE001
                        row = {"word": x["word"], "method": method, "model": mname, "error": str(e)[:200]}
                    f.write(json.dumps(row, ensure_ascii=False) + "\n"); f.flush()
                    rows.append(row)
                    print(f"{mname:22} {method} {x['word']:6} lat={row.get('latency','ERR')} "
                          f"hit={row.get('synonym_hit','-')} noFormal={row.get('formal_absent','-')}")

    print("\n=== SUMMARY (method model: %synonym-hit | %avoids-formal | p50 lat | n) ===")
    agg = defaultdict(list)
    for r in rows:
        if "latency" in r:
            agg[(r["method"], r["model"])].append(r)
    for key in sorted(agg):
        rs = agg[key]
        hit = 100 * statistics.mean(1 if r["synonym_hit"] else 0 for r in rs)
        avf = 100 * statistics.mean(1 if r["formal_absent"] else 0 for r in rs)
        lat = sorted(r["latency"] for r in rs)[len(rs) // 2]
        print(f"  {key[0]} {key[1]:22} hit={hit:3.0f}%  avoidFormal={avf:3.0f}%  p50={lat:.2f}s  n={len(rs)}")


if __name__ == "__main__":
    main()
