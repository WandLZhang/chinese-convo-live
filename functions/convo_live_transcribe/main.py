"""
convo_live_transcribe — transcribe a recorded spoken reply into Chinese text.

Powers the mic button. Model: SenseVoice (sherpa-onnx), self-hosted on Cloud Run. Benchmark-selected in
language-benchmarks/tasks/speech-to-text: on REAL Cantonese speech it scored best on meaning (4.00/5 vs
gemini-3.5-flash 3.67, chirp_3 3.75) at RTF 0.083 — roughly 0.4 s for a 5 s utterance, ~8x faster than
the Gemini audio path it replaces.

Known and accepted limitation: SenseVoice garbles English/proper nouns ("Crunchyroll" -> "CRUNCHY ROALD").
The UI drops the transcript into the input for review, so names get fixed by hand before grading. The
upside of a context-free recogniser: it cannot hallucinate the vocabulary word you were supposed to use,
so a transcript can never wrongly satisfy `meaningful_usage` downstream.

Browsers send whatever MediaRecorder produced (usually audio/webm;codecs=opus), so ffmpeg normalises to
16 kHz mono PCM before decoding.
"""
import base64
import logging
import os
import subprocess
import time
import traceback

import numpy as np
import sherpa_onnx
from flask import Flask, jsonify, request

# Explicit INFO handler: a bare logging.basicConfig can be silently disabled by an earlier library
# import, which once hid a truncation bug for days (fixed in 8dcf1bd). Do not rely on basicConfig.
logger = logging.getLogger("transcribe")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setLevel(logging.INFO)
    logger.addHandler(_h)
logger.propagate = False

MODEL_DIR = os.getenv("MODEL_DIR", "/models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2025-09-09")
SAMPLE_RATE = 16000
MAX_AUDIO_BYTES = 10 * 1024 * 1024   # a spoken reply is a few seconds; this is a generous ceiling
MAX_SECONDS = 120                    # ffmpeg guard against a pathological upload

app = Flask(__name__)
CORS = {"Access-Control-Allow-Origin": "*"}


def _load():
    """Load once at import (~1.6 s) and reuse; min-instances=1 keeps it warm."""
    t0 = time.monotonic()
    model = os.path.join(MODEL_DIR, "model.int8.onnx")
    rec = sherpa_onnx.OfflineRecognizer.from_sense_voice(
        model=model, tokens=os.path.join(MODEL_DIR, "tokens.txt"), use_itn=True)
    logger.info(f"SenseVoice loaded from {MODEL_DIR} in {time.monotonic() - t0:.2f}s")
    return rec


_recognizer = _load()


def to_pcm(audio: bytes) -> np.ndarray:
    """Any container/codec -> float32 mono 16 kHz, via ffmpeg on stdin/stdout."""
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-t", str(MAX_SECONDS),
         "-i", "pipe:0", "-ar", str(SAMPLE_RATE), "-ac", "1", "-f", "s16le", "pipe:1"],
        input=audio, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {proc.stderr.decode('utf-8', 'ignore')[:200]}")
    return np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32) / 32768.0


@app.route("/", methods=["POST", "OPTIONS"])
def transcribe():
    if request.method == "OPTIONS":
        return ("", 204, {**CORS, "Access-Control-Allow-Methods": "POST",
                          "Access-Control-Allow-Headers": "Content-Type", "Access-Control-Max-Age": "3600"})
    try:
        req = request.get_json(silent=True) or {}
        audio_b64 = req.get("audio") or ""
        mime = req.get("mimeType", "audio/webm")
        if not audio_b64:
            return (jsonify({"error": "audio required"}), 400, CORS)
        try:
            audio = base64.b64decode(audio_b64)
        except Exception:  # noqa: BLE001
            return (jsonify({"error": "audio must be base64"}), 400, CORS)
        if len(audio) > MAX_AUDIO_BYTES:
            return (jsonify({"error": "audio too large"}), 413, CORS)

        t0 = time.monotonic()
        pcm = to_pcm(audio)
        t_decode = time.monotonic() - t0
        if pcm.size == 0:
            logger.info(f"no audio decoded (mime={mime}, {len(audio)}B)")
            return (jsonify({"text": ""}), 200, CORS)

        t1 = time.monotonic()
        stream = _recognizer.create_stream()
        stream.accept_waveform(SAMPLE_RATE, pcm)
        _recognizer.decode_stream(stream)
        text = stream.result.text.strip()
        t_asr = time.monotonic() - t1

        logger.info(f"mime={mime} bytes={len(audio)} audio={pcm.size / SAMPLE_RATE:.1f}s "
                    f"ffmpeg={t_decode:.2f}s asr={t_asr:.2f}s")
        logger.info(f"TRANSCRIPT: {text!r}")
        return (jsonify({"text": text}), 200, CORS)
    except Exception as e:  # noqa: BLE001
        logger.error(f"error: {e}\n{traceback.format_exc()}")
        return (jsonify({"error": str(e)}), 500, CORS)


@app.route("/health", methods=["GET"])
def health():
    return ("ok", 200)
