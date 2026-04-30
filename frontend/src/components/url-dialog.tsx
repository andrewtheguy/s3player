import { Check, Copy } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

interface Props {
  url: string | null
  onClose: () => void
}

export function UrlDialog({ url, onClose }: Props) {
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (!copied) return
    const t = window.setTimeout(() => setCopied(false), 1500)
    return () => window.clearTimeout(t)
  }, [copied])

  async function copy() {
    if (!url) return
    await navigator.clipboard.writeText(url)
    setCopied(true)
  }

  return (
    <Dialog open={url !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Signed URL</DialogTitle>
          <DialogDescription>Valid for 24 hours.</DialogDescription>
        </DialogHeader>
        {url && (
          <code className="block w-full break-all rounded-md bg-muted p-3 font-mono text-xs">
            {url}
          </code>
        )}
        <DialogFooter className="gap-2 sm:gap-2">
          <Button variant="outline" onClick={copy}>
            {copied ? <Check /> : <Copy />}
            {copied ? 'Copied' : 'Copy'}
          </Button>
          {url && (
            <Button asChild>
              <a href={url} target="_blank" rel="noreferrer">
                Open in new tab
              </a>
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
