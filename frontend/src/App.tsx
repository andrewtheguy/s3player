import { useEffect, useState } from 'react'
import './App.css'

type S3File = {
  name: string
  size: number
  last_modified: string
}

type ListResponse = {
  directories: string[]
  files: S3File[]
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024)
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`
}

function App() {
  const [status, setStatus] = useState<string>('loading…')
  const [listing, setListing] = useState<ListResponse | null>(null)
  const [listError, setListError] = useState<string | null>(null)

  useEffect(() => {
    fetch('/api/health')
      .then((r) => r.json())
      .then((d) => setStatus(d.status))
      .catch((e) => setStatus(`error: ${e.message}`))

    fetch('/api/s3/list')
      .then(async (r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}: ${await r.text()}`)
        return r.json() as Promise<ListResponse>
      })
      .then(setListing)
      .catch((e) => setListError(e.message))
  }, [])

  return (
    <main style={{ fontFamily: 'system-ui, sans-serif', padding: '2rem' }}>
      <h1>s3player</h1>
      <p>
        backend status: <strong>{status}</strong>
      </p>

      <h2>bucket contents (top level)</h2>
      {listError && <p style={{ color: 'crimson' }}>error: {listError}</p>}
      {!listError && !listing && <p>loading…</p>}
      {listing && (
        <>
          {listing.directories.length === 0 && listing.files.length === 0 && (
            <p>
              <em>(empty)</em>
            </p>
          )}
          {listing.directories.length > 0 && (
            <ul>
              {listing.directories.map((d) => (
                <li key={d}>
                  <strong>{d}/</strong>
                </li>
              ))}
            </ul>
          )}
          {listing.files.length > 0 && (
            <table style={{ borderCollapse: 'collapse', marginTop: '0.5rem' }}>
              <thead>
                <tr>
                  <th
                    style={{
                      textAlign: 'left',
                      padding: '0.25rem 1rem 0.25rem 0',
                    }}
                  >
                    name
                  </th>
                  <th
                    style={{
                      textAlign: 'right',
                      padding: '0.25rem 1rem 0.25rem 0',
                    }}
                  >
                    size
                  </th>
                  <th style={{ textAlign: 'left', padding: '0.25rem 0' }}>
                    modified
                  </th>
                </tr>
              </thead>
              <tbody>
                {listing.files.map((f) => (
                  <tr key={f.name}>
                    <td style={{ padding: '0.25rem 1rem 0.25rem 0' }}>
                      {f.name}
                    </td>
                    <td
                      style={{
                        textAlign: 'right',
                        padding: '0.25rem 1rem 0.25rem 0',
                      }}
                    >
                      {formatSize(f.size)}
                    </td>
                    <td style={{ padding: '0.25rem 0' }}>
                      {new Date(f.last_modified).toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </main>
  )
}

export default App
