import { useCallback, useRef, useState } from 'react'
import { Timestamp } from 'firebase/firestore'
import type { Language, QuestionData, VocabEntry } from '../types'
import { selectNextVocab, selectRandomVocab } from '../services/vocabRepo'
import { generateQuestion, generateAudio } from '../services/questions'
import { pickUnusedContext, markContextUsed } from '../services/contextRepo'
import {
  evaluateAnswer,
  markWordMastered,
  updateReviewTime,
  type AnswerEvaluation,
} from '../services/scheduler'

export interface AssistantTurn {
  id: string
  role: 'assistant'
  vocab: VocabEntry
  question: QuestionData | null // null while generating (renders a shimmer)
  isOpener: boolean
}
export interface UserTurn {
  id: string
  role: 'user'
  vocabId: string
  text: string
  grading: boolean
  evaluation?: AnswerEvaluation
  nextReview?: Timestamp
}
export interface SystemTurn {
  id: string
  role: 'system'
  text: string
}
export type Turn = AssistantTurn | UserTurn | SystemTurn

function uid(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `${Date.now()}-${Math.floor(Math.random() * 1e9)}`
}

interface UseConversationArgs {
  language: Language
}

export function useConversation({ language }: UseConversationArgs) {
  const [turns, setTurns] = useState<Turn[]>([])
  const [busy, setBusy] = useState(false)
  const currentVocabRef = useRef<VocabEntry | null>(null)
  const currentQuestionRef = useRef<QuestionData | null>(null)
  const lastExchangeRef = useRef<{ question: string; answer: string } | null>(null)

  const patchTurn = useCallback((id: string, patch: Partial<Turn>) => {
    setTurns((prev) => prev.map((t) => (t.id === id ? ({ ...t, ...patch } as Turn) : t)))
  }, [])

  const attachQuestion = useCallback(
    async (turnId: string, vocab: VocabEntry, isOpener: boolean) => {
      try {
        // Every turn (unified): ONE personal fact + the recent exchange. One fact keeps the
        // sentence about a single thing — several facts made the model list them all + revert
        // to using the word as a vocative ("股東, you just..."). The model weaves the SRS word in.
        let personalContext = ''
        let contextEntryIds: string[] = []
        try {
          const entries = await pickUnusedContext(language, 1)
          if (entries.length) {
            personalContext = entries[0].text
            contextEntryIds = entries.map((e) => e.id)
          }
        } catch (err) {
          console.warn('[conversation] personal context unavailable:', err)
        }
        const conversationContext = lastExchangeRef.current
          ? `你：${lastExchangeRef.current.question}\n我：${lastExchangeRef.current.answer}`
          : ''
        // Precomputed colloquial alternative (Cantonese only); null = use the word directly.
        const alt =
          language === 'cantonese' && typeof vocab.alt === 'string' ? vocab.alt : null
        // Base shell; the streamed question text fills `.question` live via onDelta (typewriter).
        const base: QuestionData = {
          question: '',
          word: vocab.simplified,
          language,
          requires_alternative: language === 'cantonese' && !!alt,
          target_word: alt ?? vocab.simplified,
        }
        const resp = await generateQuestion({
          word: vocab.simplified,
          alt,
          language,
          conversationContext,
          personalContext,
          isOpener,
          onDelta: (_chunk, full) => {
            const streaming = { ...base, question: full, audioLoading: true }
            currentQuestionRef.current = streaming
            patchTurn(turnId, { question: streaming } as Partial<AssistantTurn>)
          },
        })
        const question: QuestionData = { ...base, question: resp.question, audioLoading: true }
        currentQuestionRef.current = question
        patchTurn(turnId, { question } as Partial<AssistantTurn>)

        // Mark the drawn context entry used so it doesn't resurface for this language.
        for (const id of contextEntryIds) {
          markContextUsed(id, language).catch((err) =>
            console.warn('[conversation] mark context used failed:', err),
          )
        }

        // Pre-generate audio in the background (old app's pattern).
        generateAudio(resp.question, language)
          .then((a) => {
            const withAudio = { ...question, audio: a.audio, audioLoading: false }
            currentQuestionRef.current = withAudio
            patchTurn(turnId, { question: withAudio } as Partial<AssistantTurn>)
          })
          .catch((err) => {
            console.error('[conversation] audio pre-generation failed:', err)
            const noAudio = { ...question, audioLoading: false }
            currentQuestionRef.current = noAudio
            patchTurn(turnId, { question: noAudio } as Partial<AssistantTurn>)
          })
      } catch (err) {
        console.error('[conversation] question generation failed:', err)
        patchTurn(turnId, {
          question: {
            question: '⚠️ Could not generate a question. Tap Next to retry.',
            word: vocab.simplified,
            language,
            requires_alternative: false,
            target_word: vocab.simplified,
          },
        } as Partial<AssistantTurn>)
      }
    },
    [language, patchTurn],
  )

  const pushTurnForVocab = useCallback(
    async (vocab: VocabEntry, isOpener: boolean) => {
      setBusy(true)
      currentQuestionRef.current = null
      currentVocabRef.current = vocab
      const turnId = uid()
      setTurns((prev) => [
        ...prev,
        { id: turnId, role: 'assistant', vocab, question: null, isOpener },
      ])
      try {
        await attachQuestion(turnId, vocab, isOpener)
      } finally {
        setBusy(false)
      }
    },
    [attachQuestion],
  )

  const pushNextVocab = useCallback(
    async (isOpener: boolean) => {
      setBusy(true)
      currentQuestionRef.current = null
      let vocab: VocabEntry | null = null
      let message: string | undefined
      try {
        const res = await selectNextVocab(language)
        vocab = res.vocab
        message = res.message
      } catch (err) {
        console.error('[conversation] selectNextVocab failed:', err)
      }
      if (!vocab) {
        currentVocabRef.current = null
        setTurns((prev) => [
          ...prev,
          { id: uid(), role: 'system', text: message ?? 'No vocabulary available' },
        ])
        setBusy(false)
        return
      }
      await pushTurnForVocab(vocab, isOpener)
    },
    [language, pushTurnForVocab],
  )

  /** Begin a fresh conversation (used on load and on language change). */
  const start = useCallback(async () => {
    setTurns([])
    currentVocabRef.current = null
    currentQuestionRef.current = null
    await pushNextVocab(true)
  }, [pushNextVocab])

  const submitAnswer = useCallback(
    async (answer: string, hadDifficulty: boolean) => {
      const vocab = currentVocabRef.current
      const question = currentQuestionRef.current
      if (!vocab || !question) return

      const userTurnId = uid()
      setTurns((prev) => [
        ...prev,
        { id: userTurnId, role: 'user', vocabId: vocab.id, text: answer, grading: true },
      ])
      try {
        const result = await evaluateAnswer({
          docId: vocab.id,
          language,
          answer,
          hadDifficulty,
          generatedQuestion: question.question,
          requiresAlternative: question.requires_alternative,
          targetWord: question.target_word,
        })
        const nextReview = new Timestamp(
          result.nextReview.seconds,
          result.nextReview.nanoseconds,
        )
        patchTurn(userTurnId, {
          grading: false,
          evaluation: result.evaluation,
          nextReview,
        } as Partial<UserTurn>)
      } catch (err) {
        console.error('[conversation] grading failed:', err)
        patchTurn(userTurnId, {
          grading: false,
          evaluation: {
            fluent: false,
            meaningful_usage: false,
            romanization: '',
            feedback: '⚠️ Grading failed. Please try again.',
          },
        } as Partial<UserTurn>)
      }
    },
    [language, patchTurn],
  )

  const next = useCallback(async () => {
    await pushNextVocab(false)
  }, [pushNextVocab])

  const masterCurrent = useCallback(async () => {
    const vocab = currentVocabRef.current
    if (vocab) {
      try {
        await markWordMastered(vocab.id, language)
      } catch (err) {
        console.error('[conversation] mark mastered failed:', err)
      }
    }
    await pushNextVocab(false)
  }, [language, pushNextVocab])

  /** Load a random word from the whole collection (the old app's shuffle). */
  const shuffle = useCallback(async () => {
    setBusy(true)
    currentQuestionRef.current = null
    let vocab: VocabEntry | null = null
    try {
      vocab = await selectRandomVocab()
    } catch (err) {
      console.error('[conversation] selectRandomVocab failed:', err)
    }
    if (!vocab) {
      setTurns((prev) => [
        ...prev,
        { id: uid(), role: 'system', text: 'No vocabulary available' },
      ])
      setBusy(false)
      return
    }
    await pushTurnForVocab(vocab, false)
  }, [pushTurnForVocab])

  /** Practice a specific word chosen from the word list. */
  const practiceWord = useCallback(
    async (vocab: VocabEntry) => {
      await pushTurnForVocab(vocab, false)
    },
    [pushTurnForVocab],
  )

  const updateReviewTimeForTurn = useCallback(
    async (userTurnId: string, vocabId: string, iso: string) => {
      try {
        const result = await updateReviewTime(vocabId, language, iso)
        const nextReview = new Timestamp(
          result.nextReview.seconds,
          result.nextReview.nanoseconds,
        )
        patchTurn(userTurnId, { nextReview } as Partial<UserTurn>)
      } catch (err) {
        console.error('[conversation] update review time failed:', err)
      }
    },
    [language, patchTurn],
  )

  return {
    turns,
    busy,
    start,
    submitAnswer,
    next,
    masterCurrent,
    shuffle,
    practiceWord,
    updateReviewTimeForTurn,
  }
}
