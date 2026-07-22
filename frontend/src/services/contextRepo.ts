import {
  collection,
  doc,
  getDocs,
  limit,
  query,
  serverTimestamp,
  updateDoc,
  where,
} from 'firebase/firestore'
import { db } from './firebase'
import type { Language } from '../types'

// The deterministic personalization DB, built server-side (see docs/superpowers/specs).
// The client only READS an unused entry for the opener and marks it used — no OAuth here.
const COLLECTION = 'context_entries'

function usedField(language: Language): 'usedCantoneseAt' | 'usedMandarinAt' {
  return language === 'cantonese' ? 'usedCantoneseAt' : 'usedMandarinAt'
}

export interface ContextEntry {
  id: string
  text: string
  source: string
}

/**
 * Pick up to `n` random UNUSED context entries for this language. The generator uses ONE fact
 * per sentence (several made it list them all), so callers pass n=1; the param stays for
 * flexibility. Empty array when the pool is exhausted (caller falls back to a plain question).
 */
export async function pickUnusedContext(language: Language, n = 1): Promise<ContextEntry[]> {
  const snap = await getDocs(
    query(collection(db, COLLECTION), where(usedField(language), '==', null), limit(60)),
  )
  if (snap.empty) return []
  const shuffled = [...snap.docs].sort(() => Math.random() - 0.5).slice(0, n)
  return shuffled.map((d) => {
    const data = d.data()
    return { id: d.id, text: String(data.text ?? ''), source: String(data.source ?? '') }
  })
}

/** Mark an entry used for this language so the randomizer never surfaces it again for it. */
export async function markContextUsed(id: string, language: Language): Promise<void> {
  await updateDoc(doc(db, COLLECTION, id), { [usedField(language)]: serverTimestamp() })
}
