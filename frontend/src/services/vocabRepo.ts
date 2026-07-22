import {
  collection,
  doc,
  documentId,
  getCountFromServer,
  getDocs,
  limit,
  orderBy,
  query,
  Timestamp,
  where,
  type DocumentData,
} from 'firebase/firestore'
import { db } from './firebase'
import type { Language, VocabEntry } from '../types'
import {
  reviewField,
  masteredField,
  isDue,
  isNew,
  isScheduled,
  isMastered,
  getReviewDate,
  minutesUntil,
} from './srs'

const COLLECTION = 'vocabulary'

function toEntry(id: string, data: DocumentData): VocabEntry {
  return {
    id,
    simplified: String(data.simplified ?? ''),
    mandarin: String(data.mandarin ?? ''),
    cantonese: String(data.cantonese ?? ''),
    ...data,
  } as VocabEntry
}

export interface NextVocabResult {
  vocab: VocabEntry | null
  message?: string
}

/**
 * Word selection, ported from the old App.tsx fetchNextVocab:
 * due-first (review time <= now, not mastered) -> oldest new word
 * (no review time, not mastered) -> a message about the next scheduled review.
 */
export async function selectNextVocab(language: Language): Promise<NextVocabResult> {
  const vocabRef = collection(db, COLLECTION)
  const now = Timestamp.now()
  const rf = reviewField(language)

  // 1) Due for review.
  const dueSnap = await getDocs(query(vocabRef, where(rf, '<=', now), limit(50)))
  const due = dueSnap.docs.find((d) => isDue(d.data(), language, now.toDate()))
  if (due) return { vocab: toEntry(due.id, due.data()) }

  // 2) Oldest never-reviewed (in this language) word.
  const newSnap = await getDocs(query(vocabRef, orderBy('timestamp'), limit(50)))
  const fresh = newSnap.docs.find((d) => isNew(d.data(), language))
  if (fresh) return { vocab: toEntry(fresh.id, fresh.data()) }

  // 3) Nothing available now — report time until the next scheduled review.
  const nextSnap = await getDocs(
    query(vocabRef, where(rf, '>', now), orderBy(rf), limit(1)),
  )
  const next = nextSnap.docs.find((d) => !isMastered(d.data(), language))
  const reviewDate = next ? getReviewDate(next.data(), language) : null
  if (reviewDate) {
    return {
      vocab: null,
      message: `Next review available in ${minutesUntil(reviewDate, now.toDate())} minutes`,
    }
  }
  return { vocab: null, message: 'No vocabulary available' }
}

/**
 * A uniformly-random vocab word via the auto-ID boundary trick (docs have
 * random IDs): pick a random ID, take the first doc at/after it, wrapping
 * around if needed. One document read, no timestamp bias (fixes the old
 * fetchRandomVocab that only sampled the oldest 100).
 */
export async function selectRandomVocab(): Promise<VocabEntry | null> {
  const vocabRef = collection(db, COLLECTION)
  const countSnap = await getCountFromServer(vocabRef)
  if (countSnap.data().count === 0) return null

  const randomId = doc(vocabRef).id
  let snap = await getDocs(
    query(vocabRef, where(documentId(), '>=', randomId), orderBy(documentId()), limit(1)),
  )
  if (snap.empty) {
    snap = await getDocs(
      query(vocabRef, where(documentId(), '<', randomId), orderBy(documentId()), limit(1)),
    )
  }
  if (snap.empty) return null
  const d = snap.docs[0]
  return toEntry(d.id, d.data())
}

export interface WordLists {
  scheduled: VocabEntry[]
  new: VocabEntry[]
  mastered: VocabEntry[]
}

export async function fetchWordLists(language: Language): Promise<WordLists> {
  const vocabRef = collection(db, COLLECTION)
  const rf = reviewField(language)
  const mf = masteredField(language)

  const scheduledSnap = await getDocs(query(vocabRef, orderBy(rf), limit(50)))
  const scheduled = scheduledSnap.docs
    .filter((d) => isScheduled(d.data(), language))
    .map((d) => toEntry(d.id, d.data()))

  const masteredSnap = await getDocs(
    query(vocabRef, where(mf, '==', true), orderBy('timestamp', 'desc'), limit(50)),
  )
  const mastered = masteredSnap.docs.map((d) => toEntry(d.id, d.data()))

  const newSnap = await getDocs(query(vocabRef, orderBy('timestamp'), limit(50)))
  const fresh = newSnap.docs
    .filter((d) => isNew(d.data(), language))
    .map((d) => toEntry(d.id, d.data()))

  return { scheduled, new: fresh, mastered }
}
