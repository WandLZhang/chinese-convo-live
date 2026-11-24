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
import { chooseEntries } from './contextPick'

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
  // Entries saved since 2026-11-23 (Signal, WhatsApp, Messenger, Messages, Google Chat, email) also carry the message:
  quote?: string // the message as written
  preview?: boolean // true = only a chat-list preview (Messenger, Messages), possibly cut off
  sender?: string // "me" = the learner, for a message they sent from their phone
  to?: string | null // who got a direct message the learner sent
  chat?: string | null // the group's name or "Note to Self"; null = a direct message
  sentAt?: Date
  replyTo?: { author: string; text: string } | null // author "me" = the learner
  link?: { url: string; title?: string | null; description?: string | null } | null
}

const WINDOW = 40 // consider the N most recently saved entries of each kind (recency bias)

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
          preview: data.preview === true,
          sender: String(data.sender ?? ''),
          to: data.to ?? null,
          chat: data.chat ?? null,
          sentAt,
          replyTo: data.replyTo ?? null,
          link: data.link ?? null,
        }
      : {}),
  }
}

/**
 * `n` entries for the next sentence, from the most recently saved ones (recency bias). Entries that carry the message
 * itself come first, and each sits out a day after it's used, so a handful of quotes doesn't repeat every turn; the
 * summary-only entries fill in meanwhile (see chooseEntries). A Firestore TTL policy deletes every entry 30 days
 * after it was saved. Empty array only if the collection is empty.
 */
export async function pickContext(language: Language, n = 1): Promise<ContextEntry[]> {
  const col = collection(db, COLLECTION)
  const field = usedField(language)
  // orderBy('sentAt') returns only the docs that have the field, which is the quoted ones.
  const quoted = (await getDocs(query(col, orderBy('sentAt', 'desc'), limit(WINDOW)))).docs
  const recent = (await getDocs(query(col, orderBy('createdAt', 'desc'), limit(WINDOW)))).docs
  const summaries = recent.filter((d) => !(typeof d.data().quote === 'string' && d.data().quote))
  const chosen = chooseEntries(quoted, summaries, (d) => toMillis(d.data()[field]), Date.now(), n)
  console.log('[pickContext]', language, { quoted: quoted.length, summaries: summaries.length,
    chosen: chosen.map((d) => d.id) })
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
    source: entry.source || 'signal',
    preview: !!entry.preview,
    sender: entry.sender || 'someone',
    to: entry.to ?? null,
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
