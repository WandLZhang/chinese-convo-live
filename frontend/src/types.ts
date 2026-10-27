export type Language = 'mandarin' | 'cantonese'

/** A Firestore Timestamp-like value. */
export interface FsTimestamp {
  toDate(): Date
  seconds?: number
  nanoseconds?: number
}

/** A word's Anki SM-2 card for one language, written by the grading function (srs.py). */
export interface SrsCard {
  state: 'new' | 'learning' | 'review' | 'relearning'
  step: number
  ivl: number // days
  ease: number
  reps: number
  lapses: number
  last?: FsTimestamp
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
  /** Absent on words the old fixed-interval scheduler handled; those count as review cards. */
  srsMandarin?: SrsCard
  srsCantonese?: SrsCard
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
  improved_answer?: string
  feedback: string
}
