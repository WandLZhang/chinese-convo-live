import { describe, it, expect } from 'vitest'
import {
  reviewField,
  masteredField,
  hasReview,
  getReviewDate,
  isNew,
  isScheduled,
  isDue,
  isMastered,
  minutesUntil,
  isLearning,
  pickNext,
  pickLearnAhead,
  relativeDue,
} from './srs'

const ts = (d: Date) => ({ toDate: () => d })

describe('field-name derivation', () => {
  it('derives the per-language review field', () => {
    expect(reviewField('mandarin')).toBe('nextReviewMandarin')
    expect(reviewField('cantonese')).toBe('nextReviewCantonese')
  })
  it('derives the per-language mastered field', () => {
    expect(masteredField('mandarin')).toBe('mastered_mandarin')
    expect(masteredField('cantonese')).toBe('mastered_cantonese')
  })
})

describe('classification', () => {
  const now = new Date('2026-07-21T12:00:00Z')
  const past = new Date('2026-07-21T11:00:00Z')
  const future = new Date('2026-07-21T13:00:00Z')

  it('a doc with no review field and not mastered is new', () => {
    const data = { simplified: '出路' }
    expect(isNew(data, 'mandarin')).toBe(true)
    expect(isScheduled(data, 'mandarin')).toBe(false)
    expect(isMastered(data, 'mandarin')).toBe(false)
  })

  it('a doc with a future review time is scheduled but not due', () => {
    const data = { nextReviewMandarin: ts(future) }
    expect(isScheduled(data, 'mandarin')).toBe(true)
    expect(isDue(data, 'mandarin', now)).toBe(false)
    expect(isNew(data, 'mandarin')).toBe(false)
  })

  it('a doc with a past review time is due', () => {
    const data = { nextReviewMandarin: ts(past) }
    expect(isDue(data, 'mandarin', now)).toBe(true)
    expect(isScheduled(data, 'mandarin')).toBe(true)
  })

  it('a mastered doc is mastered regardless of review field, and never due/new/scheduled', () => {
    const data = { nextReviewMandarin: ts(past), mastered_mandarin: true }
    expect(isMastered(data, 'mandarin')).toBe(true)
    expect(isDue(data, 'mandarin', now)).toBe(false)
    expect(isScheduled(data, 'mandarin')).toBe(false)
    expect(isNew(data, 'mandarin')).toBe(false)
  })

  it('keeps the two languages independent', () => {
    const data = { nextReviewCantonese: ts(past) }
    expect(isNew(data, 'mandarin')).toBe(true)
    expect(isDue(data, 'cantonese', now)).toBe(true)
  })

  it('treats a present-but-null review field as scheduled-without-a-time (not due, not new)', () => {
    const data = { nextReviewMandarin: null }
    expect(hasReview(data, 'mandarin')).toBe(true)
    expect(isScheduled(data, 'mandarin')).toBe(true)
    expect(isDue(data, 'mandarin', now)).toBe(false)
    expect(isNew(data, 'mandarin')).toBe(false)
    expect(getReviewDate(data, 'mandarin')).toBeNull()
  })
})

describe('minutesUntil', () => {
  it('rounds up the minutes until the next review', () => {
    const now = new Date('2026-07-21T12:00:00Z')
    const in90s = new Date('2026-07-21T12:01:30Z')
    expect(minutesUntil(in90s, now)).toBe(2)
  })
})

type Doc = { id: string; data: Record<string, unknown> }
const dataOf = (d: Doc) => d.data
const due = (iso: string, card?: Record<string, unknown>) => ({
  nextReviewCantonese: ts(new Date(iso)),
  ...(card ? { srsCantonese: card } : {}),
})

