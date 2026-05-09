import { Navigate, Route, Routes } from 'react-router-dom'
import { EpisodesPage } from '@/routes/episodes'
import { FavoritesPage } from '@/routes/favorites'
import { MonthsPage } from '@/routes/months'
import { PlayerPage } from '@/routes/player'
import { RootLayout } from '@/routes/root'
import { ShowsPage } from '@/routes/shows'
import { StationsPage } from '@/routes/stations'
import { YearsPage } from '@/routes/years'

function NotFound() {
  return <p className="text-muted-foreground">Page not found.</p>
}

export function AppRouter() {
  return (
    <Routes>
      <Route element={<RootLayout />}>
        <Route index element={<Navigate to="/stations" replace />} />
        <Route path="stations" element={<StationsPage />} />
        <Route path="stations/:station" element={<ShowsPage />} />
        <Route path="shows/:show_id" element={<YearsPage />} />
        <Route path="shows/:show_id/:year" element={<MonthsPage />} />
        <Route path="shows/:show_id/:year/:month" element={<EpisodesPage />} />
        <Route path="favorites/:show_id" element={<FavoritesPage />} />
        <Route path="player/:episode_id" element={<PlayerPage />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  )
}
