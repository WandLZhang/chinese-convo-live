import { useEffect, useRef } from 'react'
import type { Language } from '../types'
import type { AssistantTurn, Turn, UserTurn } from '../hooks/useConversation'
import TtsButton from './TtsButton'
import CritiquePanel from './CritiquePanel'

interface Props {
  turns: Turn[]
  language: Language
  onNext: () => void
  onMaster: () => void
  onUpdateReviewTime: (userTurnId: string, vocabId: string, iso: string) => void
}

export default function ConversationView({
  turns,
  language,
  onNext,
  onMaster,
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
          return <AssistantBubble key={turn.id} turn={turn} language={language} />
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

function AssistantBubble({ turn, language }: { turn: AssistantTurn; language: Language }) {
  return (
    <div className="message-group left">
      <span className="word-chip chinese-text">{turn.vocab.simplified}</span>
      {turn.question ? (
        <div className="assistant-row">
          <div className="message left chinese-text">{turn.question.question}</div>
          <TtsButton question={turn.question} language={language} />
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
