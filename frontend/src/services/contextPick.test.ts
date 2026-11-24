import { describe, it, expect } from 'vitest'
import { chooseEntries, QUOTE_REST_MS } from './contextPick'

type E = { id: string; used: number }
const usedAt = (e: E) => e.used
const now = 10 * QUOTE_REST_MS
const hour = 3600 * 1000
const first = () => 0 // deterministic: keeps the least-used order

describe('chooseEntries (which message feeds the next sentence)', () => {
  it('picks a never-used quote over the summaries', () => {
    const quoted = [{ id: 'quote', used: 0 }]
    const summaries = [{ id: 'summary', used: 0 }]
    expect(chooseEntries(quoted, summaries, usedAt, now, 1, first).map((e) => e.id)).toEqual(['quote'])
  })

  it('rests a quote used an hour ago, so a summary leads instead of the same message again', () => {
    const quoted = [{ id: 'quote', used: now - hour }]
    const summaries = [{ id: 'summary', used: 0 }]
    expect(chooseEntries(quoted, summaries, usedAt, now, 1, first).map((e) => e.id)).toEqual(['summary'])
  })

  it('brings a quote back once it has rested a day', () => {
    const quoted = [{ id: 'quote', used: now - QUOTE_REST_MS - hour }]
    const summaries = [{ id: 'summary', used: 0 }]
    expect(chooseEntries(quoted, summaries, usedAt, now, 1, first).map((e) => e.id)).toEqual(['quote'])
  })

  it('prefers the rested quote over a resting one', () => {
    const quoted = [
      { id: 'used-an-hour-ago', used: now - hour },
      { id: 'never-used', used: 0 },
    ]
    expect(chooseEntries(quoted, [], usedAt, now, 1, first).map((e) => e.id)).toEqual(['never-used'])
  })

  it('reuses the least recently used quote when every quote is resting and no summaries are left', () => {
    const quoted = [
      { id: 'an-hour-ago', used: now - hour },
      { id: 'three-hours-ago', used: now - 3 * hour },
    ]
    expect(chooseEntries(quoted, [], usedAt, now, 1, first).map((e) => e.id)).toEqual(['three-hours-ago'])
  })

  it('returns nothing when there are no entries at all', () => {
    expect(chooseEntries([], [], usedAt, now, 1, first)).toEqual([])
  })
})
