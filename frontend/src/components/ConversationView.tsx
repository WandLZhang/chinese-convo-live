import { useEffect, useRef, useState } from 'react'
import type { Language } from '../types'
import type { AssistantTurn, Turn, UserTurn } from '../hooks/useConversation'
import TtsButton from './TtsButton'
import CritiquePanel from './CritiquePanel'
import TappableText from './TappableText'
import { translateSentence } from '../services/translate'

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

  // When the on-screen keyboard opens (visual viewport shrinks), anchor the latest AI sentence to
  // the top so it stays visible above the keyboard instead of scrolling away as the input focuses.
  useEffect(() => {
    const vv = window.visualViewport
    if (!vv) return
    let prev = vv.height
    const onResize = () => {
      const opened = vv.height < prev - 120
      prev = vv.height
      if (!opened) return
      setTimeout(() => {
        const lefts = document.querySelectorAll('.chat-container .message-group.left')
        const last = lefts[lefts.length - 1] as HTMLElement | undefined
        last?.scrollIntoView({ block: 'start', behavior: 'smooth' })
      }, 60)
    }
    vv.addEventListener('resize', onResize)
    return () => vv.removeEventListener('resize', onResize)
  }, [])

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
              language={language}
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
            <TappableText text={q.question} language={language} onWordTap={onDifficulty} />

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
    </div>
  )
}

function UserBubble({
  turn,
  language,
  isLatest,
  onNext,
  onMaster,
  onUpdateReviewTime,
}: {
  turn: UserTurn
  language: Language
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
          language={language}
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
