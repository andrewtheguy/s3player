import { Outlet } from 'react-router-dom'
import { AppHeader } from '@/components/app-header'
import { PlayerSessionProvider } from '@/lib/playerSession'

export function RootLayout() {
  return (
    <PlayerSessionProvider>
      <div className="min-h-svh bg-background text-foreground">
        <AppHeader />
        <main className="container mx-auto px-6 py-8">
          <Outlet />
        </main>
      </div>
    </PlayerSessionProvider>
  )
}
