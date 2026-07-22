import { useMemo } from 'react'
import { marked } from 'marked'
import DOMPurify from 'dompurify'

/** Renders model-produced markdown as sanitized HTML. */
export default function Markdown({
  text,
  className,
}: {
  text: string
  className?: string
}) {
  const html = useMemo(() => {
    const raw = marked.parse(text, { async: false, breaks: true }) as string
    return DOMPurify.sanitize(raw)
  }, [text])
  return <div className={className} dangerouslySetInnerHTML={{ __html: html }} />
}
