"""
convo_live_generate_question — chinese-convo-live question generator.

Design (locked): the colloquial-alternative decision is PRE-COMPUTED into Firestore as `alt`
(see audit/). So at request time there is NO rule-sifting and NO RAG:
  - alt present  -> write a natural question using the colloquial word `alt` (meaning anchored
                   by the formal `word`), validated + retried so `alt` actually appears.
  - alt absent   -> write a natural question using `word` directly.
Output is the raw question text, streamed (Grok tokens) for the direct case; the alt case is
generated whole (so it can be validated) then emitted. The client already knows word/alt from
the Firestore doc, so no JSON metadata is returned — just the text.

Model: Grok 4.1 Fast (Non-Reasoning) on Vertex (OpenAI-compatible endpoint) — benchmark-selected
for lowest latency; it emits traditional Cantonese natively. Swap GEN_MODEL to change.
"""
import json
import logging
import os
import traceback

import functions_framework
import google.auth
import google.auth.transport.requests
import opencc
import requests
from flask import Response, jsonify, stream_with_context

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Project = the deploy project (from ADC), overridable via PROJECT_ID — no project id is
# hardcoded. This is where Grok (Vertex OpenAI-compatible endpoint) is billed and served.
_creds, _adc_project = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
LLM_PROJECT = os.getenv("PROJECT_ID") or _adc_project
GEN_MODEL = "xai/grok-4.1-fast-non-reasoning"  # benchmark-selected fastest generation model
_ENDPOINT = (f"https://aiplatform.googleapis.com/v1/projects/{LLM_PROJECT}"
             "/locations/global/endpoints/openapi/chat/completions")

CORS = {"Access-Control-Allow-Origin": "*"}
STREAM_HEADERS = {**CORS, "X-Accel-Buffering": "no", "Cache-Control": "no-cache"}
LANG = {"cantonese": "廣東話", "mandarin": "普通話"}
converter = opencc.OpenCC("s2t")  # simplified -> traditional (Cantonese output must be traditional)


def _token():
    _creds.refresh(google.auth.transport.requests.Request())
    return _creds.token


def build_prompt(word, alt, language, personal_context, conversation_context):
    """One prompt for every turn: weave the SRS word (or its colloquial alt) into a natural,
    idiomatic sentence that fits the learner's life and the recent exchange. Statement or question
    — no '?' required. No turn-type branching; trust the model to connect things naturally."""
    if language == "cantonese":
        word_t = converter.convert(word)  # traditional so output stays traditional
        target = alt if alt else word_t
        alt_note = f"（口語，即係書面語「{word_t}」）" if alt else ""
        recent = f"我哋啱啱傾緊：\n{conversation_context}\n" if conversation_context else ""
        facts = f"我嘅近況：\n{personal_context}\n" if personal_context else ""
        prompt = (f"你幫緊我練廣東話。{recent}{facts}"
                  f"寫一句你想問我或者同我講嘅、自然又地道嘅口語廣東話，句入面一定要用到「{target}」{alt_note}，"
                  f"就算要拗個彎都要扣返我嘅近況同啱啱傾嘅嘢（陳述句或問句都得）。淨係輸出嗰句，用繁體字，唔要jyutping、翻譯或者解釋。")
    else:
        target = word
        recent = f"我们刚在聊：\n{conversation_context}\n" if conversation_context else ""
        facts = f"我的近况：\n{personal_context}\n" if personal_context else ""
        prompt = (f"你在帮我练普通话。{recent}{facts}"
                  f"写一句你想问我或者跟我说的、自然又地道的口语普通话，句子里一定要用到「{word}」，"
                  f"就算要绕个弯也要扣上我的近况和刚聊的内容（陈述句或问句都行）。只输出那一句，不要拼音、翻译或者解释。")
    return prompt, target


def _grok(messages, stream, max_tokens):
    return requests.post(
        _ENDPOINT, stream=stream, timeout=60,
        headers={"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"},
        json={"model": GEN_MODEL, "temperature": 0.7, "max_tokens": max_tokens,
              "messages": messages, "stream": stream})


def _full_text(resp):
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def _iter_deltas(resp):
    resp.raise_for_status()
    for raw in resp.iter_lines():
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
            yield delta


@functions_framework.http
def convo_live_generate_question(request):
    if request.method == "OPTIONS":
        return ("", 204, {**CORS, "Access-Control-Allow-Methods": "POST",
                          "Access-Control-Allow-Headers": "Content-Type", "Access-Control-Max-Age": "3600"})
    try:
        req = request.get_json(silent=True) or {}
        logger.info(f"====== convo_live_generate_question ======\n{json.dumps(req, ensure_ascii=False)}")
        word = req.get("word")
        language = req.get("language", "cantonese")
        if not word:
            return (jsonify({"error": "word required"}), 400, CORS)
        alt = (req.get("alt") or "").strip() or None
        personal_context = (req.get("personalContext") or "").strip()
        conversation_context = (req.get("conversationContext") or "").strip()
        system, target = build_prompt(word, alt, language, personal_context, conversation_context)
        max_tokens = 200
        nudge = "開始。" if language == "cantonese" else "开始。"
        messages = [{"role": "system", "content": system}, {"role": "user", "content": nudge}]
        logger.info(f"word={word} alt={alt} language={language} target={target} "
                    f"pcLen={len(personal_context)} ccLen={len(conversation_context)}")
        logger.info(f"SYSTEM PROMPT:\n{system}")

        # ALT path: must actually contain `alt` -> generate whole, validate, retry, then emit.
        if alt and language == "cantonese":
            text = ""
            for attempt in range(2):  # 1 retry max — a word Grok won't produce won't appear on retry either
                text = _full_text(_grok(messages, stream=False, max_tokens=max_tokens))
                logger.info(f"alt-gen attempt {attempt}: {text}")
                if alt in text:
                    break
            else:
                logger.warning(f"alt '{alt}' not reproduced after retries for word '{word}'; emitting best effort")
            logger.info(f"FINAL (alt path): {text}")

            def gen_alt():
                yield text
            return Response(stream_with_context(gen_alt()), mimetype="text/plain; charset=utf-8",
                            headers=STREAM_HEADERS)

        # DIRECT path: real token streaming.
        def gen_stream():
            collected = []
            try:
                for delta in _iter_deltas(_grok(messages, stream=True, max_tokens=max_tokens)):
                    collected.append(delta)
                    yield delta
            finally:
                logger.info(f"FINAL (stream path): {''.join(collected)}")
        return Response(stream_with_context(gen_stream()), mimetype="text/plain; charset=utf-8",
                        headers=STREAM_HEADERS)
    except Exception as e:  # noqa: BLE001
        logger.error(f"error: {e}\n{traceback.format_exc()}")
        return (jsonify({"error": str(e)}), 500, CORS)
