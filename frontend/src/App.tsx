import { BrowserRouter } from 'react-router-dom'
import { AppRouter } from '@/routes/router'

export default function App() {
  return (
    <BrowserRouter>
      <AppRouter />
    </BrowserRouter>
  )
}
