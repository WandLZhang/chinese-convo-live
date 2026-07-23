import { useRef, useState, type FormEvent } from 'react'
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
  const [listening, setListening] = useState(false)
  // Web Speech API is untyped in TS libdom without extra defs.
  const recognitionRef = useRef<any>(null)

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    const t = text.trim()
    if (!t || disabled) return
    onSubmit(t, hadDifficulty)
    setText('')
    onHadDifficultyChange(false)
  }

  const toggleMic = () => {
    const SR =
      (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
    if (!SR) {
      alert('Voice input is not supported in this browser.')
      return
    }
    if (listening) {
      recognitionRef.current?.stop()
      return
    }
    const rec = new SR()
    rec.lang = language === 'cantonese' ? 'zh-HK' : 'zh-CN'
    rec.interimResults = true
    rec.continuous = false
    rec.onresult = (ev: any) => {
      let transcript = ''
      for (let i = 0; i < ev.results.length; i++) {
        transcript += ev.results[i][0].transcript
      }
      setText(transcript)
    }
    rec.onend = () => setListening(false)
    rec.onerror = (err: any) => {
      console.error('[stt] recognition error:', err)
      setListening(false)
    }
    recognitionRef.current = rec
    setListening(true)
    rec.start()
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
        className="chat-input-field chinese-text"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={disabled ? 'Wait for the question…' : 'Type your reply…'}
        disabled={disabled}
      />
      <button
        type="button"
        className={`icon-btn ${listening ? 'active' : ''}`}
        onClick={toggleMic}
        title="Voice input"
        aria-label="Voice input"
        disabled={disabled}
      >
        <span className="material-symbols-outlined">{listening ? 'mic' : 'mic_none'}</span>
      </button>
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
