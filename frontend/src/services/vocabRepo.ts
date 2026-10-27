import {
  collection,
  doc,
  documentId,
  getCountFromServer,
  getDocs,
  limit,
  orderBy,
  query,
  startAfter,
  Timestamp,
  where,
  type DocumentData,
  type QueryDocumentSnapshot,
  type QuerySnapshot,
} from 'firebase/firestore'
import { db } from './firebase'
import type { Language, VocabEntry } from '../types'
import {
  reviewField,
  masteredField,
  isNew,
  isScheduled,
  isMastered,
  getReviewDate,
  minutesUntil,
  pickNext,
  pickLearnAhead,
  LEARN_AHEAD_MIN,
} from './srs'

const COLLECTION = 'vocabulary'
/** Docs read per page when scanning for never-reviewed words. */
const NEW_SCAN_PAGE = 100

function toEntry(id: string, data: DocumentData): VocabEntry {
  return {
    id,
    simplified: String(data.simplified ?? ''),
    mandarin: String(data.mandarin ?? ''),
    cantonese: String(data.cantonese ?? ''),
    ...data,
  } as VocabEntry
}

/**
 * Up to `max` never-reviewed (in this language) words, oldest first. Firestore can't query
 * for a missing field, so this pages through the collection by `timestamp` and filters here
 * (fixes the old single 50-doc window, which ran dry once its 50 oldest words were reviewed).
 */
async function findNewVocab(language: Language, max: number): Promise<VocabEntry[]> {
  const vocabRef = collection(db, COLLECTION)
  const found: VocabEntry[] = []
  let cursor: QueryDocumentSnapshot | null = null
  for (;;) {
    const page: QuerySnapshot = await getDocs(
      cursor
        ? query(vocabRef, orderBy('timestamp'), startAfter(cursor), limit(NEW_SCAN_PAGE))
        : query(vocabRef, orderBy('timestamp'), limit(NEW_SCAN_PAGE)),
    )
    for (const d of page.docs) {
      if (!isNew(d.data(), language)) continue
      found.push(toEntry(d.id, d.data()))
      if (found.length >= max) return found
    }
    if (page.size < NEW_SCAN_PAGE) return found
    cursor = page.docs[page.docs.length - 1]
  }
}

export interface NextVocabResult {
  vocab: VocabEntry | null
  message?: string
}

/**
 * Word selection in AnkiDroid's order:
 *   1) a learning word (new or failed, in its 1-10 minute steps) that has fallen due, earliest first;
 *   2) review words that are due, oldest first;
 *   3) the oldest never-reviewed word;
 *   4) learn-ahead: a learning word due within LEARN_AHEAD_MIN;
 *   5) a message about the next scheduled review.
 * Before this, every due word was served most recently due first, so each word passed 3 days
 * earlier jumped ahead of words that had waited months.
 */
export async function selectNextVocab(language: Language): Promise<NextVocabResult> {
  const vocabRef = collection(db, COLLECTION)
  const now = Timestamp.now()
  const rf = reviewField(language)
  const dataOf = (d: QueryDocumentSnapshot) => d.data()

  // 1-2) Everything due. No cap: the due set is small, and a cap could hide the oldest words.
  const dueSnap = await getDocs(query(vocabRef, where(rf, '<=', now), orderBy(rf)))
  const due = pickNext(dueSnap.docs, dataOf, language, now.toDate())
  if (due) {
    const vocab = toEntry(due.id, due.data())
    console.log('[selectNextVocab] due:', vocab)
    return { vocab }
  }

  // 3) Oldest never-reviewed (in this language) word.
  const [fresh] = await findNewVocab(language, 1)
  if (fresh) {
    console.log('[selectNextVocab] new:', fresh)
    return { vocab: fresh }
  }

  // 4) Learn ahead rather than make you wait out a learning step.
  const soonSnap = await getDocs(
    query(
      vocabRef,
      where(rf, '>', now),
      where(rf, '<=', Timestamp.fromMillis(now.toMillis() + LEARN_AHEAD_MIN * 60000)),
      orderBy(rf),
    ),
  )
  const ahead = pickLearnAhead(soonSnap.docs, dataOf, language, now.toDate())
  if (ahead) {
    const vocab = toEntry(ahead.id, ahead.data())
    console.log('[selectNextVocab] learn ahead:', vocab)
    return { vocab }
  }

  // 5) Nothing available now — report time until the next scheduled review.
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

  // Every word with a review time, earliest first. No limit: it only grows as words get reviewed.
  const scheduledSnap = await getDocs(query(vocabRef, orderBy(rf)))
  const scheduled = scheduledSnap.docs
    .filter((d) => isScheduled(d.data(), language))
    .map((d) => toEntry(d.id, d.data()))

  // Equality filter only, newest first sorted here: adding orderBy('timestamp') to the query
  // needs a composite index, and without one Firestore rejected it and blanked the drawer.
  const masteredSnap = await getDocs(query(vocabRef, where(mf, '==', true)))
  const millis = (e: VocabEntry) => e.timestamp?.toDate().getTime() ?? 0
  const mastered = masteredSnap.docs
    .map((d) => toEntry(d.id, d.data()))
    .sort((a, b) => millis(b) - millis(a))

  const fresh = await findNewVocab(language, 50)

  const lists = { scheduled, new: fresh, mastered }
  console.log('[fetchWordLists]', language, lists)
  return lists
}
