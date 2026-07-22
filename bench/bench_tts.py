"""
Benchmark TTS for chinese-convo-live — latency + accuracy, both languages.

Engines: Chirp 3 HD, Standard (Cloud TTS), Gemini native-audio (current generate_audio_live).
Latency = total synth time (app pre-generates audio, so total matters more than TTFB).
Accuracy = round-trip STT: synthesize -> transcribe (Cloud STT) -> normalized char similarity
           (catches mangled tones / colloquial chars without a human listening to all of them).
Saves .wav samples per engine/language for ear-checking the finalists.

Run: source bench/.venv/bin/activate && python bench/bench_tts.py
"""
import base64
import difflib
import io
import os
import statistics
import time
import wave
from collections import defaultdict

import google.auth
import google.auth.transport.requests
import opencc
import requests

PROJECT = os.getenv("PROJECT_ID", "your-gcp-project")
_creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
_t2s = opencc.OpenCC("t2s")
OUT = "bench/results/tts"
os.makedirs(OUT, exist_ok=True)

CANTO = ["你今日食咗早餐未呀？", "你覺得個計劃好唔好呀？", "你想搵邊個傾吓偈呀？", "呢間酒店啲設施係咪一應俱全㗎？"]
MANDA = ["你周末打算做什么？", "你觉得学中文难吗？", "你最近工作忙吗？", "你去过北京吗？"]


def _hdr():
    _creds.refresh(google.auth.transport.requests.Request())
    return {"Authorization": f"Bearer {_creds.token}", "Content-Type": "application/json",
            "x-goog-user-project": PROJECT}


def cloud_tts(text, voice, langcode):
    body = {"input": {"text": text}, "voice": {"languageCode": langcode, "name": voice},
            "audioConfig": {"audioEncoding": "LINEAR16"}}
    t0 = time.time()
    r = requests.post("https://texttospeech.googleapis.com/v1/text:synthesize", headers=_hdr(), json=body, timeout=60)
    lat = time.time() - t0
    r.raise_for_status()
    return base64.b64decode(r.json()["audioContent"]), lat


def gemini_tts(text, language):
    # Legacy Gemini native-audio TTS baseline (the old app's function), used only for the
    # side-by-side comparison. Set LEGACY_TTS_URL to your own to include this arm; else skip it.
    t0 = time.time()
    r = requests.post(os.getenv("LEGACY_TTS_URL", ""),
                      json={"sentence": text, "language": language}, timeout=90)
    lat = time.time() - t0
    r.raise_for_status()
    return base64.b64decode(r.json()["audio"]), lat


def stt(wav_bytes, stt_lang):
    wf = wave.open(io.BytesIO(wav_bytes), "rb")
    rate, chans = wf.getframerate(), wf.getnchannels()
    pcm = wf.readframes(wf.getnframes())
    body = {"config": {"encoding": "LINEAR16", "sampleRateHertz": rate, "languageCode": stt_lang,
                       "audioChannelCount": chans},
            "audio": {"content": base64.b64encode(pcm).decode()}}
    r = requests.post("https://speech.googleapis.com/v1/speech:recognize", headers=_hdr(), json=body, timeout=60)
    if r.status_code != 200:
        return ""
    parts = []
    for res in r.json().get("results", []):
        alts = res.get("alternatives", [])
        if alts and alts[0].get("transcript"):
            parts.append(alts[0]["transcript"])
    return "".join(parts)


def _norm(s):
    return "".join(c for c in _t2s.convert(s) if "一" <= c <= "鿿")


def sim(a, b):
    return difflib.SequenceMatcher(None, _norm(a), _norm(b)).ratio()


ENGINES = [
    ("chirp3-hd", lambda t, lang, lc: cloud_tts(t, f"{lc}-Chirp3-HD-Achernar", lc)),
    ("standard", lambda t, lang, lc: cloud_tts(t, f"{lc}-Standard-A", lc)),
    ("gemini-native", lambda t, lang, lc: gemini_tts(t, lang)),
]
LANGS = [("cantonese", "yue-HK", "yue-Hant-HK", CANTO), ("mandarin", "cmn-CN", "cmn-Hans-CN", MANDA)]


def main():
    rows = []
    for lang, lc, stt_lang, sents in LANGS:
        for ename, fn in ENGINES:
            for i, s in enumerate(sents):
                try:
                    audio, lat = fn(s, lang, lc)
                    trans = stt(audio, stt_lang)
                    acc = sim(s, trans)
                    with open(f"{OUT}/{lang}_{ename}_{i}.wav", "wb") as f:
                        f.write(audio)
                    rows.append({"lang": lang, "engine": ename, "lat": round(lat, 2), "acc": round(acc, 2)})
                    print(f"{lang[:4]} {ename:14} lat={lat:4.2f}s acc={acc:.2f}  stt={trans[:26]}", flush=True)
                except Exception as e:  # noqa: BLE001
                    print(f"{lang[:4]} {ename:14} ERROR {str(e)[:90]}", flush=True)
                    rows.append({"lang": lang, "engine": ename, "error": str(e)[:150]})

    print("\n=== SUMMARY (engine x lang: p50 latency | mean STT accuracy | n) ===")
    agg = defaultdict(list)
    for r in rows:
        if "lat" in r:
            agg[(r["lang"], r["engine"])].append(r)
    for k in sorted(agg):
        rs = agg[k]
        lat = sorted(x["lat"] for x in rs)[len(rs) // 2]
        acc = statistics.mean(x["acc"] for x in rs)
        print(f"  {k[0]:9} {k[1]:14} p50={lat:.2f}s  acc={acc:.2f}  n={len(rs)}")
    print(f"\nwav samples in {OUT}/")


if __name__ == "__main__":
    main()
