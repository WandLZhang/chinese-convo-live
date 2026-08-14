import { appConfig } from './firebase.config'
import type { Language } from '../types'

// Cloud Run service, not a Cloud Function: SenseVoice needs the ffmpeg binary and a 237MB model baked
// into a container image, so it has its own *.run.app URL rather than the cloudfunctions.net base.
const TRANSCRIBE_URL = appConfig.transcribeUrl

function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    // result is a data URL: "data:audio/webm;codecs=opus;base64,AAAA..." — keep only the payload.
    reader.onload = () => resolve(String(reader.result).split(',')[1] ?? '')
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(blob)
  })
}

/**
 * Transcribe a recorded reply (Gemini audio-native, server-side). `question` + `targetWord` bias the
 * model toward this turn's topic and vocabulary, which is what keeps proper nouns and rare words intact.
 */
export async function transcribeAudio(
  blob: Blob,
  language: Language,
  opts: { question?: string; targetWord?: string } = {},
): Promise<string> {
  const audio = await blobToBase64(blob)
  const resp = await fetch(TRANSCRIBE_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      audio,
      mimeType: blob.type || 'audio/webm',
      language,
      question: opts.question ?? '',
      targetWord: opts.targetWord ?? '',
    }),
  })
  if (!resp.ok) {
    const t = await resp.text()
    throw new Error(t || `transcribe failed (${resp.status})`)
  }
  const data = (await resp.json()) as { text?: string; error?: string }
  if (data.error) throw new Error(data.error)
  return (data.text ?? '').trim()
}
