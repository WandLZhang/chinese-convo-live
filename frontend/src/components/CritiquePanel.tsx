import { useEffect, useState, type ChangeEvent } from 'react'
import type { Timestamp } from 'firebase/firestore'
import type { AnswerEvaluation } from '../services/scheduler'
import type { Language } from '../types'
import Markdown from './Markdown'
import TappableText from './TappableText'

interface Props {
  evaluation: AnswerEvaluation
  language: Language
  nextReview?: Timestamp
  isLatest: boolean
  onUpdateReviewTime: (iso: string) => void
  onNext: () => void
  onMaster: () => void
}

function toLocalInput(date: Date): string {
  const p = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${p(date.getMonth() + 1)}-${p(date.getDate())}T${p(date.getHours())}:${p(date.getMinutes())}`
}

function Badge({ ok, label }: { ok: boolean; label: string }) {
  return <span className={`badge ${ok ? 'badge-ok' : 'badge-warn'}`}>{label}</span>
}

export default function CritiquePanel({
  evaluation,
  language,
  nextReview,
  isLatest,
  onUpdateReviewTime,
  onNext,
  onMaster,
}: Props) {
  const [inputValue, setInputValue] = useState('')
  const [feedbackOpen, setFeedbackOpen] = useState(false)

  useEffect(() => {
    if (nextReview) setInputValue(toLocalInput(nextReview.toDate()))
  }, [nextReview])

  const handleTimeChange = (e: ChangeEvent<HTMLInputElement>) => {
    setInputValue(e.target.value)
    const d = new Date(e.target.value)
    if (!Number.isNaN(d.getTime())) {
      onUpdateReviewTime(d.toISOString().split('.')[0])
    }
  }

  const feedback = evaluation.feedback?.trim() ?? ''
  const longFeedback = feedback.length > 150

  return (
    <div className="critique">
      <div className="critique-badges">
        <Badge ok={evaluation.fluent} label="fluent" />
        <Badge ok={evaluation.meaningful_usage} label="uses word" />
      </div>


      {evaluation.improved_answer && (
        <div className="critique-improved">
          <span className="critique-label">Say it like</span>
          <div className="chinese-text critique-improved-text">
            <TappableText text={evaluation.improved_answer} language={language} />
          </div>
        </div>
      )}

      {feedback && (
        <div className="critique-feedback">
          <Markdown
            text={feedback}
            className={`md ${longFeedback && !feedbackOpen ? 'clamp' : ''}`}
          />
          {longFeedback && (
            <button
              type="button"
              className="link-btn"
              onClick={() => setFeedbackOpen((o) => !o)}
            >
              {feedbackOpen ? 'Show less' : 'Show more'}
            </button>
          )}
        </div>
      )}

      {isLatest && (
        <div className="critique-footer">
          {nextReview && (
            <label className="critique-review">
              <span className="critique-label">Next review</span>
              <input type="datetime-local" value={inputValue} onChange={handleTimeChange} />
            </label>
          )}
          <div className="critique-actions">
            <button type="button" className="btn btn-primary" onClick={onNext}>
              Next word
            </button>
            <button type="button" className="btn btn-tonal" onClick={onMaster}>
              Mastered
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
