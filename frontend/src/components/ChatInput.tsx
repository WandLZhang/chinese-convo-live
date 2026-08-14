import { useState, type FormEvent } from 'react'
import type { Language } from '../types'
import { useRecorder } from '../hooks/useRecorder'
import { transcribeAudio } from '../services/transcribe'

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
  const [transcribing, setTranscribing] = useState(false)
  const [failed, setFailed] = useState<Blob | null>(null) // keep the audio so a failure can be retried
  const rec = useRecorder()

  const send = (t: string) => {
    if (!t.trim()) return
    onSubmit(t.trim(), hadDifficulty)
    setText('')
    onHadDifficultyChange(false)
  }

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (disabled) return
    send(text)
  }

  /** Transcribe a recording. autoSend=true is the ↑ path; otherwise fill the field for review. */
  const runTranscription = async (blob: Blob, autoSend: boolean) => {
    setTranscribing(true)
    setFailed(null)
    try {
      const t = await transcribeAudio(blob, language)
      if (!t) return
      if (autoSend) send(t)
      else setText((prev) => (prev ? `${prev} ${t}` : t))
    } catch (err) {
      console.error('[transcribe] failed:', err)
      setFailed(blob) // don't silently drop what was said — offer a retry
    } finally {
      setTranscribing(false)
    }
  }

  // ⏹ stop -> transcript lands in the field so names (which SenseVoice garbles) can be fixed first.
  const stopAndFill = async () => {
    const blob = await rec.stop()
    if (blob) void runTranscription(blob, false)
  }

  // ↑ send -> transcribe and submit in one step.
  const stopAndSend = async () => {
    const blob = await rec.stop()
    if (blob) void runTranscription(blob, true)
  }

  if (rec.recording) {
    return (
      <div className="chat-input recording">
        <button
          type="button"
          className="icon-btn"
          onClick={rec.cancel}
          title="Discard recording"
          aria-label="Discard recording"
        >
          <span className="material-symbols-outlined">close</span>
        </button>
        <div className="rec-wave" aria-label="Recording">
          {Array.from({ length: 9 }, (_, i) => (
            <span key={i} style={{ animationDelay: `${i * 0.1}s` }} />
          ))}
        </div>
        <button
          type="button"
          className="icon-btn"
          onClick={() => void stopAndFill()}
          title="Stop and put the text in the box"
          aria-label="Stop and review"
        >
          <span className="material-symbols-outlined">stop_circle</span>
        </button>
        <button
          type="button"
          className="icon-btn send"
          onClick={() => void stopAndSend()}
          title="Stop and send"
          aria-label="Stop and send"
        >
          <span className="material-symbols-outlined">arrow_upward</span>
        </button>
      </div>
    )
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
        placeholder={
          transcribing ? 'Transcribing…' : disabled ? 'Wait for the question…' : 'Type your reply…'
        }
        disabled={disabled || transcribing}
      />

      {failed ? (
        <button
          type="button"
          className="icon-btn active-warn"
          onClick={() => void runTranscription(failed, false)}
          title="Transcription failed — tap to retry"
          aria-label="Retry transcription"
        >
          <span className="material-symbols-outlined">refresh</span>
        </button>
      ) : (
        rec.supported && (
          <button
            type="button"
            className="icon-btn"
            onClick={() => void rec.start()}
            title="Record your reply"
            aria-label="Record"
            disabled={disabled || transcribing}
          >
            <span className="material-symbols-outlined">
              {transcribing ? 'hourglass_top' : 'mic'}
            </span>
          </button>
        )
      )}

      <button
        type="submit"
        className="icon-btn send"
        disabled={disabled || transcribing || !text.trim()}
        title="Send"
        aria-label="Send"
      >
        <span className="material-symbols-outlined">send</span>
      </button>
    </form>
  )
}
