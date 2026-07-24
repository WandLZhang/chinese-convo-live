import type { Language } from '../types'
import { functionBase } from './firebase'

const EVALUATE_URL = `${functionBase}/convo_live_evaluate_answer`
const UPDATE_TIME_URL = `${functionBase}/convo_live_update_review_time`
const MARK_MASTERED_URL = `${functionBase}/convo_live_mark_word_mastered`

export interface AnswerEvaluation {
  fluent: boolean
  meaningful_usage: boolean
  improved_answer?: string
  feedback: string
}

export interface FsTimestampData {
  seconds: number
  nanoseconds: number
}

export interface EvaluationResult {
  success?: boolean
  evaluation: AnswerEvaluation
  nextReview: FsTimestampData
}

export interface EvaluateAnswerParams {
  docId: string
  language: Language
  answer: string
  hadDifficulty?: boolean
  generatedQuestion?: string
  requiresAlternative?: boolean
  targetWord?: string
}

export async function evaluateAnswer(
  params: EvaluateAnswerParams,
): Promise<EvaluationResult> {
  const body = {
    docId: params.docId,
    language: params.language,
    answer: params.answer,
    hadDifficulty: params.hadDifficulty ?? false,
    generatedQuestion: params.generatedQuestion,
    requiresAlternative: params.requiresAlternative,
    targetWord: params.targetWord,
  }
  console.log('[evaluateAnswer] request payload:', body)

  const response = await fetch(EVALUATE_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) {
    const err = await response.json().catch(() => ({ error: 'Unknown error' }))
    throw new Error(`Failed to evaluate answer: ${err.error || response.statusText}`)
  }
  const data = (await response.json()) as EvaluationResult
  console.log('[evaluateAnswer] response:', data)
  return data
}

export async function markWordMastered(
  docId: string,
  language: Language,
  mastered = true,
): Promise<{ success: boolean }> {
  const body = { docId, language, mastered }
  console.log('[markWordMastered] request payload:', body)
  const response = await fetch(MARK_MASTERED_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) {
    const err = await response.json().catch(() => ({ error: 'Unknown error' }))
    throw new Error(`Failed to mark mastered: ${err.error || response.statusText}`)
  }
  return response.json()
}

export async function updateReviewTime(
  docId: string,
  language: Language,
  newReviewTime: string,
): Promise<{ nextReview: FsTimestampData }> {
  const body = { docId, language, newReviewTime }
  console.log('[updateReviewTime] request payload:', body)
  const response = await fetch(UPDATE_TIME_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) {
    const err = await response.json().catch(() => ({ error: 'Unknown error' }))
    throw new Error(`Failed to update review time: ${err.error || response.statusText}`)
  }
  return response.json()
}
