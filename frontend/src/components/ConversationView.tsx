import { useEffect, useRef, useState } from 'react'
import type { Language } from '../types'
import type { AssistantTurn, Turn, UserTurn } from '../hooks/useConversation'
import TtsButton from './TtsButton'
import CritiquePanel from './CritiquePanel'
import TappableText from './TappableText'
import { translateSentence } from '../services/translate'
import { tapHitsWord } from '../services/dict'
import { GRADES, GRADE_NAMES, type Grade } from '../services/scheduler'
import { buttonLabel } from '../services/srs'
import type { ContextEntry } from '../services/contextRepo'

interface Props {
  turns: Turn[]
  language: Language
  onNext: () => void
  onMaster: () => void
  onDifficulty: () => void
  onUpdateReviewTime: (userTurnId: string, vocabId: string, iso: string) => void
  canGrade: boolean // the newest sentence is loaded and nothing is in flight
  onGrade: (grade: Grade) => void
}

export default function ConversationView({
  turns,
  language,
  onNext,
  onMaster,
  onDifficulty,
  onUpdateReviewTime,
  canGrade,
  onGrade,
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
  let lastAssistantIdx = -1
  turns.forEach((t, i) => {
    if (t.role === 'user') lastUserIdx = i
    if (t.role === 'assistant') lastAssistantIdx = i
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
              // Only the current question can raise the struggle face; an old bubble's word isn't
              // the one being graded.
              onDifficulty={i === lastAssistantIdx ? onDifficulty : undefined}
              // The Anki buttons sit under the newest sentence until it gets a reply or a grade.
              showGrades={i === turns.length - 1}
              onGrade={canGrade ? onGrade : undefined}
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
  showGrades,
  onGrade,
}: {
  turn: AssistantTurn
  language: Language
  onDifficulty?: () => void
  showGrades?: boolean
  onGrade?: (grade: Grade) => void
}) {
  const q = turn.question
  const [showTranslation, setShowTranslation] = useState(false)
  const [translation, setTranslation] = useState('')
  const [translating, setTranslating] = useState(false)
  const [showContext, setShowContext] = useState(false)

  // The struggle face rises only for a tap on the target word, in either script. Looking up some
  // other word in the sentence doesn't mean you didn't know the one being drilled.
  const handleWordTap = (i: number) => {
    if (!q || !onDifficulty) return
    tapHitsWord(q.question, i, q.target_word)
      .then((hit) => {
        if (hit) onDifficulty()
      })
      .catch((err) => console.error('[difficulty] target check failed:', err))
  }

  const handleTranslate = async () => {
    if (!q) return
    if (showTranslation) {
      setShowTranslation(false)
      return
    }
    // Needing the whole sentence translated counts as struggling with it.
    onDifficulty?.()
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
            <TappableText text={q.question} language={language} onWordTap={handleWordTap} />

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
                <ContextSource entry={turn.sourceContext} />
              </div>
            )}

            {showGrades && <GradeBar grades={turn.grades} onGrade={onGrade} />}
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

const GRADE_ICONS: Record<Grade, string> = { again: 'replay', hard: 'hourglass_top', good: 'check', easy: 'bolt' }

/** Anki's four answer buttons, quiet, at the foot of the sentence's bubble, each with the interval it would give,
 *  as AnkiDroid shows them. A tap grades the word with that button and moves on. */
function GradeBar({
  grades,
  onGrade,
}: {
  grades?: Partial<Record<Grade, Date>>
  onGrade?: (grade: Grade) => void
}) {
  const now = new Date()
  return (
    <div className="grade-bar" role="group" aria-label="Grade this word like Anki">
      {GRADES.map((g) => {
        const due = grades?.[g]
        const label = due ? buttonLabel(due, now) : '…'
        return (
          <button
            key={g}
            type="button"
            className={`grade-btn ${g}`}
            disabled={!onGrade}
            onClick={() => onGrade?.(g)}
            title={`${GRADE_NAMES[g]} · ${label}`}
            aria-label={`${GRADE_NAMES[g]}, ${label}`}
          >
            <span className="material-symbols-outlined">{GRADE_ICONS[g]}</span>
            <span className="grade-ivl">{label}</span>
          </button>
        )
      })}
    </div>
  )
}

const APPS: Record<string, string> = {
  signal: 'Signal',
  whatsapp: 'WhatsApp',
  messenger: 'Messenger',
  messages: 'Messages',
  google_chat: 'Google Chat',
  email: 'Email',
}

/** What a sentence was built from: the message as written, or an older entry's one-line summary. */
function ContextSource({ entry }: { entry: ContextEntry }) {
  if (!entry.quote) return <span className="context-text">{entry.text}</span>
  const when = entry.sentAt?.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
  const mine = entry.sender === 'me'
  const where = entry.chat ?? (mine && entry.to ? `to ${entry.to}` : null)
  const app = APPS[entry.source] ?? entry.source
  const meta = [mine ? 'You' : entry.sender, where, app, when].filter(Boolean).join(' · ')
  return (
    <>
      <span className="context-meta">{meta}</span>
      {entry.replyTo && (
        <span className="context-reply">
          Replying to {entry.replyTo.author === 'me' ? 'you' : entry.replyTo.author}: “{entry.replyTo.text}”
        </span>
      )}
      <span className="context-quote">“{entry.quote}”</span>
      {entry.preview && <span className="context-reply">Chat-list preview, may be cut off</span>}
      {entry.link?.url && (
        <a className="context-link" href={entry.link.url} target="_blank" rel="noreferrer">
          {entry.link.title || entry.link.url}
        </a>
      )}
    </>
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
