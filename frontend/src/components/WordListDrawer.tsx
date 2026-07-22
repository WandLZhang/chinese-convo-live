import { useEffect, useState, type ReactNode } from 'react'
import type { Language, VocabEntry } from '../types'
import { useSrs } from '../hooks/useSrs'
import { getReviewDate } from '../services/srs'

interface Props {
  language: Language
  onClose: () => void
  onPractice: (word: VocabEntry) => void
}

type SectionKey = 'scheduled' | 'new' | 'mastered'

export default function WordListDrawer({ language, onClose, onPractice }: Props) {
  const { lists, loading, refresh, scheduleWord, unmasterWord } = useSrs(language)
  const [expanded, setExpanded] = useState<Record<SectionKey, boolean>>({
    scheduled: false,
    new: false,
    mastered: false,
  })

  useEffect(() => {
    void refresh()
  }, [refresh])

  const practice = (w: VocabEntry) => {
    onClose()
    onPractice(w)
  }
  const toggle = (k: SectionKey) => setExpanded((e) => ({ ...e, [k]: !e[k] }))
  const now = new Date()

  return (
    <div className="drawer-overlay" onClick={onClose}>
      <div className="drawer" onClick={(e) => e.stopPropagation()}>
        <div className="drawer-header">
          <h2>Word list · {language === 'cantonese' ? '廣東話' : '普通话'}</h2>
          <button className="icon-btn ghost" onClick={onClose} aria-label="Close">
            <span className="material-symbols-outlined">close</span>
          </button>
        </div>
        {loading && <p className="muted drawer-loading">Loading…</p>}

        <Section
          title="Scheduled"
          items={lists.scheduled}
          expanded={expanded.scheduled}
          onToggle={() => toggle('scheduled')}
          onPractice={practice}
          renderMeta={(w) => {
            const d = getReviewDate(w, language)
            if (!d) {
              return (
                <button
                  className="link-btn"
                  onClick={(e) => {
                    e.stopPropagation()
                    void scheduleWord(w)
                  }}
                >
                  Schedule
                </button>
              )
            }
            const overdue = d < now
            return (
              <span className={overdue ? 'meta overdue' : 'meta'}>
                {overdue ? 'Overdue · ' : ''}
                {d.toLocaleString()}
              </span>
            )
          }}
        />

        <Section
          title="New"
          items={lists.new}
          expanded={expanded.new}
          onToggle={() => toggle('new')}
          onPractice={practice}
          renderMeta={(w) => (
            <button
              className="link-btn"
              onClick={(e) => {
                e.stopPropagation()
                void scheduleWord(w)
              }}
            >
              Schedule
            </button>
          )}
        />

        <Section
          title="Mastered"
          items={lists.mastered}
          expanded={expanded.mastered}
          onToggle={() => toggle('mastered')}
          onPractice={practice}
          renderMeta={(w) => (
            <button
              className="link-btn"
              onClick={(e) => {
                e.stopPropagation()
                void unmasterWord(w)
              }}
            >
              Unmark
            </button>
          )}
        />
      </div>
    </div>
  )
}

function Section({
  title,
  items,
  expanded,
  onToggle,
  onPractice,
  renderMeta,
}: {
  title: string
  items: VocabEntry[]
  expanded: boolean
  onToggle: () => void
  onPractice: (w: VocabEntry) => void
  renderMeta: (w: VocabEntry) => ReactNode
}) {
  const shown = expanded ? items : items.slice(0, 5)
  return (
    <div className="wl-section">
      <h3>
        {title} <span className="wl-count">{items.length}</span>
      </h3>
      {items.length === 0 && <p className="muted">None</p>}
      {shown.map((w) => (
        <div key={w.id} className="word-row">
          <button
            className="word-practice chinese-text"
            onClick={() => onPractice(w)}
            title="Practice this word"
          >
            {w.simplified}
          </button>
          {renderMeta(w)}
        </div>
      ))}
      {items.length > 5 && (
        <button className="link-btn" onClick={onToggle}>
          {expanded ? 'Show less' : `Show ${items.length - 5} more`}
        </button>
      )}
    </div>
  )
}
