export function formatRelative(iso: string): string {
  const ts = Date.parse(iso)
  if (Number.isNaN(ts)) return ''
  const diffMs = Date.now() - ts
  const future = diffMs < 0
  const fmt = (value: string) => (future ? `in ${value}` : `${value} ago`)
  const sec = Math.floor(Math.abs(diffMs) / 1000)
  if (sec < 60) return fmt(`${sec}s`)
  const min = Math.floor(sec / 60)
  if (min < 60) return fmt(`${min}m`)
  const hr = Math.floor(min / 60)
  if (hr < 24) return fmt(`${hr}h`)
  const day = Math.floor(hr / 24)
  if (day < 7) return fmt(`${day}d`)
  const week = Math.floor(day / 7)
  if (week < 5) return fmt(`${week}w`)
  return new Date(ts).toLocaleDateString()
}

export function formatAbsolute(iso: string): string {
  const ts = Date.parse(iso)
  if (Number.isNaN(ts)) return iso
  return new Date(ts).toLocaleString()
}

export function formatPosition(ms: number): string {
  const totalSec = Math.floor(Math.max(0, ms) / 1000)
  const h = Math.floor(totalSec / 3600)
  const m = Math.floor((totalSec % 3600) / 60)
  const s = totalSec % 60
  const mm = String(m).padStart(2, '0')
  const ss = String(s).padStart(2, '0')
  return h > 0 ? `${h}:${mm}:${ss}` : `${m}:${ss}`
}

export function formatTimeSlot(slot: string | null): string {
  if (!slot) return ''
  const m = /^(\d{2})(\d{2})_(\d{2})(\d{2})$/.exec(slot)
  if (!m) return slot
  return `${m[1]}:${m[2]}–${m[3]}:${m[4]}`
}
