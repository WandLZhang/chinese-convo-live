# SenseVoice speech-to-text for chinese-convo-live.
#
# A container rather than a buildpack function for two reasons: it needs the ffmpeg binary (browsers
# send webm/opus, sherpa-onnx needs PCM), and the 237 MB model belongs on a read-only image layer —
# on Cloud Run /tmp is tmpfs and would count against the memory limit.
FROM python:3.12-slim

# ffmpeg decodes whatever MediaRecorder produced; bzip2 unpacks the model archive.
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg bzip2 curl \
    && rm -rf /var/lib/apt/lists/*

# Pinned to the exact artifact the benchmark scored, so the deployed model is the benchmarked model.
# (language-benchmarks/tasks/speech-to-text — SenseVoice won real-Cantonese meaning 4.00/5 @ RTF 0.083)
ARG MODEL=sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2025-09-09
RUN curl -sL --retry 3 \
      "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/${MODEL}.tar.bz2" \
      -o /tmp/m.tar.bz2 \
    && mkdir -p /models && tar xjf /tmp/m.tar.bz2 -C /models && rm /tmp/m.tar.bz2
ENV MODEL_DIR=/models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2025-09-09

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py .

# 1 worker: the recogniser is loaded once at import (~1.6 s) and shared; more workers would each hold
# their own copy of the model. Threads handle concurrent requests. Long timeout for slow uploads.
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 120 main:app
