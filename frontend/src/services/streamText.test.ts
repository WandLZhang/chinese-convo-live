import { describe, it, expect } from 'vitest'
import { latestSentence, RETRY_MARK } from './streamText'

describe('latestSentence (the generator rewrote a sentence that left out the word)', () => {
  it('shows the stream as is when nothing was rewritten', () => {
    expect(latestSentence('你今天怎么样？')).toBe('你今天怎么样？')
  })

  it('shows only the rewrite once the mark arrives', () => {
    expect(latestSentence(`第一句没有那个词。${RETRY_MARK}第二句用到了停顿。`)).toBe('第二句用到了停顿。')
  })

  it('shows nothing past the mark until the rewrite streams in', () => {
    expect(latestSentence(`第一句。${RETRY_MARK}`)).toBe('')
  })
})
