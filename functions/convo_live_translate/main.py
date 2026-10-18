"""
convo_live_translate — stream an English translation of a generated Chinese sentence.

Powers the "eye" reveal in the app. Model: Gemini 3.5 Flash-Lite (Vertex OpenAI-compatible endpoint),
the fastest model serving on 2026-10-18 (first token ~0.5s). It replaced Grok, which Vertex stopped
serving (grok-4.1-fast 404, then grok-4.20-non-reasoning 503). Plain-text streamed output (typewriter
into the bubble). Project from ADC. An upstream error returns 502 with the model's status and body.
"""
import itertools
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
MODEL = "google/gemini-3.5-flash-lite"
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

        resp = requests.post(
            _ENDPOINT, stream=True, timeout=60,
            headers={"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"},
            json={"model": MODEL, "temperature": 0.2, "max_tokens": 200, "stream": True,
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": sentence}]})
        if resp.status_code != 200:
            error = f"{MODEL} returned {resp.status_code}: {resp.text}"
            print(f"translate ({language}) '{sentence}' failed: {error}")
            return (jsonify({"error": error}), 502, CORS)

        def data_lines():
            for raw in resp.iter_lines():
                line = raw.decode("utf-8") if raw else ""
                if line.startswith("data:"):
                    yield line[5:].strip()

        # A streamed failure arrives in-band: HTTP 200, then a data event holding "error". Read the
        # first event before answering so that case returns 502 with the model's message.
        events = data_lines()
        first = next(events, "[DONE]")
        if first.startswith("{") and "error" in json.loads(first):
            error = f"{MODEL} returned an error: {first}"
            print(f"translate ({language}) '{sentence}' failed: {error}")
            return (jsonify({"error": error}), 502, CORS)

        def gen():
            collected = []
            try:
                for data in itertools.chain([first], events):
                    if data == "[DONE]":
                        break
                    try:
                        event = json.loads(data)
                    except Exception:  # noqa: BLE001
                        continue
                    if "error" in event:
                        print(f"translate ({language}) '{sentence}' failed mid-stream: {MODEL} returned an error: {data}")
                        break
                    choices = event.get("choices") or []
                    delta = (choices[0].get("delta") or {}).get("content") if choices else None
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
