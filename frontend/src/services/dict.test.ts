import { describe, it, expect } from 'vitest'
import { hitsWord, type RawEntry } from './dict'

// Entries copied verbatim from the live blob (storage.googleapis.com/wz-canto-dict/canto-dict.min.json).
// The blob keys each word under both scripts with identical entries; 发 holds both 發 and 髮.
const SEND = {
  d: ['to send out', "to show (one's feeling)", 'to issue', 'to develop', 'to make a bundle of money',
    'classifier for gunshots (rounds)', 'rise or expand when fermented or soaked (food)',
    'to prosper or become rich', 'the sound of fish diving', ' # adapted from cc-cedict', 'to emit',
    'to dispatch', 'to launch', 'to generate', 'to transmit', 'to produce', 'to trigger off',
    'to expose', 'to discover', 'to prosper', 'to turn into'],
  jy: 'faat3',
  py: 'fa1',
}
const HAIR = { d: ['hair', 'Taiwan pr. [fa3]', 'Taiwan pr. [fǎ]', ' # adapted from cc-cedict'], jy: 'faat3', py: 'fa4' }
const AWKWARD = { d: ['awkward; embarrassed'], jy: 'gaam3 gaai3', py: 'gan1 ga4' }
const DICT: Record<string, RawEntry[]> = {
  尴尬: [AWKWARD],
  尷尬: [AWKWARD],
  发: [SEND, HAIR],
  發: [SEND],
  髮: [HAIR],
}

describe('hitsWord (does a tap land on the target word?)', () => {
  const s = '我好尷尬呀' // traditional, as a Cantonese question is written

  it('matches a simplified target inside a traditional sentence', () => {
    expect(hitsWord(s, 2, '尴尬', DICT)).toBe(true)
  })

  it('counts a tap on the second character of the target', () => {
    expect(hitsWord(s, 3, '尴尬', DICT)).toBe(true)
  })

  it('ignores a tap on some other word in the sentence', () => {
    expect(hitsWord(s, 0, '尴尬', DICT)).toBe(false)
    expect(hitsWord(s, 4, '尴尬', DICT)).toBe(false)
  })

  it('matches a verbatim target (an alt, or a Mandarin sentence) with no dictionary help', () => {
    expect(hitsWord('佢眼紅我升職', 2, '眼紅', {})).toBe(true)
    expect(hitsWord('佢眼紅我升職', 0, '眼紅', {})).toBe(false)
  })

  it('handles a simplified character that stands for two traditional ones', () => {
    expect(hitsWord('剪髮', 1, '发', DICT)).toBe(true)
    expect(hitsWord('發財', 0, '发', DICT)).toBe(true)
  })

  it('returns false for an empty target or an out-of-range tap', () => {
    expect(hitsWord(s, 2, '', DICT)).toBe(false)
    expect(hitsWord(s, 99, '尴尬', DICT)).toBe(false)
  })
})
