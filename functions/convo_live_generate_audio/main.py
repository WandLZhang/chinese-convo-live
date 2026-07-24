"""
convo_live_generate_audio — Cloud TTS Chirp 3 HD.

Benchmark-selected (bench/bench_tts.py): ~0.6s both languages with near-perfect accuracy,
replacing the old Gemini native-audio (4-6s and garbled Cantonese). Returns base64 LINEAR16
WAV to match the client's playAudio (data:audio/wav). Runs as the compute SA (quota -> its own
project, so no x-goog-user-project header needed).
"""
import html
import traceback

import functions_framework
import google.auth
import google.auth.transport.requests
import requests
from flask import jsonify

_creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
CORS = {"Access-Control-Allow-Origin": "*"}

# (languageCode, Chirp 3 HD voice). 30 voices exist per language — swap the name to taste.
VOICE = {
    "cantonese": ("yue-HK", "yue-HK-Chirp3-HD-Enceladus"),  # lower-pitch male
    "mandarin": ("cmn-CN", "cmn-CN-Chirp3-HD-Achernar"),
}


def _token():
    _creds.refresh(google.auth.transport.requests.Request())
    return _creds.token


_BREAK = '<break time="300ms"/>'


def _to_ssml(text: str) -> str:
    """Chirp 3 HD is a fluid model that under-pauses at commas (a plain comma is only a short pause
    it further shrinks by context), so force a clear clause pause with an SSML <break> after each
    comma. SSML <break> is supported on Chirp 3 HD synchronous requests for BOTH cmn-CN and yue-HK
    (the [pause] markup is not — it excludes yue-hk)."""
    s = html.escape(text)  # keep the SSML valid if the text has & < >
    for c in ("，", "、", ","):
        s = s.replace(c, c + _BREAK)
    return f"<speak>{s}</speak>"


@functions_framework.http
def convo_live_generate_audio(request):
    if request.method == "OPTIONS":
        return ("", 204, {**CORS, "Access-Control-Allow-Methods": "POST",
                          "Access-Control-Allow-Headers": "Content-Type", "Access-Control-Max-Age": "3600"})
    try:
        req = request.get_json(silent=True) or {}
        sentence = req.get("sentence")
        language = req.get("language", "cantonese")
        if not sentence:
            return (jsonify({"error": "sentence required"}), 400, CORS)
        lang_code, voice = VOICE.get(language, VOICE["cantonese"])
        r = requests.post(
            "https://texttospeech.googleapis.com/v1/text:synthesize", timeout=30,
            headers={"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"},
            json={"input": {"ssml": _to_ssml(sentence)},
                  "voice": {"languageCode": lang_code, "name": voice},
                  "audioConfig": {"audioEncoding": "LINEAR16"}})
        r.raise_for_status()
        return (jsonify({"audio": r.json()["audioContent"]}), 200, CORS)  # base64 WAV
    except Exception as e:  # noqa: BLE001
        print(traceback.format_exc())
        return (jsonify({"error": str(e)}), 500, CORS)
