import {
  collection,
  doc,
  getDocs,
  limit,
  orderBy,
  query,
  serverTimestamp,
  updateDoc,
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

const WINDOW = 40 // consider the N most recently ingested facts (recency bias)
const LRU_POOL = 8 // among those, choose from the K least-recently-used (variety, not deterministic)

function toMillis(v: unknown): number {
  // Firestore Timestamp -> ms; null/never-used -> 0 (treated as oldest = highest priority).
  if (v && typeof v === 'object' && 'toMillis' in (v as { toMillis?: () => number })) {
    return (v as { toMillis: () => number }).toMillis()
  }
  return 0
}

/**
 * Recency-biased LRU: from the most-recently-ingested facts, return `n` of the least-recently-used
 * for this language (never-used first), with light randomness for variety. Facts are REUSED, never
 * permanently retired — the pool is thousands of entries. Empty array only if the collection is empty.
 */
export async function pickContext(language: Language, n = 1): Promise<ContextEntry[]> {
  const snap = await getDocs(
    query(collection(db, COLLECTION), orderBy('createdAt', 'desc'), limit(WINDOW)),
  )
  if (snap.empty) return []
  const field = usedField(language)
  const byLru = [...snap.docs].sort((a, b) => toMillis(a.data()[field]) - toMillis(b.data()[field]))
  const pool = byLru.slice(0, Math.max(LRU_POOL, n))
  const chosen = pool.sort(() => Math.random() - 0.5).slice(0, n)
  return chosen.map((d) => {
    const data = d.data()
    return { id: d.id, text: String(data.text ?? ''), source: String(data.source ?? '') }
  })
}

/** Stamp lastUsedAt for this language so the entry is deprioritized (LRU) — not permanently retired. */
export async function markContextUsed(id: string, language: Language): Promise<void> {
  await updateDoc(doc(db, COLLECTION, id), { [usedField(language)]: serverTimestamp() })
}
