import { Navigate, Route, Routes } from 'react-router-dom'
import { EpisodesPage } from '@/routes/episodes'
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
        <Route index element={<Navigate to="/shows" replace />} />
        <Route path="shows" element={<StationsPage />} />
        <Route path="shows/:station" element={<ShowsPage />} />
        <Route path="shows/:station/:show" element={<YearsPage />} />
        <Route path="shows/:station/:show/:year" element={<MonthsPage />} />
        <Route
          path="shows/:station/:show/:year/:month/:day/:episodeFile"
          element={<PlayerPage />}
        />
        <Route
          path="shows/:station/:show/:year/:month"
          element={<EpisodesPage />}
        />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  )
}
