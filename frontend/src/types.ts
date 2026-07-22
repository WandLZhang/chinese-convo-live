export type Language = 'mandarin' | 'cantonese'

/** A Firestore Timestamp-like value. */
export interface FsTimestamp {
  toDate(): Date
  seconds?: number
  nanoseconds?: number
}

export interface VocabEntry {
  id: string
  simplified: string // the vocab word (simplified Chinese)
  mandarin: string // example sentence, simplified Mandarin
  cantonese: string // example sentence, colloquial Cantonese (traditional)
  /** Precomputed colloquial word to use instead of `simplified` (Cantonese). Set by the
   *  audit only where Words.hk attests an alternative (~2% of vocab); absent = use the word. */
  alt?: string
  timestamp?: FsTimestamp
  nextReviewMandarin?: FsTimestamp | null
  nextReviewCantonese?: FsTimestamp | null
  mastered_mandarin?: boolean
  mastered_cantonese?: boolean
  // Per-language fields are also read dynamically (e.g. `nextReview${Lang}`).
  [key: string]: unknown
}

export interface QuestionData {
  question: string
  word: string
  language: Language
  requires_alternative: boolean
  target_word: string
  audio?: string // base64 WAV, generated separately via generate_audio_live
  audioLoading?: boolean
}

export interface Evaluation {
  fluent: boolean
  meaningful_usage: boolean
  romanization: string
  improved_answer?: string
  feedback: string
}
