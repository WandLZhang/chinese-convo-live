import { useEffect, useRef, useState } from 'react'
import type { Language } from '../types'
import type { AssistantTurn, Turn, UserTurn } from '../hooks/useConversation'
import TtsButton from './TtsButton'
import CritiquePanel from './CritiquePanel'
import { translateSentence } from '../services/translate'
import { isCjk, lookupAt, type Lookup } from '../services/dict'

interface Props {
  turns: Turn[]
  language: Language
  onNext: () => void
  onMaster: () => void
  onDifficulty: () => void
  onUpdateReviewTime: (userTurnId: string, vocabId: string, iso: string) => void
}

export default function ConversationView({
  turns,
  language,
  onNext,
  onMaster,
  onDifficulty,
  onUpdateReviewTime,
}: Props) {
  const bottomRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [turns])

  let lastUserIdx = -1
  turns.forEach((t, i) => {
    if (t.role === 'user') lastUserIdx = i
  })

  return (
    <div className="chat-container">
      {turns.map((turn, i) => {
        if (turn.role === 'assistant') {
          return (
            <AssistantBubble
              key={turn.id}
              turn={turn}
              language={language}
              onDifficulty={onDifficulty}
            />
          )
        }
        if (turn.role === 'user') {
          return (
            <UserBubble
              key={turn.id}
              turn={turn}
              isLatest={i === lastUserIdx}
              onNext={onNext}
              onMaster={onMaster}
              onUpdateReviewTime={(iso) => onUpdateReviewTime(turn.id, turn.vocabId, iso)}
            />
          )
        }
        return (
          <div key={turn.id} className="chat-divider">
            <span>{turn.text}</span>
          </div>
        )
      })}
      <div ref={bottomRef} />
    </div>
  )
}

/** The generated sentence with each CJK character tappable for a dictionary pop-out. */
function TappableSentence({
  text,
  onTapChar,
}: {
  text: string
  onTapChar: (i: number) => void
}) {
  // split('') → one UTF-16 unit per item; index aligns with slice(i) in the dict lookup.
  return (
    <>
      {text.split('').map((ch, i) =>
        isCjk(ch) ? (
          <span key={i} className="tap-char" onClick={() => onTapChar(i)}>
            {ch}
          </span>
        ) : (
          <span key={i}>{ch}</span>
        ),
      )}
    </>
  )
}

function DictPopover({
  lookup,
  loading,
  onClose,
}: {
  lookup: Lookup | null
  loading: boolean
  onClose: () => void
}) {
  return (
    <div className="dict-pop" onClick={onClose} title="Tap to dismiss">
      {loading ? (
        <span className="dict-loading">looking up…</span>
      ) : (
        lookup && (
          <>
            <span className="dict-word chinese-text">{lookup.word}</span>
            {lookup.reading.length > 0 && (
              <span className="dict-roman">
                {lookup.reading.map((seg, i) => (
                  <span key={i} style={{ color: seg.color }}>
                    {i > 0 ? ' ' : ''}
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
  )
}

function AssistantBubble({
  turn,
  language,
  onDifficulty,
}: {
  turn: AssistantTurn
  language: Language
  onDifficulty: () => void
}) {
  const q = turn.question
  const [showTranslation, setShowTranslation] = useState(false)
  const [translation, setTranslation] = useState('')
  const [translating, setTranslating] = useState(false)
  const [showContext, setShowContext] = useState(false)
  const [lookup, setLookup] = useState<Lookup | null>(null)
  const [lookupLoading, setLookupLoading] = useState(false)

  const handleTranslate = async () => {
    if (!q) return
    if (showTranslation) {
      setShowTranslation(false)
      return
    }
    setShowTranslation(true)
    if (translation) return // cached
    setTranslating(true)
    try {
      await translateSentence(q.question, language, (full) => setTranslation(full))
    } catch (err) {
      console.error('[translate] failed:', err)
      setTranslation('⚠️ translation failed')
    } finally {
      setTranslating(false)
    }
  }

  const handleTapChar = async (i: number) => {
    if (!q) return
    onDifficulty() // needing a definition counts as "had trouble" → SRS reschedules sooner
    setLookup(null)
    setLookupLoading(true)
    try {
      const r = await lookupAt(q.question, i, language)
      setLookup(r ?? { word: q.question[i], reading: [], def: '(no dictionary entry)' })
    } catch (err) {
      console.error('[dict] lookup failed:', err)
      setLookup({ word: q.question[i], reading: [], def: '(dictionary unavailable)' })
    } finally {
      setLookupLoading(false)
    }
  }

  return (
    <div className="message-group left">
      <div className="assistant-chip-row">
        <span className="word-chip chinese-text">{turn.vocab.simplified}</span>
        {q && (
          <button
            type="button"
            className={`chip-icon ${showTranslation ? 'active' : ''}`}
            onClick={() => void handleTranslate()}
            title="Reveal English translation"
            aria-label="Translate sentence"
          >
            <span className="material-symbols-outlined">visibility</span>
          </button>
        )}
        {q && turn.sourceContext && (
          <button
            type="button"
            className={`chip-icon ${showContext ? 'active' : ''}`}
            onClick={() => setShowContext((v) => !v)}
            title="What this sentence is based on"
            aria-label="Show source context"
          >
            <span className="material-symbols-outlined">attach_file</span>
          </button>
        )}
      </div>

      {q ? (
        <div className="assistant-row">
          <div className="message left chinese-text">
            <TappableSentence text={q.question} onTapChar={(i) => void handleTapChar(i)} />

            {showTranslation && (
              <div className="bubble-extra">
                <div className="bubble-divider" />
                <span className="translation-text">
                  {translation || (translating ? '…' : '')}
                </span>
              </div>
            )}

            {showContext && turn.sourceContext && (
              <div className="bubble-extra">
                <div className="bubble-divider" />
                <span className="context-label">based on</span>
                <span className="context-text">{turn.sourceContext}</span>
              </div>
            )}
          </div>
          <TtsButton question={q} language={language} />
        </div>
      ) : (
        <div className="message left thinking">
          <span className="skeleton-text" />
          <span className="skeleton-text line-2" />
        </div>
      )}

      {(lookup || lookupLoading) && (
        <DictPopover lookup={lookup} loading={lookupLoading} onClose={() => setLookup(null)} />
      )}
    </div>
  )
}

function UserBubble({
  turn,
  isLatest,
  onNext,
  onMaster,
  onUpdateReviewTime,
}: {
  turn: UserTurn
  isLatest: boolean
  onNext: () => void
  onMaster: () => void
  onUpdateReviewTime: (iso: string) => void
}) {
  const edge = turn.evaluation ? (turn.evaluation.fluent ? 'ok' : 'warn') : ''
  return (
    <div className="message-group right">
      <div className={`message right chinese-text ${edge}`}>{turn.text}</div>
      {turn.grading && <span className="grading-hint">grading…</span>}
      {turn.evaluation && (
        <CritiquePanel
          evaluation={turn.evaluation}
          nextReview={turn.nextReview}
          isLatest={isLatest}
          onUpdateReviewTime={onUpdateReviewTime}
          onNext={onNext}
          onMaster={onMaster}
        />
      )}
    </div>
  )
}
