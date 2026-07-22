import { useCallback, useState } from 'react'
import type { Language, VocabEntry } from '../types'
import { fetchWordLists, type WordLists } from '../services/vocabRepo'
import { markWordMastered, updateReviewTime } from '../services/scheduler'

const EMPTY: WordLists = { scheduled: [], new: [], mastered: [] }

/** ISO string with milliseconds stripped (the backend expects no ms). */
function isoMinutesFromNow(minutes: number): string {
  const date = new Date()
  date.setMinutes(date.getMinutes() + minutes)
  return date.toISOString().split('.')[0]
}

/**
 * Word-list state + scheduling actions for the three-dot menu's Word List
 * drawer. Vocab selection for the chat flow lives in vocabRepo (selectNextVocab
 * / selectRandomVocab) and is driven by the conversation hook.
 */
export function useSrs(language: Language) {
  const [lists, setLists] = useState<WordLists>(EMPTY)
  const [loading, setLoading] = useState(false)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      setLists(await fetchWordLists(language))
    } finally {
      setLoading(false)
    }
  }, [language])

  const scheduleWord = useCallback(
    async (word: VocabEntry, minutesFromNow = 5) => {
      await updateReviewTime(word.id, language, isoMinutesFromNow(minutesFromNow))
      await refresh()
    },
    [language, refresh],
  )

  const unmasterWord = useCallback(
    async (word: VocabEntry) => {
      // Match the old app: unmark, then reschedule 5 minutes out.
      await markWordMastered(word.id, language, false)
      await scheduleWord(word, 5)
    },
    [language, scheduleWord],
  )

  return { lists, loading, refresh, scheduleWord, unmasterWord }
}
