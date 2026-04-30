import { Link } from 'react-router-dom'

export function AppHeader() {
  return (
    <header className="sticky top-0 z-10 border-b bg-background/80 backdrop-blur">
      <div className="container mx-auto flex flex-col gap-2 px-6 py-3">
        <Link to="/stations" className="text-lg font-semibold tracking-tight">
          s3player
        </Link>
      </div>
    </header>
  )
}
