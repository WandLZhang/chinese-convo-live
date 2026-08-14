import { useCallback, useRef, useState } from 'react'

// Preference order: Chrome/Android gives webm+opus; Safari/iOS only mp4 (AAC). Gemini accepts all of
// these inline, so we send whatever the browser actually produced rather than transcoding.
const TYPES = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus']

function pickMimeType(): string | undefined {
  if (typeof MediaRecorder === 'undefined') return undefined
  return TYPES.find((t) => MediaRecorder.isTypeSupported(t))
}

export interface Recorder {
  recording: boolean
  supported: boolean
  error: string | null
  start: () => Promise<void>
  /** Stop and resolve the recorded audio (null if nothing was captured). */
  stop: () => Promise<Blob | null>
  /** Stop and discard — no blob, mic released. */
  cancel: () => void
}

/**
 * Minimal MediaRecorder wrapper for short spoken replies. Always releases the mic track on stop —
 * a leaked track keeps the browser's recording indicator on and holds the mic from other apps.
 */
export function useRecorder(): Recorder {
  const [recording, setRecording] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const recRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<BlobPart[]>([])
  const streamRef = useRef<MediaStream | null>(null)

  const release = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop())
    streamRef.current = null
    recRef.current = null
  }, [])

  const start = useCallback(async () => {
    setError(null)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const mimeType = pickMimeType()
      const rec = new MediaRecorder(stream, mimeType ? { mimeType } : undefined)
      chunksRef.current = []
      rec.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) chunksRef.current.push(e.data)
      }
      streamRef.current = stream
      recRef.current = rec
      rec.start()
      setRecording(true)
    } catch (err) {
      console.error('[recorder] start failed:', err)
      setError(err instanceof Error ? err.message : 'microphone unavailable')
      release()
      setRecording(false)
    }
  }, [release])

  const stop = useCallback(async () => {
    const rec = recRef.current
    if (!rec) {
      setRecording(false)
      return null
    }
    const type = rec.mimeType || 'audio/webm'
    const blob = await new Promise<Blob | null>((resolve) => {
      rec.onstop = () => {
        const parts = chunksRef.current
        resolve(parts.length ? new Blob(parts, { type }) : null)
      }
      try {
        rec.stop()
      } catch {
        resolve(null)
      }
    })
    release()
    setRecording(false)
    chunksRef.current = []
    return blob
  }, [release])

  const cancel = useCallback(() => {
    const rec = recRef.current
    if (rec) {
      rec.onstop = null
      try {
        rec.stop()
      } catch {
        /* already stopped */
      }
    }
    chunksRef.current = []
    release()
    setRecording(false)
  }, [release])

  return {
    recording,
    supported: typeof MediaRecorder !== 'undefined' && !!navigator.mediaDevices,
    error,
    start,
    stop,
    cancel,
  }
}
