import type { Language } from '../types'
import { functionBase } from './firebase'

const GENERATE_QUESTION_URL = `${functionBase}/convo_live_generate_question`
// TTS: Cloud TTS Chirp 3 HD (benchmark-selected; ~0.6s, replaced Gemini native-audio).
const GENERATE_AUDIO_URL = `${functionBase}/convo_live_generate_audio`

export interface QuestionResponse {
  question: string
  requires_alternative: boolean
  target_word: string
}

export interface AudioResponse {
  audio: string // base64-encoded WAV
}

export interface GenerateQuestionParams {
  word: string
  /** Precomputed colloquial alternative from Firestore (`alt`). When set (Cantonese), the
   *  question uses this word instead of `word`; absent = use the word directly. */
  alt?: string | null
  language: Language
  /** Recent exchange (previous question + learner reply) for a natural bridge. */
  conversationContext?: string
  /** A short personal-context seed; when set on an opener, flavors the question. */
  personalContext?: string
  /** True only for the conversation's opening turn (gates personalization). */
  isOpener?: boolean
  /** Called for each streamed chunk with (chunk, fullSoFar) — drives the live typewriter. */
  onDelta?: (chunk: string, full: string) => void
}

export async function generateQuestion(
  params: GenerateQuestionParams,
): Promise<QuestionResponse> {
  const {
    word,
    alt = null,
    language,
    conversationContext = '',
    personalContext = '',
    isOpener = false,
    onDelta,
  } = params
  const body = { word, alt, language, conversationContext, personalContext, isOpener }
  console.log('[generateQuestion] request payload:', body)

  const response = await fetch(GENERATE_QUESTION_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok || !response.body) {
    throw new Error(
      `Failed to generate question: ${response.status} ${response.statusText}`,
    )
  }

  // The function streams plain question text — real Claude (Sonnet 5) tokens for the direct case, or the
  // whole validated sentence for the alt case. Assemble it, surfacing chunks for a typewriter.
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let full = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    const chunk = decoder.decode(value, { stream: true })
    if (chunk) {
      full += chunk
      onDelta?.(chunk, full)
    }
  }
  full = full.trim()

  // Metadata is derived client-side: the client already knows `alt` from the Firestore doc,
  // so the function no longer returns requires_alternative/target_word.
  const usesAlt = language === 'cantonese' && !!alt
  const result: QuestionResponse = {
    question: full,
    requires_alternative: usesAlt,
    target_word: usesAlt ? (alt as string) : word,
  }
  console.log('[generateQuestion] assembled:', result)
  return result
}

export async function generateAudio(
  sentence: string,
  language: Language,
): Promise<AudioResponse> {
  console.log('[generateAudio] request:', { sentence, language })
  const response = await fetch(GENERATE_AUDIO_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sentence, language }),
  })
  if (!response.ok) {
    throw new Error(
      `Failed to generate audio: ${response.status} ${response.statusText}`,
    )
  }
  const data = (await response.json()) as AudioResponse
  console.log('[generateAudio] response bytes:', data.audio?.length ?? 0)
  return data
}

export function playAudio(base64Audio: string): Promise<void> {
  const audio = new Audio(`data:audio/wav;base64,${base64Audio}`)
  return audio.play()
}
