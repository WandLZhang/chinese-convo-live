"""
Benchmark the GRADING step (evaluate_answer) — quality + speed across models.

Grading has no external ground truth (unlike generation's Words.hk), so quality is measured as
LABEL AGREEMENT against hand-curated cases whose correct labels are unambiguous by construction:
clearly-fluent, clearly-off-topic, filler-heavy, wrong-language, broken. We score the three
boolean judgments the app uses (fluent / meaningful_usage / has_fillers) vs gold, plus latency.
romanization + feedback are captured for eyeball (not auto-scored).

Structured output is forced per provider (Claude tool_use / Gemini JSON mime / Grok json_object).

Run: source bench/.venv/bin/activate && python bench/bench_grading.py
"""
import json
import os
import statistics
import time
from collections import defaultdict

import google.auth
import google.auth.transport.requests
import requests
from anthropic import AnthropicVertex
from google import genai
from google.genai.types import GenerateContentConfig

LLM_PROJECT = os.getenv("PROJECT_ID", "your-gcp-project")
_anthropic = AnthropicVertex(region="global", project_id=LLM_PROJECT)
_genai = genai.Client(vertexai=True, project=LLM_PROJECT, location="global")
_creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
_GROK_URL = (f"https://aiplatform.googleapis.com/v1/projects/{LLM_PROJECT}"
             "/locations/global/endpoints/openapi/chat/completions")

FIELDS = ["fluent", "meaningful_usage", "has_fillers", "romanization", "improved_answer", "feedback"]
BOOL_FIELDS = ["fluent", "meaningful_usage", "has_fillers"]

def sysprompt(language):
    rom = "jyutping" if language == "cantonese" else "pinyin"
    return (f"You are a strict but fair {language} tutor grading a learner's SPOKEN answer to a question. "
            f"Judge, as booleans: fluent (natural & grammatical in {language} — a wrong-language answer is "
            f"NOT fluent), meaningful_usage (actually answers the question, on-topic), has_fillers (excessive "
            f"hesitation/fillers like 呃/嗯/即係/那个/就是). Also give romanization ({rom} of the learner's "
            f"answer), improved_answer (a better natural version), and one-sentence feedback. "
            f"Keys: fluent, meaningful_usage, has_fillers, romanization, improved_answer, feedback.")

# --- curated cases: gold labels are unambiguous by construction ---
CASES = [
    # cantonese
    ("cantonese", "你今日食咗早餐未呀？", "食咗喇，我食咗個菠蘿包同埋凍奶茶。", dict(fluent=True, meaningful_usage=True, has_fillers=False)),
    ("cantonese", "你鍾唔鍾意行山呀？", "我屋企有三隻貓，佢哋好可愛。", dict(fluent=True, meaningful_usage=False, has_fillers=False)),
    ("cantonese", "你平時做咩運動呀？", "呃…即係…我…嗯…有時…即係會跑吓步囉。", dict(fluent=False, meaningful_usage=True, has_fillers=True)),
    ("cantonese", "你今日心情點呀？", "我今天心情很好，因为放假了。", dict(fluent=False, meaningful_usage=True, has_fillers=False)),  # Mandarin answer
    ("cantonese", "你屋企附近有冇好嘢食？", "有…嘢食…好…我唔知點講。", dict(fluent=False, meaningful_usage=False, has_fillers=False)),
    ("cantonese", "你想搵邊個傾吓偈呀？", "我想搵我阿媽傾吓，因為佢最近唔多開心。", dict(fluent=True, meaningful_usage=True, has_fillers=False)),
    # mandarin
    ("mandarin", "你周末打算做什么？", "我打算去公园跑步，然后跟朋友吃饭。", dict(fluent=True, meaningful_usage=True, has_fillers=False)),
    ("mandarin", "你喜欢什么音乐？", "我昨天买了一部新手机，很贵。", dict(fluent=True, meaningful_usage=False, has_fillers=False)),
    ("mandarin", "你最近工作忙吗？", "呃……就是……那个……还……还行吧。", dict(fluent=False, meaningful_usage=True, has_fillers=True)),
    ("mandarin", "你今天吃了什么？", "我食咗個菠蘿包同凍奶茶。", dict(fluent=False, meaningful_usage=True, has_fillers=False)),  # Cantonese answer
    ("mandarin", "你去过北京吗？", "去过，我前年去看了长城，非常壮观。", dict(fluent=True, meaningful_usage=True, has_fillers=False)),
    ("mandarin", "你觉得学中文难吗？", "有点难，声调最难。", dict(fluent=True, meaningful_usage=True, has_fillers=False)),
]

