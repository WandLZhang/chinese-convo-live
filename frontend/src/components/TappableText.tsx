import { useState } from 'react'
import type { Language } from '../types'
import { isCjk, lookupAt, type Lookup } from '../services/dict'

/**
 * Renders text with every CJK character tappable -> dictionary pop-out (jyutping/pinyin + definition,
 * tone-coloured). Optional `onWordTap` fires on any tap (e.g. to flag "had difficulty" on the question).
 * Used for both the generated question and the graded suggested answer.
 */
export default function TappableText({
  text,
  language,
  onWordTap,
}: {
  text: string
  language: Language
  onWordTap?: () => void
}) {
  const [lookup, setLookup] = useState<Lookup | null>(null)
  const [loading, setLoading] = useState(false)

  const handleTap = async (i: number) => {
    onWordTap?.()
    setLookup(null)
    setLoading(true)
    try {
      const r = await lookupAt(text, i, language)
      setLookup(r ?? { word: text[i], reading: [], def: '(no dictionary entry)' })
    } catch (err) {
      console.error('[dict] lookup failed:', err)
      setLookup({ word: text[i], reading: [], def: '(dictionary unavailable)' })
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      {text.split('').map((ch, i) =>
        isCjk(ch) ? (
          <span key={i} className="tap-char" onClick={() => void handleTap(i)}>
            {ch}
          </span>
        ) : (
          <span key={i}>{ch}</span>
        ),
      )}
      {(lookup || loading) && (
        <div className="dict-pop" onClick={() => setLookup(null)} title="Tap to dismiss">
          {loading ? (
            <span className="dict-loading">looking up…</span>
          ) : (
            lookup && (
              <>
                <span className="dict-word chinese-text">{lookup.word}</span>
                {lookup.reading.length > 0 && (
                  <span className="dict-roman">
                    {lookup.reading.map((seg, k) => (
                      <span key={k} style={{ color: seg.color }}>
                        {k > 0 ? ' ' : ''}
                        {seg.text}
                      </span>
                    ))}
                  </span>
                )}
                <span className="dict-def">{lookup.def}</span>
              </>
            )
          )}
        </div>
      )}
    </>
  )
}
