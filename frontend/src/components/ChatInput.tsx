import { useState, type FormEvent } from 'react'
import type { Language } from '../types'

interface Props {
  language: Language
  disabled: boolean
  hadDifficulty: boolean
  onHadDifficultyChange: (v: boolean) => void
  onSubmit: (answer: string, hadDifficulty: boolean) => void
}

export default function ChatInput({
  language,
  disabled,
  hadDifficulty,
  onHadDifficultyChange,
  onSubmit,
}: Props) {
  const [text, setText] = useState('')

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    const t = text.trim()
    if (!t || disabled) return
    onSubmit(t, hadDifficulty)
    setText('')
    onHadDifficultyChange(false)
  }

  return (
    <form className="chat-input" onSubmit={handleSubmit}>
      <button
        type="button"
        className={`icon-btn ${hadDifficulty ? 'active-warn' : ''}`}
        onClick={() => onHadDifficultyChange(!hadDifficulty)}
        title="Mark that this one was hard"
        aria-label="Had difficulty"
        disabled={disabled}
      >
        <span className="material-symbols-outlined">sentiment_stressed</span>
      </button>
      <input
        lang={language === 'cantonese' ? 'zh-HK' : 'zh-CN'}
        className="chat-input-field chinese-text"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={disabled ? 'Wait for the question…' : 'Type your reply…'}
        disabled={disabled}
      />
      <button
        type="submit"
        className="icon-btn send"
        disabled={disabled || !text.trim()}
        title="Send"
        aria-label="Send"
      >
        <span className="material-symbols-outlined">send</span>
      </button>
    </form>
  )
}
