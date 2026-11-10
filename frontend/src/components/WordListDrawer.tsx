import { useEffect, useState, type ReactNode } from 'react'
import type { Language, VocabEntry } from '../types'
import { useSrs } from '../hooks/useSrs'
import { ankiDayStart, getReviewDate, relativeDue } from '../services/srs'

interface Props {
  language: Language
  onClose: () => void
  onPractice: (word: VocabEntry) => void
}

type SectionKey = 'incoming' | 'scheduled' | 'new' | 'mastered'

/** "Nov 20", with the year only when it isn't this year ("Mar 21, 2027"). */
function shortDate(d: Date, now: Date): string {
  return d.toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: d.getFullYear() !== now.getFullYear() ? 'numeric' : undefined,
  })
}

export default function WordListDrawer({ language, onClose, onPractice }: Props) {
  const { lists, loading, error, refresh, scheduleWord, unmasterWord } = useSrs(language)
  const [expanded, setExpanded] = useState<Record<SectionKey, boolean>>({
    incoming: false,
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
  const todayStart = ankiDayStart(now)

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
        {error && <p className="error drawer-loading">Couldn't load the word list: {error}</p>}

        {/* Slated for today (until the 4 AM day boundary), overdue included, in the order Next
            serves them. */}
        <Section
          title="Incoming"
          items={lists.incoming}
          expanded={expanded.incoming}
          onToggle={() => toggle('incoming')}
          onPractice={practice}
          renderMeta={(w) => {
            const d = getReviewDate(w, language)
            if (!d) return null
            if (d < todayStart) {
              return <span className="meta overdue">Overdue · {shortDate(d, now)}</span>
            }
            return <span className="meta">{d <= now ? 'Due now' : relativeDue(d, now)}</span>
          }}
        />

        <Section
          title="New"
          items={lists.new}
          total={lists.newTotal}
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

        {/* Future days, earliest first. */}
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
            return (
              <span className="meta">
                {shortDate(d, now)} · {relativeDue(d, now)}
              </span>
            )
          }}
        />
      </div>
    </div>
  )
}

function Section({
  title,
  items,
  total,
  expanded,
  onToggle,
  onPractice,
  renderMeta,
}: {
  title: string
  items: VocabEntry[]
  /** The header count when the section only loads part of the list (New loads 50). */
  total?: number
  expanded: boolean
  onToggle: () => void
  onPractice: (w: VocabEntry) => void
  renderMeta: (w: VocabEntry) => ReactNode
}) {
  const shown = expanded ? items : items.slice(0, 5)
  return (
    <div className="wl-section">
      <h3>
        {title} <span className="wl-count">{total ?? items.length}</span>
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
