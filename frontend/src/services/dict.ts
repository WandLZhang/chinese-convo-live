import type { Language } from '../types'

// Public jyutping+pinyin dictionary (CC-CEDICT + CC-Canto, ~230k entries), keyed by word
// (traditional + simplified). Same blob used by subtitle-everything / lockscreen-translate.
const DICT_URL = 'https://storage.googleapis.com/wz-qwen-test-canto-dict/canto-dict.min.json'

interface RawEntry {
  d: string[] // definitions
  jy: string // jyutping
  py: string // pinyin
}

export interface ReadingSeg {
  text: string // one syllable — pinyin with a tone mark (Mandarin) or numbered jyutping (Cantonese)
  color: string // tone colour
}

export interface Lookup {
  word: string
  reading: ReadingSeg[]
  def: string
}

let dictPromise: Promise<Record<string, RawEntry[]>> | null = null

/** Lazy-load the ~7MB dict once per session (only on first tap). Cached in memory. */
function loadDict(): Promise<Record<string, RawEntry[]>> {
  if (!dictPromise) {
    dictPromise = fetch(DICT_URL)
      .then((r) => r.json())
      .then((j) => (j.entries ?? {}) as Record<string, RawEntry[]>)
      .catch((err) => {
        dictPromise = null // allow retry on next tap
        throw err
      })
  }
  return dictPromise
}

// A CJK ideograph is worth making tappable. Char-code range check (no regex — parsing is for LLMs).
export function isCjk(ch: string): boolean {
  const c = ch.charCodeAt(0)
  return (c >= 0x3400 && c <= 0x9fff) || (c >= 0xf900 && c <= 0xfaff)
}

// Tone colour by trailing digit (matches lockscreen-translate): 1-4 pinyin, 1-6 jyutping, 5 neutral.
const TONE_COLORS: Record<string, string> = {
  '1': '#e15a5a', '2': '#e6a13a', '3': '#3fae4f', '4': '#5a8fe1', '5': '#b06fe0', '6': '#9aa0a6',
}
function toneColor(syl: string): string {
  return TONE_COLORS[syl.trim().slice(-1)] || '#dfe3ea'
}

// Numbered Mandarin pinyin -> tone marks (jian3 -> jiǎn). Standard vowel placement, no regex.
// Ported from lockscreen-translate (render.html pyDiacritic).
const TONE_MARKS: Record<string, string> = {
  a: 'āáǎà', e: 'ēéěè', i: 'īíǐì', o: 'ōóǒò', u: 'ūúǔù', 'ü': 'ǖǘǚǜ',
}
function pyDiacritic(syl: string): string {
  if (!syl) return syl
  let s = syl.toLowerCase()
  let tone = 0
  const last = s.charAt(s.length - 1)
  if (last >= '1' && last <= '5') {
    tone = Number(last)
    s = s.slice(0, -1)
  }
  if (s.includes('u:')) s = s.replace('u:', 'ü')
  if (s.includes('v')) s = s.replace('v', 'ü')
  if (!tone || tone === 5) return s // neutral tone: no mark
  const vowels = 'aeiouü'
  let idx = -1
  if (s.includes('a')) idx = s.indexOf('a') // a wins
  else if (s.includes('e')) idx = s.indexOf('e') // then e
  else if (s.includes('ou')) idx = s.indexOf('o') // ou -> o
  else {
    for (let i = s.length - 1; i >= 0; i--) {
      if (vowels.includes(s.charAt(i))) {
        idx = i
        break
      }
    }
  }
  if (idx < 0) return s
  const mk = TONE_MARKS[s.charAt(idx)]
  return mk ? s.slice(0, idx) + mk.charAt(tone - 1) + s.slice(idx + 1) : s
}

/** Per-syllable reading: pinyin with tone marks (Mandarin) or numbered jyutping (Cantonese),
 *  each syllable coloured by its tone. Falls back to the other script if the preferred is empty. */
function readingOf(e: RawEntry, language: Language): ReadingSeg[] {
  let src: string
  let isPinyin: boolean
  if (language === 'cantonese') {
    if (e.jy) {
      src = e.jy
      isPinyin = false
    } else {
      src = e.py
      isPinyin = true
    }
  } else {
    if (e.py) {
      src = e.py
      isPinyin = true
    } else {
      src = e.jy
      isPinyin = false
    }
  }
  return (src || '')
    .split(' ')
    .filter(Boolean)
    .map((s) => ({ text: isPinyin ? pyDiacritic(s) : s, color: toneColor(s) }))
}

const MAX_WORD = 6 // forward-maximum-matching window

/**
 * Forward-maximum-match at position `i` in `sentence`: return the longest word starting there that
 * the dictionary knows, with its romanization (jyutping for Cantonese, pinyin for Mandarin) and
 * glued definitions. null if nothing matches (e.g. the char isn't a headword).
 */
export async function lookupAt(
  sentence: string,
  i: number,
  language: Language,
): Promise<Lookup | null> {
  const dict = await loadDict()
  const maxK = Math.min(MAX_WORD, sentence.length - i)
  for (let k = maxK; k >= 1; k--) {
    const word = sentence.slice(i, i + k)
    const arr = dict[word]
    if (arr && arr.length) {
      const e = arr[0]
      return { word, reading: readingOf(e, language), def: (e.d || []).join('; ') }
    }
  }
  return null
}
