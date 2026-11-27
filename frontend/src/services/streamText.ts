/** The generator sends this, then a rewritten sentence, when the streamed one left out the word. */
export const RETRY_MARK = '\u001e'

/** The sentence to show: whatever follows the last RETRY_MARK, or the whole stream when there's none. */
export function latestSentence(streamed: string): string {
  const i = streamed.lastIndexOf(RETRY_MARK)
  return i >= 0 ? streamed.slice(i + RETRY_MARK.length) : streamed
}
