/** How long a quoted message sits out after it leads a sentence in one language. */
export const QUOTE_REST_MS = 24 * 3600 * 1000
/** Pick at random among this many of the least recently used entries, for variety. */
export const LRU_POOL = 8

/**
 * Which entries feed the next sentence. Quoted messages (the message as written) come first: never used, then least
 * recently used, with light randomness among the least-used few. A quote used in the last QUOTE_REST_MS sits out, so
 * a small quoted pool doesn't repeat one message every turn. The summary-only entries fill in then, and a resting
 * quote comes back only when there are no summaries either. `usedAt` gives 0 for never used.
 */
export function chooseEntries<T>(
  quoted: T[],
  summaries: T[],
  usedAt: (d: T) => number,
  now: number,
  n: number,
  rand: () => number = Math.random,
): T[] {
  const rested = quoted.filter((d) => now - usedAt(d) >= QUOTE_REST_MS)
  const from =
    rested.length >= n ? rested : summaries.length >= n ? summaries : quoted.length ? quoted : summaries
  const pool = [...from].sort((a, b) => usedAt(a) - usedAt(b)).slice(0, Math.max(LRU_POOL, n))
  return pool
    .map((d) => ({ d, key: rand() }))
    .sort((a, b) => a.key - b.key)
    .slice(0, n)
    .map(({ d }) => d)
}