describe('pickNext (AnkiDroid queue order)', () => {
  const now = new Date('2026-10-27T12:00:00Z')

  it('puts a learning word that just fell due ahead of a review overdue for months', () => {
    const docs: Doc[] = [
      { id: 'overdue-268d', data: due('2026-02-01T09:00:00Z') },
      { id: 'failed-just-now', data: due('2026-10-27T11:59:00Z', { state: 'relearning' }) },
    ]
    expect(pickNext(docs, dataOf, 'cantonese', now)?.id).toBe('failed-just-now')
  })

  it('serves review words oldest due first, so a long-overdue word is not starved', () => {
    const docs: Doc[] = [
      { id: 'yesterday', data: due('2026-10-26T08:00:00Z', { state: 'review' }) },
      { id: 'february', data: due('2026-02-01T09:00:00Z') },
      { id: 'september', data: due('2026-09-01T08:00:00Z', { state: 'review' }) },
    ]
    expect(pickNext(docs, dataOf, 'cantonese', now)?.id).toBe('february')
  })

  it('serves the earliest-due learning word first', () => {
    const docs: Doc[] = [
      { id: 'later', data: due('2026-10-27T11:58:00Z', { state: 'learning' }) },
      { id: 'earlier', data: due('2026-10-27T11:50:00Z', { state: 'learning' }) },
    ]
    expect(pickNext(docs, dataOf, 'cantonese', now)?.id).toBe('earlier')
  })

  it('returns null when nothing is due (not-yet-due and mastered words are skipped)', () => {
    const docs: Doc[] = [
      { id: 'in-5-min', data: due('2026-10-27T12:05:00Z', { state: 'learning' }) },
      { id: 'mastered', data: { ...due('2026-10-01T08:00:00Z'), mastered_cantonese: true } },
    ]
    expect(pickNext(docs, dataOf, 'cantonese', now)).toBeNull()
  })

  it('counts a word with no card (scheduled by the old code) as a review word', () => {
    expect(isLearning(due('2026-10-01T08:00:00Z'), 'cantonese')).toBe(false)
    expect(isLearning(due('2026-10-01T08:00:00Z', { state: 'learning' }), 'cantonese')).toBe(true)
  })
})

describe('pickLearnAhead', () => {
  const now = new Date('2026-10-27T12:00:00Z')

  it('picks a learning word due within 20 minutes', () => {
    const docs: Doc[] = [{ id: 'in-8-min', data: due('2026-10-27T12:08:00Z', { state: 'learning' }) }]
    expect(pickLearnAhead(docs, dataOf, 'cantonese', now)?.id).toBe('in-8-min')
  })

  it('ignores a learning word due in 25 minutes and a review word due in 5', () => {
    const docs: Doc[] = [
      { id: 'in-25-min', data: due('2026-10-27T12:25:00Z', { state: 'learning' }) },
      { id: 'review-in-5', data: due('2026-10-27T12:05:00Z', { state: 'review' }) },
    ]
    expect(pickLearnAhead(docs, dataOf, 'cantonese', now)).toBeNull()
  })
})

describe('relativeDue (local time, day starts at 4 AM)', () => {
  it('labels learning steps in minutes', () => {
    const now = new Date(2026, 9, 27, 7, 0)
    expect(relativeDue(new Date(2026, 9, 27, 7, 10), now)).toBe('in 10 min')
  })

  it('labels a same-day time in hours', () => {
    const now = new Date(2026, 9, 27, 9, 0)
    expect(relativeDue(new Date(2026, 9, 27, 14, 0), now)).toBe('in 5 h')
  })

  it('calls tomorrow 4 AM "in 1 day" from 7 PM', () => {
    const now = new Date(2026, 9, 27, 19, 0)
    expect(relativeDue(new Date(2026, 9, 28, 4, 0), now)).toBe('in 1 day')
  })

  it('counts days by the 4 AM day', () => {
    const now = new Date(2026, 9, 27, 19, 0)
    expect(relativeDue(new Date(2026, 9, 30, 4, 0), now)).toBe('in 3 days')
  })

  it('keeps a 10-minute step across 4 AM in minutes', () => {
    const now = new Date(2026, 9, 28, 3, 55)
    expect(relativeDue(new Date(2026, 9, 28, 4, 5), now)).toBe('in 10 min')
  })

  it('says "now" for a time already past', () => {
    const now = new Date(2026, 9, 27, 7, 0)
    expect(relativeDue(new Date(2026, 9, 27, 6, 0), now)).toBe('now')
  })
})
