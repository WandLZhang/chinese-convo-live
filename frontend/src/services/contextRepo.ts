import {
  collection,
  doc,
  getDocs,
  limit,
  orderBy,
  query,
  serverTimestamp,
  updateDoc,
  type DocumentData,
} from 'firebase/firestore'
import { db } from './firebase'
import type { ContextQuote, Language } from '../types'

// The deterministic personalization DB, built server-side (see docs/superpowers/specs).
// The client only READS an unused entry for the opener and marks it used — no OAuth here.
const COLLECTION = 'context_entries'

function usedField(language: Language): 'usedCantoneseAt' | 'usedMandarinAt' {
  return language === 'cantonese' ? 'usedCantoneseAt' : 'usedMandarinAt'
}

export interface ContextEntry {
  id: string
  text: string // one English summary line
  source: string
  // Signal entries saved since 2026-11-23 also carry the message itself:
  quote?: string // the message as written
  sender?: string
  chat?: string | null // the group's name; null = a direct message
  sentAt?: Date
  replyTo?: { author: string; text: string } | null // author "me" = the learner
  link?: { url: string; title?: string | null; description?: string | null } | null
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

function toEntry(id: string, data: DocumentData): ContextEntry {
  const sentAt = data.sentAt && typeof data.sentAt.toDate === 'function' ? data.sentAt.toDate() : undefined
  return {
    id,
    text: String(data.text ?? ''),
    source: String(data.source ?? ''),
    ...(typeof data.quote === 'string' && data.quote
      ? {
          quote: data.quote,
          sender: String(data.sender ?? ''),
          chat: data.chat ?? null,
          sentAt,
          replyTo: data.replyTo ?? null,
          link: data.link ?? null,
        }
      : {}),
  }
}

/**
 * Recency-biased LRU: from the most-recently-ingested facts, return `n` of the least-recently-used
 * for this language (never-used first), with light randomness for variety. Entries that carry the
 * message itself come first; the summary-only ones are the fallback until a quoted one exists.
 * A Firestore TTL policy deletes every entry 30 days after it was saved. Empty array only if the
 * collection is empty.
 */
export async function pickContext(language: Language, n = 1): Promise<ContextEntry[]> {
  const col = collection(db, COLLECTION)
  // orderBy('sentAt') returns only the docs that have the field, which is the quoted ones.
  let snap = await getDocs(query(col, orderBy('sentAt', 'desc'), limit(WINDOW)))
  if (snap.empty) snap = await getDocs(query(col, orderBy('createdAt', 'desc'), limit(WINDOW)))
  if (snap.empty) return []
  const field = usedField(language)
  const byLru = [...snap.docs].sort((a, b) => toMillis(a.data()[field]) - toMillis(b.data()[field]))
  const pool = byLru.slice(0, Math.max(LRU_POOL, n))
  const chosen = pool.sort(() => Math.random() - 0.5).slice(0, n)
  return chosen.map((d) => toEntry(d.id, d.data()))
}

/** YYYY-MM-DD in the phone's time zone. */
export function localDate(d: Date): string {
  const p = (x: number) => String(x).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

/** The message the generator builds on, or null for a summary-only entry. */
export function quoteFor(entry: ContextEntry): ContextQuote | null {
  if (!entry.quote) return null
  return {
    sender: entry.sender || 'someone',
    chat: entry.chat ?? null,
    text: entry.quote,
    sentDate: entry.sentAt ? localDate(entry.sentAt) : null,
    replyTo: entry.replyTo ?? null,
    link: entry.link?.url ? { url: entry.link.url, title: entry.link.title ?? null } : null,
  }
}

/** Stamp lastUsedAt for this language so the entry is deprioritized (LRU) — not permanently retired. */
export async function markContextUsed(id: string, language: Language): Promise<void> {
  await updateDoc(doc(db, COLLECTION, id), { [usedField(language)]: serverTimestamp() })
}
