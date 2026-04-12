import { createBrowserRouter } from 'react-router-dom'
import { App } from './App'
import { LoginPage } from '@/components/auth/LoginPage'
import { SummaryReport } from '@/components/reports/SummaryReport'
import { MRRReport } from '@/components/reports/MRRReport'
import { ChurnReport } from '@/components/reports/ChurnReport'
import { RetentionReport } from '@/components/reports/RetentionReport'
import { LTVReport } from '@/components/reports/LTVReport'
import { TrialsReport } from '@/components/reports/TrialsReport'
import { DashboardList } from '@/components/dashboards/DashboardList'
import { DashboardEditor } from '@/components/dashboards/DashboardEditor'
import { APIKeyManager } from '@/components/settings/APIKeyManager'

export const router = createBrowserRouter([
  {
    path: '/login',
    element: <LoginPage />,
  },
  {
    path: '/',
    element: <App />,
    children: [
      { index: true, element: <SummaryReport /> },
      { path: 'dashboards', element: <DashboardList /> },
      { path: 'dashboards/:id', element: <DashboardEditor /> },
      { path: 'reports/mrr', element: <MRRReport /> },
      { path: 'reports/churn', element: <ChurnReport /> },
      { path: 'reports/retention', element: <RetentionReport /> },
      { path: 'reports/ltv', element: <LTVReport /> },
      { path: 'reports/trials', element: <TrialsReport /> },
      { path: 'settings/api-keys', element: <APIKeyManager /> },
    ],
  },
])
