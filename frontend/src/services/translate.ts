import { functionBase } from './firebase'
import type { Language } from '../types'

const TRANSLATE_URL = `${functionBase}/convo_live_translate`

/**
 * Stream an English translation of a Chinese sentence (Grok, benchmark-selected). `onDelta` gets
 * the accumulated text so far (typewriter). Resolves with the full translation.
 */
export async function translateSentence(
  sentence: string,
  language: Language,
  onDelta: (full: string) => void,
): Promise<string> {
  const resp = await fetch(TRANSLATE_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sentence, language }),
  })
  if (!resp.ok || !resp.body) {
    const t = await resp.text()
    throw new Error(t || `translate failed (${resp.status})`)
  }
  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let full = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    full += decoder.decode(value, { stream: true })
    onDelta(full)
  }
  return full
}
