import type { Language } from '../types'

// Public jyutping+pinyin dictionary (CC-CEDICT + CC-Canto, ~230k entries), keyed by word
// (traditional + simplified). Same blob used by subtitle-everything / lockscreen-translate.
const DICT_URL = 'https://storage.googleapis.com/wz-qwen-test-canto-dict/canto-dict.min.json'

interface RawEntry {
  d: string[] // definitions
  jy: string // jyutping
  py: string // pinyin
}

export interface Lookup {
  word: string
  roman: string // jyutping (Cantonese) or pinyin (Mandarin)
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
      const roman = language === 'cantonese' ? e.jy || e.py : e.py || e.jy
      return { word, roman: roman || '', def: (e.d || []).join('; ') }
    }
  }
  return null
}
