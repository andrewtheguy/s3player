import { useEffect } from 'react'

const BRAND = 's3player'

export function useDocumentTitle(title: string | null | undefined): void {
  useEffect(() => {
    document.title = title ? `${title} · ${BRAND}` : BRAND
  }, [title])
}
