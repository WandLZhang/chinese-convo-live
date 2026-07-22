import { useEffect, useRef, useState } from 'react'

interface Props {
  onShuffle: () => void
  onOpenWordList: () => void
}

function applyTheme(t: 'light' | 'dark') {
  localStorage.setItem('convo_theme', t)
  document.documentElement.setAttribute('data-theme', t)
}

export default function OverflowMenu({ onShuffle, onOpenWordList }: Props) {
  const [open, setOpen] = useState(false)
  const [isDark, setIsDark] = useState(
    document.documentElement.getAttribute('data-theme') === 'dark',
  )
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open])

  const toggleDark = () => {
    applyTheme(isDark ? 'light' : 'dark')
    setIsDark(!isDark)
  }

  return (
    <div className="overflow-menu" ref={ref}>
      <button
        className="icon-btn ghost"
        onClick={() => setOpen((v) => !v)}
        title="More"
        aria-label="More options"
      >
        <span className="material-symbols-outlined">more_vert</span>
      </button>
      {open && (
        <div className="menu-dropdown" role="menu">
          <button
            className="menu-item"
            onClick={() => {
              setOpen(false)
              onShuffle()
            }}
          >
            <span className="material-symbols-outlined">shuffle</span>Random word
          </button>
          <button
            className="menu-item"
            onClick={() => {
              setOpen(false)
              onOpenWordList()
            }}
          >
            <span className="material-symbols-outlined">list</span>Word list
          </button>
          <button className="menu-item" onClick={toggleDark}>
            <span className="material-symbols-outlined">
              {isDark ? 'light_mode' : 'dark_mode'}
            </span>
            {isDark ? 'Light mode' : 'Dark mode'}
          </button>
        </div>
      )}
    </div>
  )
}
