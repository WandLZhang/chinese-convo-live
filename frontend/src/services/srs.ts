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

// ---- Anki queue order -------------------------------------------------------------------------
// The grading function (functions/convo_live_evaluate_answer/srs.py) keeps an Anki SM-2 card per
// language in `srs<Lang>`. These helpers pick the next word the way AnkiDroid does.

/** Anki's "Learn ahead limit": with nothing else left, show a learning word due this soon. */
export const LEARN_AHEAD_MIN = 20
/** Anki's "Next day starts at". Must match DAY_STARTS_HOUR in srs.py. */
export const DAY_STARTS_HOUR = 4

export function srsField(language: Language): string {
  return `srs${language.charAt(0).toUpperCase()}${language.slice(1)}`
}

/** In the minutes-scale learning steps (new word, or a failed one being relearned). A word with no
 *  card was scheduled by the old fixed-interval code and counts as a review word. */
export function isLearning(data: Data, language: Language): boolean {
  const card = data[srsField(language)] as { state?: string } | undefined
  return card?.state === 'learning' || card?.state === 'relearning'
}

function byDue<T>(dataOf: (d: T) => Data, language: Language) {
  return (a: T, b: T) =>
    (getReviewDate(dataOf(a), language)?.getTime() ?? 0) -
    (getReviewDate(dataOf(b), language)?.getTime() ?? 0)
}

/**
 * The next due word, in AnkiDroid's order: a learning word that has fallen due goes to the front,
 * earliest first; then review words, oldest due first, so a long-overdue word isn't starved by
 * yesterday's. null when nothing is due.
 */
export function pickNext<T>(docs: T[], dataOf: (d: T) => Data, language: Language, now: Date): T | null {
  const due = docs.filter((d) => isDue(dataOf(d), language, now)).sort(byDue(dataOf, language))
  return due.find((d) => isLearning(dataOf(d), language)) ?? due[0] ?? null
}

/** A learning word due within LEARN_AHEAD_MIN, earliest first, so a 10-minute step doesn't strand
 *  you on a wait message when nothing else is left. */
export function pickLearnAhead<T>(
  docs: T[],
  dataOf: (d: T) => Data,
  language: Language,
  now: Date,
): T | null {
  const limit = now.getTime() + LEARN_AHEAD_MIN * 60000
  return (
    docs
      .filter((d) => {
        const data = dataOf(d)
        const t = getReviewDate(data, language)?.getTime()
        return t !== undefined && t > now.getTime() && t <= limit &&
          !isMastered(data, language) && isLearning(data, language)
      })
      .sort(byDue(dataOf, language))[0] ?? null
  )
}

/** The Anki day a moment falls on (local calendar day, starting at DAY_STARTS_HOUR), as a day count. */
function ankiDay(t: Date): number {
  const shifted = new Date(t.getTime() - DAY_STARTS_HOUR * 3600000)
  return Math.floor(
    Date.UTC(shifted.getFullYear(), shifted.getMonth(), shifted.getDate()) / 86400000,
  )
}

/** How far off a due time is, the way Anki labels it: "in 10 min", "in 5 h", "in 3 days". */
export function relativeDue(due: Date, now: Date): string {
  const min = Math.ceil((due.getTime() - now.getTime()) / 60000)
  if (min <= 0) return 'now'
  if (min < 60) return `in ${min} min`
  const days = ankiDay(due) - ankiDay(now)
  if (days >= 1) return days === 1 ? 'in 1 day' : `in ${days} days`
  return `in ${Math.round(min / 60)} h`
}
