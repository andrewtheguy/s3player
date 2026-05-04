import { useState } from 'react'
import type { ChapterSummariesResponse } from '@/lib/api'
import { useFetch } from '@/lib/use-fetch'

interface Props {
  episodeId: number
}

function formatChapterLabel(index: number): string {
  return `Chapter ${String(index).padStart(2, '0')}`
}

export function ChapterSummaries({ episodeId }: Props) {
  const { data } = useFetch<ChapterSummariesResponse>(
    `/api/shows/episodes/${episodeId}/chapter_summaries`,
  )
  const [expanded, setExpanded] = useState<ReadonlySet<number>>(new Set())

  const summaries = data?.summaries ?? []
  if (summaries.length === 0) return null

  const toggle = (index: number) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(index)) next.delete(index)
      else next.add(index)
      return next
    })
  }

  return (
    <section className="space-y-2">
      <div className="flex items-baseline justify-between">
        <h2 className="text-base font-semibold tracking-tight">
          Chapter summaries
        </h2>
        <span className="text-xs text-muted-foreground">
          {summaries.length}
        </span>
      </div>
      <div className="overflow-hidden rounded-md border">
        {summaries.map((s) => {
          const isOpen = expanded.has(s.index)
          return (
            <div key={s.index} className="border-b last:border-b-0">
              <button
                type="button"
                onClick={() => toggle(s.index)}
                aria-expanded={isOpen}
                className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm hover:bg-accent"
              >
                <span className="truncate">{formatChapterLabel(s.index)}</span>
                <span
                  aria-hidden
                  className="shrink-0 font-mono text-xs text-muted-foreground"
                >
                  {isOpen ? '▼' : '▶'}
                </span>
              </button>
              {isOpen && (
                <pre className="whitespace-pre-wrap break-words border-t bg-muted/30 px-3 py-2 font-sans text-sm">
                  {s.content}
                </pre>
              )}
            </div>
          )
        })}
      </div>
    </section>
  )
}
