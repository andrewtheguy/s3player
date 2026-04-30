import { useEffect, useState } from 'react'
import './App.css'

function App() {
  const [status, setStatus] = useState<string>('loading…')

  useEffect(() => {
    fetch('/api/health')
      .then((r) => r.json())
      .then((d) => setStatus(d.status))
      .catch((e) => setStatus(`error: ${e.message}`))
  }, [])

  return (
    <main style={{ fontFamily: 'system-ui, sans-serif', padding: '2rem' }}>
      <h1>s3player</h1>
      <p>
        backend status: <strong>{status}</strong>
      </p>
    </main>
  )
}

export default App
