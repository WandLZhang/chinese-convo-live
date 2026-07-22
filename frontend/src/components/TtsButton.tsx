import { useState } from 'react'
import type { Language, QuestionData } from '../types'
import { generateAudio, playAudio } from '../services/questions'

export default function TtsButton({
  question,
  language,
}: {
  question: QuestionData
  language: Language
}) {
  const [loading, setLoading] = useState(false)
  const busy = loading || question.audioLoading === true

  async function handlePlay() {
    if (question.audio) {
      void playAudio(question.audio)
      return
    }
    setLoading(true)
    try {
      const a = await generateAudio(question.question, language)
      void playAudio(a.audio)
    } catch (e) {
      console.error('[tts] playback failed:', e)
    } finally {
      setLoading(false)
    }
  }

  return (
    <button
      type="button"
      className="icon-btn tts"
      onClick={handlePlay}
      disabled={busy}
      title={busy ? 'Preparing audio…' : 'Play audio'}
      aria-label="Play audio"
    >
      <span className="material-symbols-outlined">
        {busy ? 'hourglass_empty' : 'volume_up'}
      </span>
    </button>
  )
}