GRADE_TOOL = {"name": "grade", "description": "Return the grading result.",
              "input_schema": {"type": "object", "properties": {
                  "fluent": {"type": "boolean"}, "meaningful_usage": {"type": "boolean"},
                  "has_fillers": {"type": "boolean"}, "romanization": {"type": "string"},
                  "improved_answer": {"type": "string"}, "feedback": {"type": "string"}},
                  "required": FIELDS}}

def _claude_grade(mid, system, user):
    r = _anthropic.messages.create(model=mid, max_tokens=500, temperature=0, system=system,
        tools=[GRADE_TOOL], tool_choice={"type": "tool", "name": "grade"},
        messages=[{"role": "user", "content": user}])
    for b in r.content:
        if getattr(b, "type", None) == "tool_use":
            return dict(b.input)
    return {}

def _gemini_grade(mid, system, user):
    r = _genai.models.generate_content(model=mid, contents=user,
        config=GenerateContentConfig(system_instruction=system, temperature=0,
            response_mime_type="application/json", max_output_tokens=600))
    return json.loads(r.text)

def _grok_grade(mid, system, user):
    _creds.refresh(google.auth.transport.requests.Request())
    r = requests.post(_GROK_URL, timeout=60,
        headers={"Authorization": f"Bearer {_creds.token}", "Content-Type": "application/json"},
        json={"model": mid, "temperature": 0, "max_tokens": 600, "response_format": {"type": "json_object"},
              "messages": [{"role": "system", "content": system + " Return ONLY a JSON object."},
                           {"role": "user", "content": user}]})
    r.raise_for_status()
    return json.loads(r.json()["choices"][0]["message"]["content"])

MODELS = {
    "claude-sonnet-4-5": ("claude", "claude-sonnet-4-5@20250929"),
    "claude-haiku-4-5": ("claude", "claude-haiku-4-5@20251001"),
    "gemini-3.5-flash-lite": ("gemini", "gemini-3.5-flash-lite"),
    "grok-4.1-fast": ("grok", "xai/grok-4.1-fast-non-reasoning"),
}

def grade(model_name, language, question, answer):
    family, mid = MODELS[model_name]
    system = sysprompt(language)
    user = f"Question: {question}\nLearner's answer: {answer}"
    fn = {"claude": _claude_grade, "gemini": _gemini_grade, "grok": _grok_grade}[family]
    return fn(mid, system, user)

def main():
    rows = []
    for language, q, a, gold in CASES:
        for mname in MODELS:
            t0 = time.time()
            try:
                out = grade(mname, language, q, a)
                lat = round(time.time() - t0, 2)
                agree = {f: (bool(out.get(f)) == gold[f]) for f in BOOL_FIELDS}
                rows.append({"model": mname, "lang": language, "q": q, "a": a, "gold": gold,
                             "out": out, "lat": lat, "agree": agree,
                             "all3": all(agree.values())})
                print(f"{mname:22} {language[:4]} lat={lat:>4} "
                      f"F{'✓' if agree['fluent'] else '✗'} "
                      f"M{'✓' if agree['meaningful_usage'] else '✗'} "
                      f"H{'✓' if agree['has_fillers'] else '✗'}  "
                      f"rom={str(out.get('romanization',''))[:22]}")
            except Exception as e:  # noqa: BLE001
                rows.append({"model": mname, "error": str(e)[:160]})
                print(f"{mname:22} {language[:4]} ERROR {str(e)[:120]}")

    with open("bench/results/grading.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print("\n=== SUMMARY (label agreement vs gold | all-3-correct | latency) ===")
    agg = defaultdict(list)
    for r in rows:
        if "lat" in r:
            agg[r["model"]].append(r)
    print(f"{'model':22} fluent% mean% filler% | all3% | p50   p95   n")
    for m in MODELS:
        rs = agg[m]
        if not rs:
            print(f"{m:22} (no data)"); continue
        fl = 100 * statistics.mean(r["agree"]["fluent"] for r in rs)
        me = 100 * statistics.mean(r["agree"]["meaningful_usage"] for r in rs)
        hf = 100 * statistics.mean(r["agree"]["has_fillers"] for r in rs)
        a3 = 100 * statistics.mean(r["all3"] for r in rs)
        ls = sorted(r["lat"] for r in rs)
        p50 = ls[len(ls) // 2]; p95 = ls[min(len(ls) - 1, int(len(ls) * 0.95))]
        print(f"{m:22} {fl:5.0f} {me:6.0f} {hf:6.0f} | {a3:4.0f} | {p50:.2f}  {p95:.2f}  {len(rs)}")

if __name__ == "__main__":
    main()
