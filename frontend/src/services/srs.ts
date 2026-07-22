import type { Language } from '../types'

/**
 * Pure spaced-repetition classification helpers, ported from the old app's
 * inline App.tsx logic. Kept free of Firestore so they can be unit-tested.
 *
 * A `vocabulary` doc carries per-language state via suffixed fields:
 *   nextReviewMandarin / nextReviewCantonese  (Firestore Timestamp | null)
 *   mastered_mandarin  / mastered_cantonese    (boolean)
 *
 * Derived per-language state:
 *   - mastered:  mastered_<lang> === true              (checked first)
 *   - new:       review field absent  AND not mastered
 *   - scheduled: review field present AND not mastered  (a due word is also scheduled)
 *   - due:       scheduled AND review time <= now
 */

type Data = Record<string, unknown>
type FsTimestamp = { toDate: () => Date }

export function reviewField(language: Language): string {
  return `nextReview${language.charAt(0).toUpperCase()}${language.slice(1)}`
}

export function masteredField(language: Language): string {
  return `mastered_${language}`
}

export function isMastered(data: Data, language: Language): boolean {
  return data[masteredField(language)] === true
}

/** True if the review-time key is present on the doc (even if its value is null). */
export function hasReview(data: Data, language: Language): boolean {
  return reviewField(language) in data
}

/** The review time as a Date, or null if absent/null/not a Timestamp. */
export function getReviewDate(data: Data, language: Language): Date | null {
  const v = data[reviewField(language)] as FsTimestamp | null | undefined
  if (v && typeof v.toDate === 'function') return v.toDate()
  return null
}

export function isNew(data: Data, language: Language): boolean {
  return !hasReview(data, language) && !isMastered(data, language)
}

export function isScheduled(data: Data, language: Language): boolean {
  return hasReview(data, language) && !isMastered(data, language)
}

export function isDue(data: Data, language: Language, now: Date): boolean {
  if (isMastered(data, language)) return false
  const d = getReviewDate(data, language)
  return d !== null && d.getTime() <= now.getTime()
}

/** Minutes (rounded up) from `now` until `reviewDate`. */
export function minutesUntil(reviewDate: Date, now: Date): number {
  return Math.ceil((reviewDate.getTime() - now.getTime()) / 60000)
}
