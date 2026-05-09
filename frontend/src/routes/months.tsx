import { Link, useParams } from 'react-router-dom'
import { BreadcrumbTrail } from '@/components/breadcrumb-trail'
import type { MonthsResponse } from '@/lib/api'
import { formatTwoDigit } from '@/lib/episode-path'
import { useDocumentTitle } from '@/lib/use-document-title'
import { useFetch } from '@/lib/use-fetch'

const MONTH_NAMES = [
  'Jan',
  'Feb',
  'Mar',
  'Apr',
  'May',
  'Jun',
  'Jul',
  'Aug',
  'Sep',
  'Oct',
  'Nov',
  'Dec',
]

export function MonthsPage() {
  const { show_id, year } = useParams<{
    show_id: string
    year: string
  }>()
  const { data, error, loading } = useFetch<MonthsResponse>(
    `/api/shows/${show_id}/months`,
  )

  useDocumentTitle(
    data?.show ? `${data.show.name} — ${year}` : (year ?? 'Months'),
  )

  if (loading) return <p className="text-muted-foreground">Loading months…</p>
  if (error) return <p className="text-destructive">Error: {error}</p>
  const show = data?.show
  const yearNum = Number(year)
  const months = (data?.months ?? [])
    .filter((m) => m.year === yearNum)
    .sort((a, b) => a.month - b.month)

  const crumbs = show
    ? [
        { label: 'Stations', href: '/stations' },
        {
          label: show.station,
          href: `/stations/${encodeURIComponent(show.station)}`,
        },
        { label: show.name, href: `/shows/${show.id}` },
        { label: year ?? '' },
      ]
    : []

  return (
    <div className="space-y-6">
      <BreadcrumbTrail crumbs={crumbs} />
      {months.length === 0 ? (
        <p className="text-muted-foreground">No episodes for {year} yet.</p>
      ) : (
        <div>
          <h1 className="mb-6 text-2xl font-semibold tracking-tight">
            {show?.name} — {year}
          </h1>
          <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {months.map((m) => (
              <li key={`${m.year}-${m.month}`}>
                <Link
                  to={`/shows/${show_id}/${m.year}/${formatTwoDigit(m.month)}`}
                  className="block rounded-lg border bg-card p-5 transition-colors hover:bg-accent"
                >
                  <div className="font-medium">
                    {formatTwoDigit(m.month)}-{MONTH_NAMES[m.month - 1]}
                  </div>
                  <div className="text-sm text-muted-foreground">
                    {m.episode_count}{' '}
                    {m.episode_count === 1 ? 'episode' : 'episodes'}
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
