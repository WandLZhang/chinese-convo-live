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
