"""
convo_live_translate — stream an English translation of a generated Chinese sentence.

Powers the "eye" reveal in the app. Model: Grok 4.1 Fast (Vertex OpenAI-compatible MaaS endpoint) —
benchmark-selected for translation: accurate + fastest warm TTFT (~0.3s), already enabled for
grading, cheap. Plain-text streamed output (typewriter into the bubble). Project from ADC.
"""
import json
import os
import traceback

import functions_framework
import google.auth
import google.auth.transport.requests
import requests
from flask import Response, jsonify, stream_with_context

_creds, _adc_project = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
LLM_PROJECT = os.getenv("PROJECT_ID") or _adc_project
MODEL = "xai/grok-4.1-fast-non-reasoning"
_ENDPOINT = (f"https://aiplatform.googleapis.com/v1/projects/{LLM_PROJECT}"
             "/locations/global/endpoints/openapi/chat/completions")

CORS = {"Access-Control-Allow-Origin": "*"}
STREAM_HEADERS = {**CORS, "X-Accel-Buffering": "no", "Cache-Control": "no-cache"}


def _token():
    _creds.refresh(google.auth.transport.requests.Request())
    return _creds.token


@functions_framework.http
def convo_live_translate(request):
    if request.method == "OPTIONS":
        return ("", 204, {**CORS, "Access-Control-Allow-Methods": "POST",
                          "Access-Control-Allow-Headers": "Content-Type", "Access-Control-Max-Age": "3600"})
    try:
        req = request.get_json(silent=True) or {}
        sentence = (req.get("sentence") or "").strip()
        language = req.get("language", "cantonese")
        if not sentence:
            return (jsonify({"error": "sentence required"}), 400, CORS)
        lang = "Cantonese" if language == "cantonese" else "Mandarin"
        system = (f"Translate the {lang} Chinese sentence into natural, idiomatic English for a "
                  "language learner. Output ONLY the English translation — one line, no notes, no "
                  "quotes, no pinyin or jyutping.")

        def gen():
            collected = []
            try:
                resp = requests.post(
                    _ENDPOINT, stream=True, timeout=60,
                    headers={"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"},
                    json={"model": MODEL, "temperature": 0.2, "max_tokens": 200, "stream": True,
                          "messages": [{"role": "system", "content": system},
                                       {"role": "user", "content": sentence}]})
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
                        collected.append(delta)
                        yield delta
            finally:
                print(f"translate ({language}) '{sentence}' -> {''.join(collected)}")
        return Response(stream_with_context(gen()), mimetype="text/plain; charset=utf-8",
                        headers=STREAM_HEADERS)
    except Exception as e:  # noqa: BLE001
        print(f"error: {e}\n{traceback.format_exc()}")
        return (jsonify({"error": str(e)}), 500, CORS)
