import { Link, useParams } from 'react-router-dom'
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from '@/components/ui/breadcrumb'

interface Crumb {
  label: string
  href?: string
}

type Params = {
  station?: string
  show?: string
  year?: string
  month?: string
} & Record<string, string | undefined>

function buildCrumbs(params: Params): Crumb[] {
  const crumbs: Crumb[] = [{ label: 'Shows', href: '/shows' }]
  const station = params.station
  if (!station) return crumbs
  crumbs.push({
    label: station,
    href: `/shows/${encodeURIComponent(station)}`,
  })
  const show = params.show
  if (!show) return crumbs
  const showHref = `/shows/${encodeURIComponent(station)}/${encodeURIComponent(show)}`
  crumbs.push({ label: decodeURIComponent(show), href: showHref })
  if (!params.year) return crumbs
  const yearHref = `${showHref}/${params.year}`
  crumbs.push({ label: params.year, href: yearHref })
  if (params.month) {
    crumbs.push({
      label: String(params.month).padStart(2, '0'),
    })
  }
  return crumbs
}

export function BreadcrumbTrail() {
  const params = useParams<Params>()
  const crumbs = buildCrumbs(params)
  return (
    <Breadcrumb>
      <BreadcrumbList>
        {crumbs.map((crumb, i) => {
          const isLast = i === crumbs.length - 1
          return (
            <span key={crumb.href ?? crumb.label} className="contents">
              <BreadcrumbItem>
                {isLast || !crumb.href ? (
                  <BreadcrumbPage>{crumb.label}</BreadcrumbPage>
                ) : (
                  <BreadcrumbLink asChild>
                    <Link to={crumb.href}>{crumb.label}</Link>
                  </BreadcrumbLink>
                )}
              </BreadcrumbItem>
              {!isLast && <BreadcrumbSeparator />}
            </span>
          )
        })}
      </BreadcrumbList>
    </Breadcrumb>
  )
}
